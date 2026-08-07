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


def test_editar_item_atualiza_valor_total(client, admin_headers):
    item_editado = {"id": "i1", "pedido_id": PEDIDO_FIXTURE["id"], "produto": "Cabo HDMI 8K 2M",
                     "quantidade": 300, "valor_unitario": 12.00, "valor_total": 3600.00}
    pedido_atualizado = {**PEDIDO_FIXTURE, "valor_total": 3600.00}
    mock_transaction, mock_cur = _mock_transaction_cursor([item_editado, pedido_atualizado])

    with patch("routes.fornecedores.db.query", side_effect=[
            [{"id": PEDIDO_FIXTURE["id"]}], [{"id": "i1"}]
        ]), \
         patch("routes.fornecedores.db.transaction", mock_transaction):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/itens/i1",
            json={"produto": "Cabo HDMI 8K 2M", "quantidade": 300, "valor_unitario": 12.00},
            headers=admin_headers
        )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["valor_total"] == 3600.00
    assert body["item"]["valor_total"] == 3600.00

    update_sql = mock_cur.execute.call_args_list[1].args[0]
    assert "UPDATE fin_pedidos_fornecedor" in update_sql
    assert "SUM(valor_total)" in update_sql


def test_editar_item_quantidade_invalida_retorna_erro(client, admin_headers):
    resp = client.put(
        f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/itens/i1",
        json={"produto": "Cabo", "quantidade": 0, "valor_unitario": 10.00},
        headers=admin_headers
    )
    assert resp.status_code == 400


def test_editar_item_pedido_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/naoexiste/itens/i1",
            json={"produto": "Cabo", "quantidade": 1, "valor_unitario": 10.00},
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_editar_item_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", side_effect=[[{"id": PEDIDO_FIXTURE["id"]}], []]):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/itens/naoexiste",
            json={"produto": "Cabo", "quantidade": 1, "valor_unitario": 10.00},
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_atualizar_pedido_valor_total_sem_itens(client, admin_headers):
    pedido_atualizado = {**PEDIDO_FIXTURE, "valor_total": 90000.00}
    with patch("routes.fornecedores.db.query", return_value=[]), \
         patch("routes.fornecedores.db.execute", return_value=pedido_atualizado):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}",
            json={"valor_total": 90000.00},
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()["valor_total"] == 90000.00


def test_atualizar_pedido_valor_total_com_itens_retorna_erro(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[{"id": "i1"}]):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}",
            json={"valor_total": 90000.00},
            headers=admin_headers
        )
    assert resp.status_code == 400
    assert "produtos" in resp.get_json()["error"].lower()


def test_atualizar_pedido_valor_total_invalido(client, admin_headers):
    resp = client.put(
        f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}",
        json={"valor_total": 0},
        headers=admin_headers
    )
    assert resp.status_code == 400


def test_atualizar_pedido_valor_total_pedido_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]), \
         patch("routes.fornecedores.db.execute", return_value=None):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/naoexiste",
            json={"valor_total": 100.00},
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_atualizar_pedido_data_pedido(client, admin_headers):
    pedido_atualizado = {**PEDIDO_FIXTURE, "data_pedido": "2026-08-02"}
    with patch("routes.fornecedores.db.execute", return_value=pedido_atualizado) as mock_execute:
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}",
            json={"data_pedido": "2026-08-02"},
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()["data_pedido"] == "2026-08-02"
    update_sql = mock_execute.call_args[0][0]
    assert "data_pedido = %s" in update_sql


def test_atualizar_pedido_data_pedido_vazia_retorna_erro(client, admin_headers):
    resp = client.put(
        f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}",
        json={"data_pedido": ""},
        headers=admin_headers
    )
    assert resp.status_code == 400


