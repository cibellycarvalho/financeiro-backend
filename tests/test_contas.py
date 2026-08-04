from unittest.mock import patch

CONTA_FIXTURE = {
    "id": "11111111-0000-0000-0000-000000000001",
    "descricao": "DAS Agosto",
    "categoria": "IMPOSTO_DAS",
    "valor": 350.00,
    "vencimento": "2026-08-20",
    "marca": "GERAL",
    "status": "pendente",
    "data_pagamento": None,
    "observacao": None,
    "criado_por": "fd3a3d59-727f-40e2-bbea-c91187d2f0a7",
    "created_at": "2026-08-04T10:00:00+00:00"
}

def test_list_contas(client, admin_headers):
    with patch("routes.contas.db.query", return_value=[CONTA_FIXTURE]):
        resp = client.get("/api/contas", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["descricao"] == "DAS Agosto"

def test_list_contas_filter_semana(client, admin_headers):
    with patch("routes.contas.db.query", return_value=[]) as mock_q:
        resp = client.get("/api/contas?periodo=semana", headers=admin_headers)
    assert resp.status_code == 200
    call_args = mock_q.call_args[0][0]
    assert "vencimento" in call_args

def test_create_conta(client, admin_headers):
    payload = {
        "descricao": "DAS Agosto",
        "categoria": "IMPOSTO_DAS",
        "valor": 350.00,
        "vencimento": "2026-08-20",
        "marca": "GERAL"
    }
    with patch("routes.contas.db.execute", return_value=CONTA_FIXTURE):
        resp = client.post("/api/contas", json=payload, headers=admin_headers)
    assert resp.status_code == 201
    assert resp.get_json()["id"] == CONTA_FIXTURE["id"]

def test_create_conta_categoria_invalida(client, admin_headers):
    payload = {"descricao": "Teste", "categoria": "INVALIDA", "valor": 100, "vencimento": "2026-08-20", "marca": "GERAL"}
    resp = client.post("/api/contas", json=payload, headers=admin_headers)
    assert resp.status_code == 400

def test_marcar_como_pago(client, admin_headers):
    pago = {**CONTA_FIXTURE, "status": "pago", "data_pagamento": "2026-08-04"}
    with patch("routes.contas.db.execute", return_value=pago):
        resp = client.put(
            f"/api/contas/{CONTA_FIXTURE['id']}",
            json={"status": "pago", "data_pagamento": "2026-08-04"},
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "pago"

def test_delete_conta_viewer_negado(client, viewer_headers):
    resp = client.delete("/api/contas/qualquer-id", headers=viewer_headers)
    assert resp.status_code == 403
