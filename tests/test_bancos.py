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
