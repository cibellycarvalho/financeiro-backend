from unittest.mock import patch

FORN = "33333333-0000-0000-0000-000000000001"
BASE = f"/api/fornecedores/{FORN}/devolucoes"


def test_registrar_devolucao_grava_e_devolve_201(client, admin_headers):
    gravada = {"id": "d1", "valor": 1200.0, "data_devolucao": "2026-10-05"}
    with patch("routes.fornecedores.db.query", return_value=[{"id": FORN}]), \
         patch("routes.fornecedores.db.execute", return_value=gravada) as ex:
        resp = client.post(BASE, headers=admin_headers,
                           json={"valor": 1200, "data_devolucao": "2026-10-05", "descricao": "devolução"})
    assert resp.status_code == 201
    assert "fin_devolucoes_fornecedor" in ex.call_args[0][0]


def test_registrar_devolucao_recusa_valor_zero_e_data_ruim(client, admin_headers):
    r1 = client.post(BASE, headers=admin_headers, json={"valor": 0, "data_devolucao": "2026-10-05"})
    r2 = client.post(BASE, headers=admin_headers, json={"valor": 10, "data_devolucao": "05/10/2026"})
    assert r1.status_code == 400 and r2.status_code == 400


def test_registrar_devolucao_fornecedor_inexistente(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.post(BASE, headers=admin_headers, json={"valor": 10, "data_devolucao": "2026-10-05"})
    assert resp.status_code == 404


def test_saldo_desconta_devolucoes():
    import routes.fornecedores as f
    with patch("routes.fornecedores.db.query", return_value=[{"saldo_aberto": 100}]) as q:
        f._saldo_aberto_fornecedor(FORN)
    assert "fin_devolucoes_fornecedor" in q.call_args[0][0]
    assert len(q.call_args[0][1]) == 3


def test_excluir_devolucao(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[{"id": "d1"}]), \
         patch("routes.fornecedores.db.execute") as ex:
        resp = client.delete(f"{BASE}/d1", headers=admin_headers)
    assert resp.status_code == 204
    assert "DELETE" in ex.call_args[0][0]


def _post(client, admin_headers, **extra):
    corpo = {"valor": 100, "data_devolucao": "2026-10-13", **extra}
    with patch("routes.fornecedores.db.query", return_value=[{"id": FORN}]), \
         patch("routes.fornecedores.db.execute", return_value={"id": "d1"}) as ex:
        resp = client.post(BASE, headers=admin_headers, json=corpo)
    return resp, ex


def test_registrar_devolucao_sem_forma_vira_credito(client, admin_headers):
    resp, ex = _post(client, admin_headers)
    assert resp.status_code == 201
    assert "forma" in ex.call_args[0][0]
    assert "credito" in ex.call_args[0][1]


def test_registrar_devolucao_em_dinheiro(client, admin_headers):
    resp, ex = _post(client, admin_headers, forma="dinheiro")
    assert resp.status_code == 201
    assert "dinheiro" in ex.call_args[0][1]


def test_registrar_devolucao_recusa_forma_desconhecida(client, admin_headers):
    resp, _ = _post(client, admin_headers, forma="cheque")
    assert resp.status_code == 400


def test_editar_devolucao_troca_forma_e_valor(client, admin_headers):
    atual = {"id": "d1", "valor": 100, "data_devolucao": "2026-10-13", "forma": "credito",
             "pedido_id": None, "descricao": None}
    with patch("routes.fornecedores.db.query", return_value=[atual]), \
         patch("routes.fornecedores.db.execute", return_value={**atual, "forma": "dinheiro", "valor": 250}) as ex:
        resp = client.put(f"{BASE}/d1", headers=admin_headers, json={"valor": 250, "forma": "dinheiro"})
    assert resp.status_code == 200
    sql, params = ex.call_args[0]
    assert "UPDATE fin_devolucoes_fornecedor" in sql
    assert 250.0 in params and "dinheiro" in params


def test_editar_devolucao_inexistente(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.put(f"{BASE}/d1", headers=admin_headers, json={"forma": "dinheiro"})
    assert resp.status_code == 404


def test_editar_devolucao_recusa_valor_e_forma_ruins(client, admin_headers):
    atual = {"id": "d1", "valor": 100, "data_devolucao": "2026-10-13", "forma": "credito",
             "pedido_id": None, "descricao": None}
    with patch("routes.fornecedores.db.query", return_value=[atual]):
        r1 = client.put(f"{BASE}/d1", headers=admin_headers, json={"valor": -5})
        r2 = client.put(f"{BASE}/d1", headers=admin_headers, json={"forma": "cheque"})
    assert r1.status_code == 400 and r2.status_code == 400


def test_devolucoes_em_dinheiro_do_periodo(client, admin_headers):
    linhas = [{"id": "d1", "valor": 300, "data_devolucao": "2026-10-13", "fornecedor_nome": "Tânia"}]
    with patch("routes.fornecedores.db.query", return_value=linhas) as q:
        resp = client.get("/api/fornecedores/devolucoes?de=2026-10-12&ate=2026-10-18", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json() == linhas
    sql, params = q.call_args[0]
    assert "forma = 'dinheiro'" in sql
    assert params == ("2026-10-12", "2026-10-18")


def test_devolucoes_do_periodo_exige_datas_validas(client, admin_headers):
    resp = client.get("/api/fornecedores/devolucoes?de=ontem&ate=2026-10-18", headers=admin_headers)
    assert resp.status_code == 400


def test_so_credito_abate_o_saldo_devedor():
    """Dinheiro de volta desfaz um pagamento: a dívida continua a mesma. Se
    abatesse de novo, quem já pagou ficava com "Ainda devo" negativo."""
    import routes.fornecedores as f
    with patch("routes.fornecedores.db.query", return_value=[{"saldo_aberto": 0}]) as q:
        f._saldo_aberto_fornecedor(FORN)
    assert "forma = 'credito'" in q.call_args[0][0]