def test_atualizar_pedido_data_pedido_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.execute", return_value=None):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/naoexiste",
            json={"data_pedido": "2026-08-02"},
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_excluir_item_com_mais_de_um_produto(client, admin_headers):
    pedido_atualizado = {**PEDIDO_FIXTURE, "valor_total": 3500.00}
    mock_transaction, mock_cur = _mock_transaction_cursor([pedido_atualizado])

    with patch("routes.fornecedores.db.query", side_effect=[
            [{"id": PEDIDO_FIXTURE["id"]}], [{"id": "i1"}, {"id": "i2"}]
        ]), \
         patch("routes.fornecedores.db.transaction", mock_transaction):
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/itens/i1",
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()["valor_total"] == 3500.00

    delete_sql = mock_cur.execute.call_args_list[0].args[0]
    update_sql = mock_cur.execute.call_args_list[1].args[0]
    assert "DELETE FROM fin_pedido_itens" in delete_sql
    assert "SUM(valor_total)" in update_sql


def test_excluir_item_unico_retorna_erro(client, admin_headers):
    with patch("routes.fornecedores.db.query", side_effect=[
            [{"id": PEDIDO_FIXTURE["id"]}], [{"id": "i1"}]
        ]):
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/itens/i1",
            headers=admin_headers
        )
    assert resp.status_code == 400
    assert "único" in resp.get_json()["error"].lower()


def test_excluir_item_pedido_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/naoexiste/itens/i1",
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_excluir_item_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", side_effect=[
            [{"id": PEDIDO_FIXTURE["id"]}], [{"id": "i2"}, {"id": "i3"}]
        ]):
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/itens/naoexiste",
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_excluir_pedido(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[{"id": PEDIDO_FIXTURE["id"]}]), \
         patch("routes.fornecedores.db.execute") as mock_execute:
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}",
            headers=admin_headers
        )
    assert resp.status_code == 204
    delete_sql = mock_execute.call_args[0][0]
    assert "DELETE FROM fin_pedidos_fornecedor" in delete_sql


def test_excluir_pedido_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/naoexiste",
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_adicionar_item_a_pedido_existente(client, admin_headers):
    item_criado = {"id": "i3", "pedido_id": PEDIDO_FIXTURE["id"], "produto": "Cabo USB-C",
                   "quantidade": 500, "valor_unitario": 5.00, "valor_total": 2500.00}
    pedido_atualizado = {**PEDIDO_FIXTURE, "valor_total": 8100.00}
    mock_transaction, mock_cur = _mock_transaction_cursor([item_criado, pedido_atualizado])

    with patch("routes.fornecedores.db.query", return_value=[{"id": PEDIDO_FIXTURE["id"]}]), \
         patch("routes.fornecedores.db.transaction", mock_transaction):
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/itens",
            json={"produto": "Cabo USB-C", "quantidade": 500, "valor_unitario": 5.00},
            headers=admin_headers
        )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["valor_total"] == 8100.00
    assert body["item"]["produto"] == "Cabo USB-C"

    insert_sql = mock_cur.execute.call_args_list[0].args[0]
    update_sql = mock_cur.execute.call_args_list[1].args[0]
    assert "INSERT INTO fin_pedido_itens" in insert_sql
    assert "SUM(valor_total)" in update_sql


def test_adicionar_item_pedido_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/naoexiste/itens",
            json={"produto": "Cabo", "quantidade": 1, "valor_unitario": 10.00},
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_adicionar_item_quantidade_invalida_retorna_erro(client, admin_headers):
    resp = client.post(
        f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos/{PEDIDO_FIXTURE['id']}/itens",
        json={"produto": "Cabo", "quantidade": 0, "valor_unitario": 10.00},
        headers=admin_headers
    )
    assert resp.status_code == 400


def test_excluir_fornecedor_sem_saldo(client, admin_headers):
    fornecedor_ativo = [{"id": FORNECEDOR_FIXTURE["id"]}]
    saldo_zerado = [{"saldo_aberto": 0}]
    with patch("routes.fornecedores.db.query", side_effect=[fornecedor_ativo, saldo_zerado]), \
         patch("routes.fornecedores.db.execute",
               return_value={**FORNECEDOR_FIXTURE, "ativo": False}) as mock_execute:
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}", headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()["ativo"] is False
    update_sql = mock_execute.call_args[0][0]
    assert "ativo = false" in update_sql


