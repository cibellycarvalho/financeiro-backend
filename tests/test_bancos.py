from contextlib import contextmanager
from unittest.mock import patch, MagicMock

CONTA = {"id": "c1", "nome": "Itaú", "principal": True, "saldo": 9870.0, "saldo_em": None, "ativo": True}


def _transacao(row=CONTA):
    cur = MagicMock()
    cur.fetchone.return_value = row

    @contextmanager
    def transaction():
        yield cur
    return cur, transaction


def test_lista_principal_primeiro(client, admin_headers):
    with patch("routes.bancos.db.query", return_value=[CONTA]) as q:
        r = client.get("/api/bancos", headers=admin_headers)
    assert r.status_code == 200 and r.get_json() == [CONTA]
    assert "ORDER BY principal DESC" in q.call_args[0][0]


def test_criar_principal_desmarca_a_antiga(client, admin_headers):
    cur, tx = _transacao()
    with patch("routes.bancos.db.transaction", tx):
        r = client.post("/api/bancos", headers=admin_headers, json={"nome": " Itaú ", "principal": True})
    assert r.status_code == 201
    sqls = [c[0][0] for c in cur.execute.call_args_list]
    assert "SET principal = false" in sqls[0]
    assert cur.execute.call_args_list[1][0][1] == ("Itaú", True)


def test_criar_sem_nome_400(client, admin_headers):
    r = client.post("/api/bancos", headers=admin_headers, json={"nome": "  "})
    assert r.status_code == 400


def test_atualizar_saldo_grava_a_hora(client, admin_headers):
    cur, tx = _transacao()
    with patch("routes.bancos.db.transaction", tx):
        r = client.put("/api/bancos/c1", headers=admin_headers, json={"saldo": 9870.5})
    assert r.status_code == 200
    sql, params = cur.execute.call_args[0]
    assert "saldo = %s, saldo_em = now()" in sql and params == (9870.5, "c1")


def test_saldo_texto_400(client, admin_headers):
    r = client.put("/api/bancos/c1", headers=admin_headers, json={"saldo": "abc"})
    assert r.status_code == 400


def test_conta_inexistente_404(client, admin_headers):
    cur, tx = _transacao(row=None)
    with patch("routes.bancos.db.transaction", tx):
        r = client.put("/api/bancos/zz", headers=admin_headers, json={"nome": "X"})
    assert r.status_code == 404


def test_importar_extrato_grava_e_atualiza_saldo(client, admin_headers):
    import io
    from tests.test_conciliacao import OFX_SGML
    cur, tx = _transacao({"id": "m1"})
    with patch("routes.bancos.db.query", side_effect=[[{"id": "c1"}], [], [], []]), \
         patch("routes.bancos.db.transaction", tx):
        r = client.post("/api/bancos/c1/extrato", headers=admin_headers,
                        data={"arquivo": (io.BytesIO(OFX_SGML), "extrato.ofx")},
                        content_type="multipart/form-data")
    assert r.status_code == 201, r.get_json()
    assert r.get_json() == {"lidos": 2, "novos": 2, "saldo": 9870.5}
    sqls = [c[0][0] for c in cur.execute.call_args_list]
    assert sum("INSERT INTO fin_extrato_movimentos" in s for s in sqls) == 2
    assert "ON CONFLICT" in sqls[0]
    assert "SET saldo" in sqls[-1]


def test_confirmar_conta_marca_paga(client, admin_headers):
    cur, tx = _transacao()
    cur.fetchone.side_effect = [
        {"id": "m1", "data": "2026-10-27", "casado_tipo": "conta", "casado_id": "c9", "casado_texto": "Conta: DAS"},
        {"id": "m1", "status": "casado"},
    ]
    with patch("routes.bancos.db.transaction", tx):
        r = client.put("/api/bancos/c1/extrato/m1", headers=admin_headers, json={"acao": "confirmar"})
    assert r.status_code == 200
    sqls = [c[0][0] for c in cur.execute.call_args_list]
    assert any("UPDATE fin_contas_pagar SET status = 'pago'" in s for s in sqls)


def test_acao_invalida_400(client, admin_headers):
    r = client.put("/api/bancos/c1/extrato/m1", headers=admin_headers, json={"acao": "apagar"})
    assert r.status_code == 400


def test_importar_extrato_pdf_usa_a_leitura(client, admin_headers):
    import io
    from datetime import date
    lido = {"movimentos": [{"fitid": "pdf|1", "data": date(2026, 10, 27), "valor": -59.9, "descricao": "TARIFA"}], "saldo": 100.0}
    cur, tx = _transacao({"id": "m1"})
    with patch("routes.bancos.leitura_documento.ler_extrato", return_value=lido) as ler, \
         patch("routes.bancos.db.query", side_effect=[[{"id": "c1"}], [], [], []]), \
         patch("routes.bancos.db.transaction", tx):
        r = client.post("/api/bancos/c1/extrato", headers=admin_headers,
                        data={"arquivo": (io.BytesIO(b"%PDF-1.7 ..."), "extrato.pdf")},
                        content_type="multipart/form-data")
    assert r.status_code == 201 and r.get_json()["novos"] == 1
    assert ler.call_args[0][1] == "application/pdf"


def test_pdf_ilegivel_422(client, admin_headers):
    import io
    import leitura_documento
    with patch("routes.bancos.leitura_documento.ler_extrato", side_effect=leitura_documento.LeituraFalhou("x")):
        r = client.post("/api/bancos/c1/extrato", headers=admin_headers,
                        data={"arquivo": (io.BytesIO(b"%PDF-1.7"), "e.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 422
