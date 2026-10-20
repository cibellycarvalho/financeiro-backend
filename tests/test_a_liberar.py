from unittest.mock import patch, MagicMock

from routes.repasses import agrupar_a_liberar


def _p(dia, liquido, status="approved", em_details=True):
    p = {"status": status, "money_release_date": f"{dia}T12:00:00.000-03:00"}
    if em_details:
        p["transaction_details"] = {"net_received_amount": liquido}
    else:
        p["net_received_amount"] = liquido
    return p


def test_soma_por_dia_e_ignora_fora_da_janela_e_nao_aprovados():
    pags = [
        _p("2026-10-21", 100.10), _p("2026-10-21", 50.05),
        _p("2026-10-22", 30), _p("2026-10-30", 999),
        _p("2026-10-21", 70, status="refunded"),
        {"status": "approved", "money_release_date": None},
        _p("2026-10-22", 10, em_details=False),
    ]
    assert agrupar_a_liberar(pags, "2026-10-20", "2026-10-26") == {
        "2026-10-21": 150.15, "2026-10-22": 40.0}


def _resp(results, total=None):
    r = MagicMock(status_code=200)
    r.json.return_value = {"results": results, "paging": {"total": total if total is not None else len(results)}}
    return r


def test_endpoint_agrega(client, admin_headers):
    with patch("config.MERCADO_PAGO_ACCESS_TOKEN", "tok"), \
         patch("routes.repasses.http_req.get", return_value=_resp([_p("2026-10-21", 80)])) as g:
        r = client.get("/api/repasses/a-liberar?de=2026-10-20&ate=2026-10-26", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()["por_dia"] == {"2026-10-21": 80.0}
    assert r.get_json()["total"] == 80.0
    assert g.call_args.kwargs["params"]["range"] == "money_release_date"


def test_endpoint_sem_token_503(client, admin_headers):
    with patch("config.MERCADO_PAGO_ACCESS_TOKEN", None):
        assert client.get("/api/repasses/a-liberar", headers=admin_headers).status_code == 503


def test_endpoint_data_invalida_400(client, admin_headers):
    with patch("config.MERCADO_PAGO_ACCESS_TOKEN", "tok"):
        assert client.get("/api/repasses/a-liberar?de=xx", headers=admin_headers).status_code == 400


def test_endpoint_erro_mp_502(client, admin_headers):
    ruim = MagicMock(status_code=500, text="boom")
    with patch("config.MERCADO_PAGO_ACCESS_TOKEN", "tok"), patch("routes.repasses.http_req.get", return_value=ruim):
        assert client.get("/api/repasses/a-liberar", headers=admin_headers).status_code == 502


def test_endpoint_exige_login(client):
    assert client.get("/api/repasses/a-liberar").status_code == 401