def test_excluir_fornecedor_com_saldo_retorna_erro(client, admin_headers):
    fornecedor_ativo = [{"id": FORNECEDOR_FIXTURE["id"]}]
    saldo_em_aberto = [{"saldo_aberto": 5600.00}]
    with patch("routes.fornecedores.db.query", side_effect=[fornecedor_ativo, saldo_em_aberto]), \
         patch("routes.fornecedores.db.execute") as mock_execute:
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}", headers=admin_headers
        )
    assert resp.status_code == 400
    assert "saldo" in resp.get_json()["error"].lower()
    mock_execute.assert_not_called()


def test_excluir_fornecedor_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.delete(
            "/api/fornecedores/00000000-0000-0000-0000-000000000000", headers=admin_headers
        )
    assert resp.status_code == 404


def test_listar_pagamentos_fornecedor(client, admin_headers):
    pagamento = {"id": "pg1", "fornecedor_id": FORNECEDOR_FIXTURE["id"],
                 "valor": 1000.00, "data_pagamento": "2026-08-05"}
    with patch("routes.fornecedores.db.query", return_value=[pagamento]):
        resp = client.get(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos", headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()[0]["valor"] == 1000.00


def test_registrar_pagamento_fornecedor(client, admin_headers):
    fornecedor_ativo = [{"id": FORNECEDOR_FIXTURE["id"]}]
    saldo_row = [{"saldo_aberto": 5600.00}]
    pagamento_criado = {"id": "pg1", "fornecedor_id": FORNECEDOR_FIXTURE["id"],
                         "valor": 2000.00, "data_pagamento": "2026-08-05"}
    with patch("routes.fornecedores.db.query", side_effect=[fornecedor_ativo, saldo_row]), \
         patch("routes.fornecedores.db.execute", return_value=pagamento_criado) as mock_execute:
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos",
            json={"valor": 2000.00, "data_pagamento": "2026-08-05"},
            headers=admin_headers
        )
    assert resp.status_code == 201
    assert resp.get_json()["valor"] == 2000.00
    insert_sql = mock_execute.call_args[0][0]
    assert "INSERT INTO fin_pagamentos_fornecedor" in insert_sql


def test_registrar_pagamento_fornecedor_maior_que_saldo_retorna_erro(client, admin_headers):
    fornecedor_ativo = [{"id": FORNECEDOR_FIXTURE["id"]}]
    saldo_row = [{"saldo_aberto": 100.00}]
    with patch("routes.fornecedores.db.query", side_effect=[fornecedor_ativo, saldo_row]):
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos",
            json={"valor": 200.00, "data_pagamento": "2026-08-05"},
            headers=admin_headers
        )
    assert resp.status_code == 400


def test_registrar_pagamento_fornecedor_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.post(
            "/api/fornecedores/00000000-0000-0000-0000-000000000000/pagamentos",
            json={"valor": 100.00, "data_pagamento": "2026-08-05"},
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_editar_pagamento_fornecedor(client, admin_headers):
    pagamento_atual = [{"valor": 2000.00}]
    saldo_row = [{"saldo_aberto": 3600.00}]
    pagamento_editado = {"id": "pg1", "fornecedor_id": FORNECEDOR_FIXTURE["id"],
                          "valor": 2500.00, "data_pagamento": "2026-08-06"}
    with patch("routes.fornecedores.db.query", side_effect=[pagamento_atual, saldo_row]), \
         patch("routes.fornecedores.db.execute", return_value=pagamento_editado):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos/pg1",
            json={"valor": 2500.00, "data_pagamento": "2026-08-06"},
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()["valor"] == 2500.00


def test_editar_pagamento_fornecedor_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos/naoexiste",
            json={"valor": 100.00, "data_pagamento": "2026-08-05"},
            headers=admin_headers
        )
    assert resp.status_code == 404


def test_excluir_pagamento_fornecedor(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[{"id": "pg1"}]), \
         patch("routes.fornecedores.db.execute") as mock_execute:
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos/pg1",
            headers=admin_headers
        )
    assert resp.status_code == 204
    delete_sql = mock_execute.call_args[0][0]
    assert "DELETE FROM fin_pagamentos_fornecedor" in delete_sql


def test_excluir_pagamento_fornecedor_inexistente_retorna_404(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[]):
        resp = client.delete(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos/naoexiste",
            headers=admin_headers
        )
    assert resp.status_code == 404
