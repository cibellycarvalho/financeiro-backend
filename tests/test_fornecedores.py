from unittest.mock import patch

FORNECEDOR_FIXTURE = {
    "id": "33333333-0000-0000-0000-000000000001",
    "nome": "Flávia", "apelido": "FL",
    "tipo_pagamento": "variavel", "ativo": True,
    "saldo_aberto": 5600.00
}
PEDIDO_FIXTURE = {
    "id": "44444444-0000-0000-0000-000000000001",
    "fornecedor_id": "33333333-0000-0000-0000-000000000001",
    "data_pedido": "2026-08-01",
    "descricao_produtos": "Cabo HDMI 8K 2M x500",
    "valor_total": 5600.00,
    "prazo_combinado": "2026-08-10",
    "status": "pendente",
    "valor_pago": 0,
    "data_pagamento": None,
    "observacao": None,
    "created_at": "2026-08-04T10:00:00+00:00"
}

def test_list_fornecedores(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[FORNECEDOR_FIXTURE]):
        resp = client.get("/api/fornecedores", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()[0]["apelido"] == "FL"

def test_list_pedidos(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[PEDIDO_FIXTURE]):
        resp = client.get(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos",
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()[0]["status"] == "pendente"

def test_create_pedido(client, admin_headers):
    payload = {
        "data_pedido": "2026-08-01",
        "valor_total": 5600.00,
        "prazo_combinado": "2026-08-10",
        "descricao_produtos": "Cabo HDMI 8K 2M x500"
    }
    with patch("routes.fornecedores.db.execute", return_value=PEDIDO_FIXTURE):
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos",
            json=payload, headers=admin_headers
        )
    assert resp.status_code == 201
    assert resp.get_json()["valor_total"] == 5600.00

def test_marcar_pedido_pago(client, admin_headers):
    pago = {**PEDIDO_FIXTURE, "status": "pago", "valor_pago": 5600.00, "data_pagamento": "2026-08-10"}
    with patch("routes.fornecedores.db.execute", return_value=pago):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}",
            json={"status": "pago", "valor_pago": 5600.00, "data_pagamento": "2026-08-10"},
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "pago"
