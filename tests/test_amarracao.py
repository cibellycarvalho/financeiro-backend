from unittest.mock import patch, MagicMock

import amarracao


def test_soma_amarrada_nao_passa_do_pagamento():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 100.0},                       # valor do pagamento
        {"valor_total": 60.0, "amarrado": 0.0},  # pedido A
        {"valor_total": 60.0, "amarrado": 0.0},  # pedido B
    ]
    erro = amarracao.validar(cur, "pg-1", [
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
    erro = amarracao.validar(cur, "pg-1", [{"pedido_id": "a", "valor": 40.0}])
    assert erro is not None
    assert "compra" in erro


def test_amarracao_parcial_e_valida():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 100.0},
        {"valor_total": 500.0, "amarrado": 0.0},
    ]
    assert amarracao.validar(cur, "pg-1", [{"pedido_id": "a", "valor": 100.0}]) is None


def test_valor_zero_ou_negativo_e_recusado():
    cur = MagicMock()
    cur.fetchone.side_effect = [{"valor": 100.0}]
    assert amarracao.validar(cur, "pg-1", [{"pedido_id": "a", "valor": 0}]) is not None


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
