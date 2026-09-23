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


def test_list_pedidos_traz_valor_amarrado(client, admin_headers):
    """Fix round 1 (item 8): a tela de 'Pix sem compra' propõe amarrar o
    valor_total inteiro de novo mesmo quando parte do pedido já está amarrada
    a outro Pix. Precisa do saldo já amarrado para propor só o que falta."""
    pedido_com_amarracao = {**PEDIDO_FIXTURE, "amarrado": 2000.00}
    with patch("routes.fornecedores.db.query", return_value=[pedido_com_amarracao]):
        resp = client.get(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pedidos",
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()[0]["amarrado"] == 2000.00


def test_list_pagamentos_traz_amarracoes(client, admin_headers):
    """Fix round 1 (item 2, CRITICAL): depois de amarrar, o Pix precisa
    continuar mostrando a que compras ficou amarrado — sem isso a única saída
    pra corrigir um erro era apagar o pagamento inteiro e relançar."""
    pagamento_amarrado = {
        "id": "pg-1", "fornecedor_id": FORNECEDOR_FIXTURE["id"], "valor": 49310.00,
        "data_pagamento": "2026-09-14", "arquivo_path": None,
        "amarracoes": [
            {"pedido_id": PEDIDO_FIXTURE["id"], "numero_pedido": "10",
             "data_pedido": "2026-08-10", "valor": 30000.00},
        ],
    }
    with patch("routes.fornecedores.db.query", return_value=[pagamento_amarrado]):
        resp = client.get(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos",
            headers=admin_headers
        )
    assert resp.status_code == 200
    body = resp.get_json()[0]
    assert body["amarracoes"][0]["numero_pedido"] == "10"
    assert body["amarracoes"][0]["valor"] == 30000.00


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


def test_registrar_pagamento_liga_no_maximo_o_valor_da_compra(client, admin_headers):
    """Ruling do fix round 1: o link em fin_pagamento_pedido vale no máximo o
    que cabe na compra, não o valor cheio do Pix quando o Pix é maior."""
    fornecedor_ativo = [{"id": FORNECEDOR_FIXTURE["id"]}]
    saldo_row = [{"saldo_aberto": 5600.00}]
    pedido_amarrado = [{"id": PEDIDO_FIXTURE["id"], "valor_total": 500.00, "pago_em": None}]
    pagamento_criado = {"id": "pg1", "fornecedor_id": FORNECEDOR_FIXTURE["id"],
                         "valor": 800.00, "data_pagamento": "2026-08-05"}
    with patch("routes.fornecedores.db.query", side_effect=[fornecedor_ativo, saldo_row, pedido_amarrado]), \
         patch("routes.fornecedores.db.execute", return_value=pagamento_criado) as mock_execute:
        resp = client.post(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos",
            json={"valor": 800.00, "data_pagamento": "2026-08-05", "pedido_id": PEDIDO_FIXTURE["id"]},
            headers=admin_headers
        )
    assert resp.status_code == 201
    insert_calls = [c for c in mock_execute.call_args_list if "INSERT INTO fin_pagamento_pedido" in c[0][0]]
    assert len(insert_calls) == 1
    params = insert_calls[0][0][1]
    assert params[2] == 500.00


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
    amarrado_row = [{"amarrado": 0.0}]
    saldo_row = [{"saldo_aberto": 3600.00}]
    pagamento_editado = {"id": "pg1", "fornecedor_id": FORNECEDOR_FIXTURE["id"],
                          "valor": 2500.00, "data_pagamento": "2026-08-06"}
    with patch("routes.fornecedores.db.query", side_effect=[pagamento_atual, amarrado_row, saldo_row]), \
         patch("routes.fornecedores.db.execute", return_value=pagamento_editado):
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos/pg1",
            json={"valor": 2500.00, "data_pagamento": "2026-08-06"},
            headers=admin_headers
        )
    assert resp.status_code == 200
    assert resp.get_json()["valor"] == 2500.00


