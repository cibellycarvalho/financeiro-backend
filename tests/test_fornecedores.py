from unittest.mock import patch, MagicMock

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
    "descricao_produtos": None,
    "valor_total": 5600.00,
    "status": "pendente",
    "valor_pago": 0,
    "data_pagamento": None,
    "observacao": None,
    "created_at": "2026-08-04T10:00:00+00:00"
}


def _mock_transaction_cursor(fetchone_results):
    """Monta um mock de db.transaction() cujo cursor.fetchone() retorna,
    em sequência, os valores passados em fetchone_results."""
    mock_cur = MagicMock()
    mock_cur.fetchone.side_effect = fetchone_results
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_cur
    mock_ctx.__exit__.return_value = False
    mock_transaction = MagicMock(return_value=mock_ctx)
    return mock_transaction, mock_cur


def test_list_fornecedores(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[FORNECEDOR_FIXTURE]):
        resp = client.get("/api/fornecedores", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()[0]["apelido"] == "FL"


def test_list_pedidos_com_itens(client, admin_headers):
    pedido_com_itens = {
        **PEDIDO_FIXTURE,
        "itens": [
            {"id": "i1", "produto": "Cabo HDMI 8K 2M", "quantidade": 250,
             "valor_unitario": 10.00, "valor_total": 2500.00}
        ]
    }
    with patch("routes.fornecedores.db.query", return_value=[pedido_com_itens]):
        resp = client.get(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos",
            headers=admin_headers
        )
    assert resp.status_code == 200
    body = resp.get_json()[0]
    assert body["status"] == "pendente"
    assert body["itens"][0]["produto"] == "Cabo HDMI 8K 2M"


def test_create_pedido_com_itens(client, admin_headers):
    payload = {
        "data_pedido": "2026-08-01",
        "itens": [
            {"produto": "Cabo HDMI 8K 2M", "quantidade": 250, "valor_unitario": 10.00},
            {"produto": "Cabo HDMI 8K 5M", "quantidade": 900, "valor_unitario": 18.00},
        ]
    }
    pedido_row = {**PEDIDO_FIXTURE, "valor_total": 18700.00}
    item1_row = {"id": "i1", "pedido_id": pedido_row["id"], "produto": "Cabo HDMI 8K 2M",
                 "quantidade": 250, "valor_unitario": 10.00, "valor_total": 2500.00}
    item2_row = {"id": "i2", "pedido_id": pedido_row["id"], "produto": "Cabo HDMI 8K 5M",
                 "quantidade": 900, "valor_unitario": 18.00, "valor_total": 16200.00}
    mock_transaction, mock_cur = _mock_transaction_cursor([pedido_row, item1_row, item2_row])

    with patch("routes.fornecedores.db.transaction", mock_transaction):
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos",
            json=payload, headers=admin_headers
        )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["valor_total"] == 18700.00
    assert len(body["itens"]) == 2
    assert body["itens"][0]["produto"] == "Cabo HDMI 8K 2M"
    assert body["itens"][1]["valor_total"] == 16200.00

    # valor_total inserido no pedido deve ser a soma calculada no servidor
    first_insert_params = mock_cur.execute.call_args_list[0].args[1]
    assert 18700.00 in first_insert_params


def test_create_pedido_sem_itens_retorna_erro(client, admin_headers):
    resp = client.post(
        f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos",
        json={"data_pedido": "2026-08-01"},
        headers=admin_headers
    )
    assert resp.status_code == 400
    assert "itens" in resp.get_json()["error"]


def test_create_pedido_item_quantidade_invalida(client, admin_headers):
    resp = client.post(
        f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos",
        json={
            "data_pedido": "2026-08-01",
            "itens": [{"produto": "Cabo", "quantidade": 0, "valor_unitario": 10.00}]
        },
        headers=admin_headers
    )
    assert resp.status_code == 400


def test_registrar_pagamento_parcial(client, admin_headers):
    pedido_atualizado = {**PEDIDO_FIXTURE, "valor_pago": 2000.00, "status": "parcial",
                          "data_pagamento": "2026-08-05"}
    with patch("routes.fornecedores.db.query", return_value=[PEDIDO_FIXTURE]), \
         patch("routes.fornecedores.db.execute", return_value=pedido_atualizado):
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/pagamentos",
            json={"valor": 2000.00, "data_pagamento": "2026-08-05"},
            headers=admin_headers
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "parcial"
    assert body["valor_pago"] == 2000.00


def test_registrar_pagamento_completa_pedido(client, admin_headers):
    pedido_pago = {**PEDIDO_FIXTURE, "valor_pago": 5600.00, "status": "pago",
                   "data_pagamento": "2026-08-10"}
    with patch("routes.fornecedores.db.query", return_value=[PEDIDO_FIXTURE]), \
         patch("routes.fornecedores.db.execute", return_value=pedido_pago):
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/pagamentos",
            json={"valor": 5600.00, "data_pagamento": "2026-08-10"},
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "pago"


def test_registrar_pagamento_acumula_com_pagamento_anterior(client, admin_headers):
    pedido_parcial = {**PEDIDO_FIXTURE, "valor_pago": 2000.00, "status": "parcial"}
    pedido_completo = {**PEDIDO_FIXTURE, "valor_pago": 5600.00, "status": "pago",
                       "data_pagamento": "2026-08-10"}
    with patch("routes.fornecedores.db.query", return_value=[pedido_parcial]), \
         patch("routes.fornecedores.db.execute", return_value=pedido_completo) as mock_execute:
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/pagamentos",
            json={"valor": 3600.00, "data_pagamento": "2026-08-10"},
            headers=admin_headers
        )
    assert resp.status_code == 200
    # 2000 (já pago) + 3600 (novo) = 5600 -> deve mandar 5600.0 pro UPDATE
    update_params = mock_execute.call_args.args[1]
    assert 5600.0 in update_params


def test_registrar_pagamento_maior_que_saldo_retorna_erro(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[PEDIDO_FIXTURE]):
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/pagamentos",
            json={"valor": 99999.00, "data_pagamento": "2026-08-10"},
            headers=admin_headers
        )
    assert resp.status_code == 400


def test_registrar_pagamento_pedido_inexistente(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/00000000-0000-0000-0000-000000000000/pagamentos",
            json={"valor": 100.00, "data_pagamento": "2026-08-10"},
            headers=admin_headers
        )
    assert resp.status_code == 404
