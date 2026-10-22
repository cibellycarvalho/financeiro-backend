from unittest.mock import patch

import pytest

COMPRAS_USER = {"user_id": "cccc0000-0000-0000-0000-000000000001", "email": "compras@test.com",
                "fin_role": "fin_compras", "conta_ml": "M12", "is_admin": True}
H = {"Authorization": "Bearer fake"}


@pytest.fixture(autouse=True)
def como_compras(monkeypatch):
    monkeypatch.setattr("auth.verify_jwt", lambda token: COMPRAS_USER)


@pytest.mark.parametrize("metodo,url", [
    ("get", "/api/funcionarios"),
    ("get", "/api/dashboard"),
    ("get", "/api/contas"),
    ("get", "/api/planejamento/2026-10-19"),
    ("get", "/api/usuarios"),
    ("get", "/api/fornecedores/pagamentos"),
    ("get", "/api/fornecedores/f1/pagamentos"),
    ("post", "/api/fornecedores/f1/pagamentos"),
    ("post", "/api/fornecedores/f1/pedidos/p1/pago"),
    ("get", "/api/fornecedores/f1/devolucoes"),
    ("delete", "/api/fornecedores/f1/pedidos/p1"),
    ("delete", "/api/fornecedores/f1"),
])
def test_compras_bloqueado_fora_de_compras(client, metodo, url):
    with patch("db.query", return_value=[]), patch("db.execute"):
        resp = getattr(client, metodo)(url, headers=H, json={})
    assert resp.status_code == 403
    assert "compras" in resp.get_json()["error"]


def test_compras_lista_fornecedores(client):
    with patch("db.query", return_value=[{"id": "f1", "nome": "Flávia"}]):
        resp = client.get("/api/fornecedores", headers=H)
    assert resp.status_code == 200


def test_compras_lista_pedidos(client):
    with patch("db.query", return_value=[]):
        resp = client.get("/api/fornecedores/f1/pedidos", headers=H)
    assert resp.status_code == 200


def test_compras_passa_do_require_admin_ao_criar_pedido(client):
    # sem data_pedido o handler devolve 400: prova que passou das travas de papel
    resp = client.post("/api/fornecedores/f1/pedidos", headers=H, json={})
    assert resp.status_code == 400
