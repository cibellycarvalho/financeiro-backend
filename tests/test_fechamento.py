"""Rotas de fechamento portadas do CRM.

Portadas FIEIS: o CRM aceita valor_total e total vindos da tela, sem recalcular.
Mudar isso durante uma migração de endereço faria os números divergirem do que a
usuária vê hoje, sem ninguém pedir. A observação está registrada como trabalho
próprio, não embutida aqui.
"""
from unittest.mock import patch

COMPRA = {"id": 1, "conta_ml": "YUSO", "mes_ano": "2026-08", "data": "2026-08-05",
          "fornecedor": "Fornecedor X", "nota_fiscal": "123", "produto": "Cabo",
          "quantidade": 10, "valor_unitario": 5.0, "valor_total": 50.0,
          "status": "pago", "nota": None}


def test_lista_compras_do_mes(client, admin_headers):
    with patch("routes.fechamento.db.query", return_value=[COMPRA]) as q:
        r = client.get("/api/fechamento/compras?mes_ano=2026-08", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()[0]["fornecedor"] == "Fornecedor X"
    assert q.call_args[0][1] == ("YUSO", "2026-08")


def test_mes_ano_invalido_recusa(client, admin_headers):
    r = client.get("/api/fechamento/compras?mes_ano=agosto", headers=admin_headers)
    assert r.status_code == 400


def test_viewer_grava_na_propria_loja_mesmo_pedindo_outra(client, viewer_headers):
    """A fronteira: o viewer da fixture é da M12. Pedir YUSO não pode gravar na YUSO."""
    with patch("routes.fechamento.db.execute", return_value=COMPRA) as ex:
        r = client.post("/api/fechamento/compras?conta_ml=YUSO",
                        json={"mes_ano": "2026-08", "produto": "Cabo",
                              "quantidade": 1, "valor_unitario": 5.0, "valor_total": 5.0},
                        headers=viewer_headers)
    assert r.status_code == 201
    assert ex.call_args[0][1][0] == "M12"


def test_viewer_nao_edita_compra_de_outra_loja(client, viewer_headers):
    """O UPDATE filtra por loja além do id — senão um id de outra loja seria editável."""
    with patch("routes.fechamento.db.execute", return_value=None) as ex:
        r = client.put("/api/fechamento/compras/1?conta_ml=YUSO",
                       json={"produto": "Cabo"}, headers=viewer_headers)
    assert r.status_code == 404
    assert ex.call_args[0][1][-1] == "M12"


def test_viewer_nao_apaga_compra_de_outra_loja(client, viewer_headers):
    with patch("routes.fechamento.db.execute", return_value=None) as ex:
        r = client.delete("/api/fechamento/compras/1?conta_ml=YUSO", headers=viewer_headers)
    assert r.status_code == 404
    assert ex.call_args[0][1] == (1, "M12")


def test_cria_compra_grava_o_total_que_a_tela_mandou(client, admin_headers):
    """Comportamento do CRM preservado: o servidor não recalcula."""
    with patch("routes.fechamento.db.execute", return_value=COMPRA) as ex:
        client.post("/api/fechamento/compras",
                    json={"mes_ano": "2026-08", "quantidade": 10,
                          "valor_unitario": 5.0, "valor_total": 47.5},
                    headers=admin_headers)
    assert ex.call_args[0][1][8] == 47.5


FRETE = {"id": 3, "conta_ml": "YUSO", "mes_ano": "2026-08", "data": "2026-08-02",
         "motorista": "João", "coleta_sp": True, "frete_full": 120.0,
         "total": 120.0, "status": "pago"}


def test_coleta_sp_e_um_sim_ou_nao_nao_um_valor(client, admin_headers):
    """No CRM coleta_sp é booleano. Tratar como dinheiro somaria bool com real."""
    with patch("routes.fechamento.db.execute", return_value=FRETE) as ex:
        client.post("/api/fechamento/fretes",
                    json={"mes_ano": "2026-08", "coleta_sp": True,
                          "frete_full": 120.0, "total": 120.0},
                    headers=admin_headers)
    assert ex.call_args[0][1][4] is True


def test_lista_fretes_do_mes(client, admin_headers):
    with patch("routes.fechamento.db.query", return_value=[FRETE]):
        r = client.get("/api/fechamento/fretes?mes_ano=2026-08", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()[0]["motorista"] == "João"


MONTAGEM = {"id": 5, "conta_ml": "YUSO", "mes_ano": "2026-08",
            "montador": "Pedro", "valor": 412.5, "data": "2026-08-07"}


def test_lista_montagem_do_mes(client, admin_headers):
    with patch("routes.fechamento.db.query", return_value=[MONTAGEM]):
        r = client.get("/api/fechamento/montagem?mes_ano=2026-08", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()[0]["montador"] == "Pedro"


def test_cria_montagem(client, admin_headers):
    with patch("routes.fechamento.db.execute", return_value=MONTAGEM) as ex:
        r = client.post("/api/fechamento/montagem",
                        json={"mes_ano": "2026-08", "montador": "Pedro", "valor": 412.5},
                        headers=admin_headers)
    assert r.status_code == 201
    assert ex.call_args[0][1][2] == "Pedro"
