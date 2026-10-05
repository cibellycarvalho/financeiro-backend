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
