from unittest.mock import patch, MagicMock

import amarracao

FORN_ID = "forn-1"


def test_soma_amarrada_nao_passa_do_pagamento():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 100.0},                       # valor do pagamento
        {"valor_total": 60.0, "amarrado": 0.0},  # pedido A
        {"valor_total": 60.0, "amarrado": 0.0},  # pedido B
    ]
    erro = amarracao.validar(cur, "pg-1", FORN_ID, [
        {"pedido_id": "a", "valor": 60.0},
        {"pedido_id": "b", "valor": 60.0},
    ])
    assert erro is not None
    assert "pagamento" in erro


def test_soma_amarrada_nao_passa_do_valor_da_compra():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 100.0},
        {"valor_total": 50.0, "amarrado": 20.0},   # já tem 20 amarrados
    ]
    erro = amarracao.validar(cur, "pg-1", FORN_ID, [{"pedido_id": "a", "valor": 40.0}])
    assert erro is not None
    assert "compra" in erro


def test_amarracao_parcial_e_valida():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 100.0},
        {"valor_total": 500.0, "amarrado": 0.0},
    ]
    assert amarracao.validar(cur, "pg-1", FORN_ID, [{"pedido_id": "a", "valor": 100.0}]) is None


def test_valor_zero_ou_negativo_e_recusado():
    cur = MagicMock()
    cur.fetchone.side_effect = [{"valor": 100.0}]
    assert amarracao.validar(cur, "pg-1", FORN_ID, [{"pedido_id": "a", "valor": 0}]) is not None


# --- Fix round 1: qualidade ---------------------------------------------

def test_compra_repetida_na_lista_e_recusada_sem_tocar_o_banco():
    cur = MagicMock()
    erro = amarracao.validar(cur, "pg-1", FORN_ID, [
        {"pedido_id": "a", "valor": 30.0},
        {"pedido_id": "a", "valor": 20.0},
    ])
    assert erro is not None
    assert "repetida" in erro
    # nem chegou a consultar o banco: a checagem de repetição é só em Python
    cur.execute.assert_not_called()


def test_pedido_de_outro_fornecedor_nao_e_amarrado():
    """SELECT já filtra por fornecedor_id — o pedido de outro fornecedor não
    aparece, então cur.fetchone() devolve None como se a compra não existisse."""
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 100.0},
        None,   # pedido existe, mas é de outro fornecedor -> filtro não acha
    ]
    erro = amarracao.validar(cur, "pg-1", FORN_ID, [{"pedido_id": "a", "valor": 40.0}])
    assert erro is not None
    assert "não encontrada" in erro
    sql, params = cur.execute.call_args_list[-1][0]
    assert "p.fornecedor_id = %s" in sql
    assert params[-1] == FORN_ID


def test_pedido_id_ausente_no_item_da_erro_em_portugues_sem_500():
    cur = MagicMock()
    erro = amarracao.validar(cur, "pg-1", FORN_ID, [{"valor": 40.0}])
    assert erro is not None
    assert "pedido_id" in erro


def test_pedido_id_invalido_no_banco_vira_erro_de_validacao_nao_500():
    """Um pedido_id que não é UUID faz o driver real levantar um erro de
    banco (ex.: DataError) ao rodar o SELECT — validar() converte isso em
    mensagem, não deixa a exceção subir."""
    cur = MagicMock()
    cur.fetchone.side_effect = [{"valor": 100.0}]
    cur.execute.side_effect = [None, Exception("invalid input syntax for type uuid")]
    erro = amarracao.validar(cur, "pg-1", FORN_ID, [{"pedido_id": "nao-e-uuid", "valor": 40.0}])
    assert erro is not None
    assert "não encontrada" in erro


def test_valor_nan_e_recusado():
    cur = MagicMock()
    erro = amarracao.validar(cur, "pg-1", FORN_ID, [{"pedido_id": "a", "valor": float("nan")}])
    assert erro is not None


def test_valor_infinito_e_recusado():
    cur = MagicMock()
    erro = amarracao.validar(cur, "pg-1", FORN_ID, [{"pedido_id": "a", "valor": float("inf")}])
    assert erro is not None


# --- rotas ----------------------------------------------------------------

def test_lista_pagamentos_soltos(client, admin_headers):
    soltos = [{"id": "pg-1", "valor": 2970.0, "data_pagamento": "2026-09-23", "arquivo_path": None}]
    with patch("db.query", return_value=soltos):
        resp = client.get("/api/fornecedores/forn-1/pagamentos/soltos", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()[0]["id"] == "pg-1"


def test_amarrar_grava_uma_linha_por_compra(client, admin_headers):
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 49310.0},
        {"valor_total": 30000.0, "amarrado": 0.0},
        {"valor_total": 19310.0, "amarrado": 0.0},
    ]
    transacao = MagicMock()
    transacao.__enter__.return_value = cur
    with patch("db.query", return_value=[{"id": "pg-1"}]), patch("db.transaction", return_value=transacao):
        resp = client.post(
            "/api/fornecedores/forn-1/pagamentos/pg-1/pedidos",
            json={"itens": [{"pedido_id": "a", "valor": 30000.0},
                            {"pedido_id": "b", "valor": 19310.0}]},
            headers=admin_headers,
        )
    assert resp.status_code == 200
    inserts = [c for c in cur.execute.call_args_list if "INSERT INTO fin_pagamento_pedido" in c[0][0]]
    assert len(inserts) == 2


def test_amarrar_compra_do_outro_fornecedor_e_recusado(client, admin_headers):
    """O pedido_id é de verdade (existe no banco), só que é de outro
    fornecedor — a amarração não pode passar a abater a dívida alheia."""
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 49310.0},
        None,   # SELECT ... AND p.fornecedor_id = %s não acha (é de outro fornecedor)
    ]
    transacao = MagicMock()
    transacao.__enter__.return_value = cur
    with patch("db.query", return_value=[{"id": "pg-1"}]), patch("db.transaction", return_value=transacao):
        resp = client.post(
            "/api/fornecedores/forn-1/pagamentos/pg-1/pedidos",
            json={"itens": [{"pedido_id": "pedido-de-outro-fornecedor", "valor": 30000.0}]},
            headers=admin_headers,
        )
    assert resp.status_code == 400
    assert "não encontrada" in resp.get_json()["error"]
    inserts = [c for c in cur.execute.call_args_list if "INSERT INTO fin_pagamento_pedido" in c[0][0]]
    assert len(inserts) == 0


def test_amarrar_compra_repetida_na_lista_e_recusado(client, admin_headers):
    cur = MagicMock()
    cur.fetchone.side_effect = [{"valor": 60000.0}]
    transacao = MagicMock()
    transacao.__enter__.return_value = cur
    with patch("db.query", return_value=[{"id": "pg-1"}]), patch("db.transaction", return_value=transacao):
        resp = client.post(
            "/api/fornecedores/forn-1/pagamentos/pg-1/pedidos",
            json={"itens": [{"pedido_id": "a", "valor": 30000.0},
                            {"pedido_id": "a", "valor": 30000.0}]},
            headers=admin_headers,
        )
    assert resp.status_code == 400
    assert "repetida" in resp.get_json()["error"]