def test_editar_pagamento_baixando_abaixo_do_amarrado_e_recusado(client, admin_headers):
    """Ruling do fix round 1: baixar o valor de um pagamento já amarrado a
    compras não pode deixar a soma amarrada maior que o próprio pagamento."""
    pagamento_atual = [{"valor": 2000.00}]
    amarrado_row = [{"amarrado": 1500.00}]
    with patch("routes.fornecedores.db.query", side_effect=[pagamento_atual, amarrado_row]), \
         patch("routes.fornecedores.db.execute") as mock_execute:
        resp = client.put(
            f"/api/fornecedores/{FORNECEDOR_FIXTURE['id']}/pagamentos/pg1",
            json={"valor": 1000.00, "data_pagamento": "2026-08-06"},
            headers=admin_headers
        )
    assert resp.status_code == 400
    assert "amarrado" in resp.get_json()["error"]
    mock_execute.assert_not_called()


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


def test_pagamentos_do_periodo_traz_todos_os_fornecedores(client, admin_headers):
    linha = {"id": "pg1", "fornecedor_id": "f1", "fornecedor_nome": "Flavia", "fornecedor_apelido": "FL",
             "valor": 1000.00, "data_pagamento": "2026-09-15", "created_at": "2026-09-15T10:00:00"}
    with patch("routes.fornecedores.db.query", return_value=[linha]) as mock_query:
        resp = client.get("/api/fornecedores/pagamentos?de=2026-09-14&ate=2026-09-20", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()[0]["fornecedor_apelido"] == "FL"
    sql, params = mock_query.call_args[0]
    assert "JOIN fin_fornecedores" in sql
    assert params == ("2026-09-14", "2026-09-20")


def test_pagamentos_do_periodo_exige_datas_validas(client, admin_headers):
    resp = client.get("/api/fornecedores/pagamentos?de=ontem&ate=2026-09-20", headers=admin_headers)
    assert resp.status_code == 400


F_ID = FORNECEDOR_FIXTURE["id"]
P_ID = PEDIDO_FIXTURE["id"]
URL_PAGO = f"/api/fornecedores/{F_ID}/pedidos/{P_ID}/pago"


def test_caixinha_lancar_cria_pagamento_amarrado_e_marca_pedido(client, admin_headers):
    pedido = [{"id": P_ID, "valor_total": 35310.00, "pago_em": None}]
    saldo = [{"saldo_aberto": 273320.00}]
    mock_transaction, mock_cur = _mock_transaction_cursor([
        {"id": "pg1", "valor": 35310.00, "pedido_id": P_ID},   # INSERT do pagamento
        {"valor": 35310.00},                                   # amarracao.validar: valor do pagamento
        {"valor_total": 35310.00, "amarrado": 0.0},            # amarracao.validar: pedido sem amarração prévia
        {"id": P_ID, "pago_em": "2026-09-17"},                 # UPDATE pago_em
    ])
    with patch("routes.fornecedores.db.query", side_effect=[pedido, saldo]), \
         patch("routes.fornecedores.db.transaction", mock_transaction):
        resp = client.post(URL_PAGO, json={"modo": "lancar", "data_pagamento": "2026-09-17"}, headers=admin_headers)
    assert resp.status_code == 201
    assert resp.get_json()["pagamento"]["pedido_id"] == P_ID
    insert_sql, params = mock_cur.execute.call_args_list[0][0]
    assert "INSERT INTO fin_pagamentos_fornecedor" in insert_sql
    assert params[1] == 35310.00 and params[3] == P_ID


def test_caixinha_lancar_recusa_quando_adiantamento_ja_ocupou_a_compra(client, admin_headers):
    """Ruling do fix round 1: clicar 'Pago' (modo lancar) não pode gravar o
    link se a compra já tem amarração de um adiantamento e não sobra espaço
    pro valor cheio do novo pagamento — antes isso estourava a soma amarrada."""
    pedido = [{"id": P_ID, "valor_total": 30000.00, "pago_em": None}]
    saldo = [{"saldo_aberto": 273320.00}]
    mock_transaction, mock_cur = _mock_transaction_cursor([
        {"id": "pg-novo", "valor": 30000.00, "pedido_id": P_ID},   # INSERT do pagamento novo
        {"valor": 30000.00},                                        # amarracao.validar: valor do pagamento novo
        {"valor_total": 30000.00, "amarrado": 10000.00},            # já tem 10.000 de adiantamento amarrado
    ])
    with patch("routes.fornecedores.db.query", side_effect=[pedido, saldo]), \
         patch("routes.fornecedores.db.transaction", mock_transaction):
        resp = client.post(URL_PAGO, json={"modo": "lancar", "data_pagamento": "2026-09-17"}, headers=admin_headers)
    assert resp.status_code == 400
    assert "compra" in resp.get_json()["error"]
    sqls = [c[0][0] for c in mock_cur.execute.call_args_list]
    assert not any("INSERT INTO fin_pagamento_pedido" in s for s in sqls)
    assert not any("pago_em" in s for s in sqls)


def test_caixinha_ja_lancado_recusa_quando_pix_nao_cobre(client, admin_headers):
    pedido = [{"id": P_ID, "valor_total": 40400.00, "pago_em": None}]
    livre = [{"livre": 400.00}]
    with patch("routes.fornecedores.db.query", side_effect=[pedido, livre]), \
         patch("routes.fornecedores.db.execute") as mock_execute:
        resp = client.post(URL_PAGO, json={"modo": "ja_lancado", "data_pagamento": "2026-08-19"}, headers=admin_headers)
    assert resp.status_code == 400
    mock_execute.assert_not_called()


def test_caixinha_ja_lancado_so_marca(client, admin_headers):
    pedido = [{"id": P_ID, "valor_total": 400.00, "pago_em": None}]
    livre = [{"livre": 91910.00}]
    with patch("routes.fornecedores.db.query", side_effect=[pedido, livre]), \
         patch("routes.fornecedores.db.execute", return_value={"id": P_ID, "pago_em": "2026-08-26"}) as mock_execute:
        resp = client.post(URL_PAGO, json={"modo": "ja_lancado", "data_pagamento": "2026-08-26"}, headers=admin_headers)
    assert resp.status_code == 201
    assert "UPDATE fin_pedidos_fornecedor SET pago_em" in mock_execute.call_args[0][0]


def test_caixinha_pedido_ja_pago_retorna_409(client, admin_headers):
    pedido = [{"id": P_ID, "valor_total": 400.00, "pago_em": "2026-08-26"}]
    with patch("routes.fornecedores.db.query", side_effect=[pedido]):
        resp = client.post(URL_PAGO, json={"modo": "lancar", "data_pagamento": "2026-09-17"}, headers=admin_headers)
    assert resp.status_code == 409


def test_desmarcar_caixinha_apaga_pagamento_amarrado(client, admin_headers):
    mock_transaction, mock_cur = _mock_transaction_cursor([])
    with patch("routes.fornecedores.db.query", return_value=[{"id": P_ID, "valor_total": 1, "pago_em": "2026-09-17"}]), \
         patch("routes.fornecedores.db.transaction", mock_transaction):
        resp = client.delete(URL_PAGO, headers=admin_headers)
    assert resp.status_code == 204
    sqls = [c[0][0] for c in mock_cur.execute.call_args_list]
    assert "DELETE FROM fin_pagamentos_fornecedor WHERE pedido_id" in sqls[0]
    assert "pago_em = NULL" in sqls[1]


def test_desmarcar_ja_lancado_nao_apaga_amarracao_de_pagamento_que_continua(client, admin_headers):
    """RULING (fix round 1, CRITICAL): Pix de 49.310 amarrado às compras de
    10/08 e 11/08 via fin_pagamento_pedido. A de 10/08 foi marcada no modo
    'ja_lancado' (não criou pagamento novo — só marcou pago_em). Desmarcar a
    caixinha da 10/08 não pode apagar a ligação Pix->10/08: esse Pix continua
    existindo e ainda tem a alocação de 30.000 pra ele. O DELETE FROM
    fin_pagamentos_fornecedor (coluna legada pedido_id) não acha nada pra
    apagar aqui, e não deve haver nenhum DELETE direto em
    fin_pagamento_pedido — o ON DELETE CASCADE só entra em ação quando o
    pagamento em si é apagado."""
    mock_transaction, mock_cur = _mock_transaction_cursor([])
    with patch("routes.fornecedores.db.query",
               return_value=[{"id": P_ID, "valor_total": 30000.00, "pago_em": "2026-08-10"}]), \
         patch("routes.fornecedores.db.transaction", mock_transaction):
        resp = client.delete(URL_PAGO, headers=admin_headers)
    assert resp.status_code == 204
    sqls = [c[0][0] for c in mock_cur.execute.call_args_list]
    assert len(sqls) == 2
    assert not any("fin_pagamento_pedido" in s for s in sqls)


def test_caixinha_viewer_nao_pode_marcar_viewer(client, viewer_headers):
    resp = client.post(URL_PAGO, json={"modo": "lancar", "data_pagamento": "2026-09-17"}, headers=viewer_headers)
    assert resp.status_code == 403
