from unittest.mock import patch

SEMANA = "2026-09-14"   # segunda-feira
LINHA = {
    "semana": SEMANA, "saldo_conta": 12000.0, "saldo_em": "2026-09-14T12:00:00+00:00",
    "reserva_aplicada": 50000.0, "agenda": {"2026-09-15": 2280.51},
    "ajustes_pagamento": {}, "informado_por": "x", "updated_at": "2026-09-14T12:00:00+00:00",
}


def test_ler_semana_nunca_informada_devolve_200_vazio(client, admin_headers):
    with patch("routes.planejamento.db.query", return_value=[]):
        r = client.get(f"/api/planejamento/{SEMANA}", headers=admin_headers)
    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["saldo_conta"] is None and corpo["reserva_aplicada"] is None
    assert corpo["agenda"] == {} and corpo["ajustes_pagamento"] == {}


def test_ler_semana_informada(client, admin_headers):
    with patch("routes.planejamento.db.query", return_value=[LINHA]):
        r = client.get(f"/api/planejamento/{SEMANA}", headers=admin_headers)
    assert r.get_json()["saldo_conta"] == 12000.0


def test_gravar_faz_upsert_numa_linha_so(client, admin_headers):
    with patch("routes.planejamento.db.execute", return_value=LINHA) as ex:
        r = client.put(f"/api/planejamento/{SEMANA}", headers=admin_headers, json={
            "saldo_conta": 12000, "reserva_aplicada": 50000,
            "agenda": {"2026-09-15": 2280.51}, "ajustes_pagamento": {"pg-1": True},
        })
    assert r.status_code == 200
    sql, params = ex.call_args[0]
    assert "ON CONFLICT (semana) DO UPDATE" in sql
    # a hora do saldo só muda quando o saldo muda — é ela que decide o que já
    # estava fora da conta na regra anti-desconto-duplo
    assert "IS DISTINCT FROM EXCLUDED.saldo_conta" in sql
    # saldo vai duas vezes: no valor e no CASE que decide se saldo_em nasce
    assert params[:4] == (SEMANA, 12000.0, 12000.0, 50000.0)


def test_gravar_semana_que_nao_e_segunda_400(client, admin_headers):
    r = client.put("/api/planejamento/2026-09-15", headers=admin_headers, json={})
    assert r.status_code == 400
    assert "segunda" in r.get_json()["error"]


def test_gravar_data_invalida_400(client, admin_headers):
    r = client.put("/api/planejamento/15-09-2026", headers=admin_headers, json={})
    assert r.status_code == 400


def test_gravar_agenda_fora_da_semana_400(client, admin_headers):
    r = client.put(f"/api/planejamento/{SEMANA}", headers=admin_headers,
                   json={"agenda": {"2026-09-21": 10}})
    assert r.status_code == 400


def test_gravar_agenda_que_nao_e_objeto_400(client, admin_headers):
    for ruim in ([1, 2], "texto", 5):
        r = client.put(f"/api/planejamento/{SEMANA}", headers=admin_headers, json={"agenda": ruim})
        assert r.status_code == 400


def test_gravar_agenda_valor_nao_numerico_400(client, admin_headers):
    r = client.put(f"/api/planejamento/{SEMANA}", headers=admin_headers,
                   json={"agenda": {"2026-09-15": "2.280,51"}})
    assert r.status_code == 400


def test_gravar_ajustes_devem_ser_booleanos_400(client, admin_headers):
    r = client.put(f"/api/planejamento/{SEMANA}", headers=admin_headers,
                   json={"ajustes_pagamento": {"pg-1": "sim"}})
    assert r.status_code == 400


def test_saldo_negativo_aceito_reserva_negativa_400(client, admin_headers):
    with patch("routes.planejamento.db.execute", return_value=LINHA):
        ok = client.put(f"/api/planejamento/{SEMANA}", headers=admin_headers, json={"saldo_conta": -500})
    assert ok.status_code == 200
    ruim = client.put(f"/api/planejamento/{SEMANA}", headers=admin_headers, json={"reserva_aplicada": -1})
    assert ruim.status_code == 400


def test_gravar_viewer_pode(client, viewer_headers):
    """Os dois donos preenchem (decisão de 14/09/2026). Se alguém 'padronizar'
    a rota com @require_admin, o marido dela perde o acesso — este teste trava."""
    with patch("routes.planejamento.db.execute", return_value=LINHA):
        r = client.put(f"/api/planejamento/{SEMANA}", headers=viewer_headers, json={"saldo_conta": 1})
    assert r.status_code == 200


def test_quem_nao_tem_papel_e_barrado(client, monkeypatch):
    monkeypatch.setattr("auth.verify_jwt", lambda t: {"user_id": "u", "fin_role": None})
    r = client.put(f"/api/planejamento/{SEMANA}", headers={"Authorization": "Bearer x"}, json={})
    assert r.status_code == 403
