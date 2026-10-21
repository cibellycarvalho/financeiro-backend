from unittest.mock import patch

from tests.test_fornecedores import FORNECEDOR_FIXTURE, PEDIDO_FIXTURE, _mock_transaction_cursor

F, P = FORNECEDOR_FIXTURE["id"], PEDIDO_FIXTURE["id"]


def test_adicionar_item_guarda_o_sku_normalizado(client, admin_headers):
    item = {"id": "i3", "produto": "Cabo", "sku": "FV0073", "quantidade": 10, "valor_unitario": 5}
    mock_tr, cur = _mock_transaction_cursor([item, {**PEDIDO_FIXTURE, "valor_total": 50}])
    with patch("routes.fornecedores.db.query", return_value=[{"id": P}]), \
         patch("routes.fornecedores.db.transaction", mock_tr):
        r = client.post(f"/api/fornecedores/{F}/pedidos/{P}/itens", headers=admin_headers,
                        json={"produto": "Cabo", "quantidade": 10, "valor_unitario": 5, "sku": " fv0073 "})
    assert r.status_code == 201
    sql, params = cur.execute.call_args_list[0].args
    assert "sku" in sql and params == (P, "Cabo", 10.0, 5.0, "FV0073")


def test_item_sem_sku_continua_valendo(client, admin_headers):
    mock_tr, cur = _mock_transaction_cursor([{"id": "i3", "sku": None}, {**PEDIDO_FIXTURE}])
    with patch("routes.fornecedores.db.query", return_value=[{"id": P}]), \
         patch("routes.fornecedores.db.transaction", mock_tr):
        r = client.post(f"/api/fornecedores/{F}/pedidos/{P}/itens", headers=admin_headers,
                        json={"produto": "Cabo", "quantidade": 10, "valor_unitario": 5})
    assert r.status_code == 201
    assert cur.execute.call_args_list[0].args[1][-1] is None


def test_sku_invalido_400(client, admin_headers):
    for ruim in ("FV 0073", "FV0073;DROP", "X" * 41):
        r = client.post(f"/api/fornecedores/{F}/pedidos/{P}/itens", headers=admin_headers,
                        json={"produto": "Cabo", "quantidade": 10, "valor_unitario": 5, "sku": ruim})
        assert r.status_code == 400 and "sku" in r.get_json()["error"]


def test_criar_pedido_grava_o_sku_de_cada_item(client, admin_headers):
    pedido = {**PEDIDO_FIXTURE, "valor_total": 150}
    mock_tr, cur = _mock_transaction_cursor([pedido, {"id": "a", "sku": "FV0001"}, {"id": "b", "sku": None}])
    with patch("routes.fornecedores.db.transaction", mock_tr), \
         patch("routes.fornecedores._aprender_alias_silencioso"):
        r = client.post(f"/api/fornecedores/{F}/pedidos", headers=admin_headers, json={
            "data_pedido": "2026-10-20",
            "itens": [{"produto": "A", "quantidade": 1, "valor_unitario": 100, "sku": "fv0001"},
                      {"produto": "B", "quantidade": 1, "valor_unitario": 50}]})
    assert r.status_code == 201
    inserts = [c.args[1] for c in cur.execute.call_args_list if "fin_pedido_itens" in c.args[0]]
    assert [i[-1] for i in inserts] == ["FV0001", None]


def test_editar_item_so_mexe_no_sku_quando_a_tela_o_manda(client, admin_headers):
    mock_tr, cur = _mock_transaction_cursor([{"id": "i1", "sku": "FV0073"}, {**PEDIDO_FIXTURE}])
    with patch("routes.fornecedores.db.query", side_effect=[[{"id": P}], [{"id": "i1"}]]), \
         patch("routes.fornecedores.db.transaction", mock_tr):
        r = client.put(f"/api/fornecedores/{F}/pedidos/{P}/itens/i1", headers=admin_headers,
                       json={"produto": "Cabo", "quantidade": 10, "valor_unitario": 6})
    assert r.status_code == 200
    assert not any("SET sku" in c.args[0] for c in cur.execute.call_args_list)


def test_editar_item_com_sku_atualiza_e_devolve_o_sku(client, admin_headers):
    mock_tr, cur = _mock_transaction_cursor([{"id": "i1", "sku": None}, {"sku": "FV0073"}, {**PEDIDO_FIXTURE}])
    with patch("routes.fornecedores.db.query", side_effect=[[{"id": P}], [{"id": "i1"}]]), \
         patch("routes.fornecedores.db.transaction", mock_tr):
        r = client.put(f"/api/fornecedores/{F}/pedidos/{P}/itens/i1", headers=admin_headers,
                       json={"produto": "Cabo", "quantidade": 10, "valor_unitario": 6, "sku": "fv0073"})
    assert r.status_code == 200 and r.get_json()["item"]["sku"] == "FV0073"
    assert any("SET sku" in c.args[0] for c in cur.execute.call_args_list)
