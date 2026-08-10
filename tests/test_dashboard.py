from unittest.mock import patch

def test_dashboard_retorna_estrutura(client, admin_headers):
    contas = [
        {"id": "1", "descricao": "DAS", "valor": 350.00, "vencimento": "2026-08-06",
         "status": "pendente", "categoria": "IMPOSTO_DAS", "marca": "GERAL"}
    ]
    saldo_data = [
        {"tipo": "repasse", "valor": 10000.00},
        {"tipo": "cobranca", "valor": 1500.00},
    ]
    contas_pagas = []
    contas_pendentes = []
    fornecedores = [{"nome": "Flávia", "saldo_aberto": 5000.00}]

    with patch("routes.dashboard.db.query", side_effect=[contas, saldo_data, contas_pagas, contas_pendentes, fornecedores]):
        resp = client.get("/api/dashboard", headers=admin_headers)

    assert resp.status_code == 200
    data = resp.get_json()
    assert "contas_semana" in data
    assert "totais" in data
    assert "alertas" in data
    assert data["totais"]["a_pagar_semana"] == 350.00
    assert data["totais"]["saldo_disponivel"] == 3500.00

def test_dashboard_sem_autenticacao(client):
    resp = client.get("/api/dashboard")
    assert resp.status_code == 401
