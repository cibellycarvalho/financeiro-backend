from unittest.mock import patch

FORN = "33333333-0000-0000-0000-000000000001"
PED = "44444444-0000-0000-0000-000000000001"
URL = f"/api/fornecedores/{FORN}/pedidos/{PED}/desconto"


def _pedido(valor=7050.0):
    return {"id": PED, "valor_total": valor, "desconto": 0, "pago_em": None}


def test_desconto_automatico_e_a_diferenca_entre_pedido_e_pago(client, admin_headers):
    # pedido 7.050, Pix amarrado 6.556,50 -> desconto 493,50 (caso ALTOMEX, 20/10/2026)
    with patch("routes.fornecedores._pedido_do_fornecedor", return_value=_pedido()), \
         patch("routes.fornecedores.db.query", return_value=[{"v": 6556.50}]), \
         patch("routes.fornecedores.db.execute", return_value={"id": PED, "desconto": 493.5}) as ex:
        r = client.post(URL, headers=admin_headers, json={})
    assert r.status_code == 200
    assert ex.call_args[0][1] == (493.5, PED)


def test_desconto_com_valor_informado(client, admin_headers):
    with patch("routes.fornecedores._pedido_do_fornecedor", return_value=_pedido()), \
         patch("routes.fornecedores.db.query", return_value=[{"v": 6000.0}]), \
         patch("routes.fornecedores.db.execute", return_value={"id": PED}) as ex:
        r = client.post(URL, headers=admin_headers, json={"valor": 100})
    assert r.status_code == 200 and ex.call_args[0][1] == (100.0, PED)


def test_desconto_maior_que_o_que_falta_400(client, admin_headers):
    with patch("routes.fornecedores._pedido_do_fornecedor", return_value=_pedido()), \
         patch("routes.fornecedores.db.query", return_value=[{"v": 7000.0}]):
        r = client.post(URL, headers=admin_headers, json={"valor": 100})
    assert r.status_code == 400 and "passa do que falta" in r.get_json()["error"]


def test_pedido_ja_coberto_nao_tem_diferenca_a_descontar(client, admin_headers):
    with patch("routes.fornecedores._pedido_do_fornecedor", return_value=_pedido()), \
         patch("routes.fornecedores.db.query", return_value=[{"v": 7050.0}]):
        r = client.post(URL, headers=admin_headers, json={})
    assert r.status_code == 400


def test_pedido_inexistente_404(client, admin_headers):
    with patch("routes.fornecedores._pedido_do_fornecedor", return_value=None):
        assert client.post(URL, headers=admin_headers, json={}).status_code == 404
        assert client.delete(URL, headers=admin_headers).status_code == 404


def test_desfazer_desconto_zera(client, admin_headers):
    with patch("routes.fornecedores._pedido_do_fornecedor", return_value=_pedido()), \
         patch("routes.fornecedores.db.execute", return_value={}) as ex:
        r = client.delete(URL, headers=admin_headers)
    assert r.status_code == 204 and "desconto = 0" in ex.call_args[0][0]


def test_desconto_viewer_nao_pode(client, viewer_headers):
    assert client.post(URL, headers=viewer_headers, json={}).status_code == 403


def test_marcar_pago_lanca_o_valor_ja_com_desconto(client, admin_headers):
    ped = {"id": PED, "valor_total": 7050.0, "desconto": 493.5, "pago_em": None}
    with patch("routes.fornecedores._pedido_do_fornecedor", return_value=ped), \
         patch("routes.fornecedores._saldo_aberto_fornecedor", return_value=6556.5), \
         patch("routes.fornecedores.db.transaction") as tr, \
         patch("routes.fornecedores.amarracao.validar", return_value=None):
        cur = tr.return_value.__enter__.return_value
        cur.fetchone.side_effect = [{"id": "pg1", "valor": 6556.5}, {"id": PED, "pago_em": "2026-10-20"}]
        r = client.post(f"/api/fornecedores/{FORN}/pedidos/{PED}/pago", headers=admin_headers,
                        json={"modo": "lancar", "data_pagamento": "2026-10-20"})
    assert r.status_code == 201
    inserido = cur.execute.call_args_list[0][0][1]
    assert inserido[1] == 6556.5
