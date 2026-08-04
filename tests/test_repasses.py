from unittest.mock import patch

REPASSE_FIXTURE = {
    "id": "22222222-0000-0000-0000-000000000001",
    "tipo": "repasse",
    "valor": 12340.00,
    "data_referencia": "2026-08-01",
    "descricao": "Repasse YUSO semana 31",
    "conta_ml": "YUSO",
    "confirmado": True,
    "created_at": "2026-08-04T10:00:00+00:00"
}

def test_list_repasses(client, admin_headers):
    with patch("routes.repasses.db.query", return_value=[REPASSE_FIXTURE]):
        resp = client.get("/api/repasses", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()[0]["tipo"] == "repasse"

def test_create_repasse(client, admin_headers):
    payload = {"tipo": "repasse", "valor": 12340.00, "data_referencia": "2026-08-01", "conta_ml": "YUSO"}
    with patch("routes.repasses.db.execute", return_value=REPASSE_FIXTURE):
        resp = client.post("/api/repasses", json=payload, headers=admin_headers)
    assert resp.status_code == 201

def test_create_repasse_tipo_invalido(client, admin_headers):
    payload = {"tipo": "transferencia", "valor": 100, "data_referencia": "2026-08-01", "conta_ml": "YUSO"}
    resp = client.post("/api/repasses", json=payload, headers=admin_headers)
    assert resp.status_code == 400

def test_saldo(client, admin_headers):
    movimentos = [
        {"tipo": "repasse", "valor": 15000.00},
        {"tipo": "cobranca", "valor": 2500.00},
        {"tipo": "tarifa", "valor": 200.00},
    ]
    contas = [{"valor": 1000.00}, {"valor": 500.00}]
    with patch("routes.repasses.db.query", side_effect=[movimentos, contas]):
        resp = client.get("/api/repasses/saldo", headers=admin_headers)
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["repasses_bruto"] == 15000.00
    assert data["cobranças_ml"] == 2700.00
    assert data["contas_pagas"] == 1500.00
    assert data["saldo_disponivel"] == 10800.00
