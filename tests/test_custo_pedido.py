from unittest.mock import patch

import custo_pedido
from tests.test_fornecedores import FORNECEDOR_FIXTURE, PEDIDO_FIXTURE, _mock_transaction_cursor

F, P = FORNECEDOR_FIXTURE["id"], PEDIDO_FIXTURE["id"]


def test_custo_soma_os_2_porcento_da_nf():
    assert custo_pedido.custo_com_nf(105) == 107.10
    assert custo_pedido.custo_com_nf(6.5) == 6.63


def _sqls(cur):
    return [c.args for c in cur.execute.call_args_list]


def test_aplica_em_todos_os_anuncios_do_sku():
    anuncios = [{"ml_item_id": "MLB1", "conta_ml": "YUSO", "titulo": "A"},
                {"ml_item_id": "MLB2", "conta_ml": "YUSO", "titulo": "A republicado"}]
    # sem pedido mais novo; por anúncio: vigente, UPDATE historico sem linha
    mock_tr, cur = _mock_transaction_cursor([None, {"vigente": "2026-10-19"}, None, {"vigente": "2026-10-19"}, None])
    cur.fetchall.return_value = anuncios
    with patch("custo_pedido.db.transaction", mock_tr):
        r = custo_pedido.aplicar("i1", "FV0001", 105, "2026-10-19")
    assert r == {"sku": "FV0001", "status": "atualizado", "custo": 107.10, "anuncios": 2}
    upserts = [p for s, p in _sqls(cur) if "INSERT INTO custos_produtos" in s]
    assert [(u[1], u[3]) for u in upserts] == [("MLB1", 107.10), ("MLB2", 107.10)]
    assert all("custo_atualizado_em = now()" in s for s, _ in _sqls(cur) if "INSERT INTO custos_produtos" in s)
    assert sum("INSERT INTO custos_historico" in s for s, _ in _sqls(cur)) == 2


def test_mesma_data_altera_a_linha_do_historico_em_vez_de_duplicar():
    mock_tr, cur = _mock_transaction_cursor([None, {"vigente": "2026-10-19"}, {"id": 9}])
    cur.fetchall.return_value = [{"ml_item_id": "MLB1", "conta_ml": "YUSO", "titulo": "A"}]
    with patch("custo_pedido.db.transaction", mock_tr):
        custo_pedido.aplicar("i1", "FV0001", 10, "2026-10-19")
    assert not any("INSERT INTO custos_historico" in s for s, _ in _sqls(cur))


def test_pedido_mais_antigo_nao_volta_o_custo():
    mock_tr, cur = _mock_transaction_cursor([(1,)])
    with patch("custo_pedido.db.transaction", mock_tr):
        r = custo_pedido.aplicar("i1", "FV0001", 10, "2026-08-01")
    assert r["status"] == "pedido_mais_novo"
    assert not any("custos_produtos" in s for s, _ in _sqls(cur))


def test_sku_que_nao_existe_no_crm_e_contado():
    mock_tr, cur = _mock_transaction_cursor([None])
    cur.fetchall.return_value = []
    with patch("custo_pedido.db.transaction", mock_tr):
        assert custo_pedido.aplicar("i1", "XX9", 10, "2026-10-19")["status"] == "sku_desconhecido"


def test_criar_pedido_aprende_o_sku_e_atualiza_o_custo(client, admin_headers):
    mock_tr, _ = _mock_transaction_cursor([{**PEDIDO_FIXTURE}, {"id": "a", "produto": "FIBRA 20M", "sku": "FV0001", "valor_unitario": 105},
                                           {"id": "b", "produto": "Frete", "sku": None, "valor_unitario": 5}])
    with patch("routes.fornecedores.db.transaction", mock_tr), \
         patch("routes.fornecedores._aprender_alias_silencioso"), \
         patch("routes.fornecedores.custo_pedido.aprender_sku") as aprender, \
         patch("routes.fornecedores.custo_pedido.aplicar", return_value={"sku": "FV0001", "status": "atualizado"}) as aplicar:
        r = client.post(f"/api/fornecedores/{F}/pedidos", headers=admin_headers, json={
            "data_pedido": "2026-10-19",
            "itens": [{"produto": "FIBRA 20M", "quantidade": 1, "valor_unitario": 105, "sku": "FV0001"},
                      {"produto": "Frete", "quantidade": 1, "valor_unitario": 5}]})
    assert r.status_code == 201
    aprender.assert_called_once_with(F, "FIBRA 20M", "FV0001")
    aplicar.assert_called_once_with("a", "FV0001", 105, "2026-10-19")
    assert r.get_json()["custos"] == [{"sku": "FV0001", "status": "atualizado"}]


def test_falha_no_custo_nao_derruba_o_pedido(client, admin_headers):
    mock_tr, _ = _mock_transaction_cursor([{**PEDIDO_FIXTURE}, {"id": "a", "produto": "X", "sku": "FV0001", "valor_unitario": 1}])
    with patch("routes.fornecedores.db.transaction", mock_tr), \
         patch("routes.fornecedores._aprender_alias_silencioso"), \
         patch("routes.fornecedores.custo_pedido.aprender_sku", side_effect=RuntimeError("banco")):
        r = client.post(f"/api/fornecedores/{F}/pedidos", headers=admin_headers, json={
            "data_pedido": "2026-10-19",
            "itens": [{"produto": "X", "quantidade": 1, "valor_unitario": 1, "sku": "FV0001"}]})
    assert r.status_code == 201
    assert r.get_json()["custos"] == [{"sku": "FV0001", "status": "erro"}]


def test_lista_skus_do_crm(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[{"sku": "FV0001", "conta_ml": "YUSO", "titulo": "Cabo"}]):
        r = client.get("/api/fornecedores/skus", headers=admin_headers)
    assert r.status_code == 200 and r.get_json()[0]["sku"] == "FV0001"
