"""Contagem do galpão, portada do CRM.

O galpão é um fato do NEGÓCIO dela, não de uma loja: a tabela é chaveada por
dono da conta e mês, não por conta_ml. Por isso não passa pela trava de loja —
não há loja envolvida.

O dono é o id do usuário no Supabase. O CRM o chama de `id` e o Painel de
`user_id`, mas é o mesmo valor (o `sub` do token). Se não fosse, as contagens
gravadas de um lado não seriam encontradas do outro.
"""
from unittest.mock import patch

GALPAO = {"mes_ano": "2026-08", "valor": 15000.0, "observacao": "contagem do dia 31",
          "atualizado_em": "2026-08-31T18:00:00+00:00"}

# O mesmo id que a fixture ADMIN_USER usa — e que o CRM grava como owner_user_id.
OWNER = "fd3a3d59-727f-40e2-bbea-c91187d2f0a7"


def test_le_a_contagem_do_mes(client, admin_headers):
    with patch("routes.galpao.db.query", return_value=[GALPAO]) as q:
        r = client.get("/api/fechamento/galpao?mes_ano=2026-08", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()["valor"] == 15000.0
    assert q.call_args[0][1] == (OWNER, "2026-08")


def test_mes_sem_contagem_responde_404_e_nao_zero(client, admin_headers):
    """"Não contei" e "contei e deu zero" são coisas opostas no fechamento.
    Devolver 0 aqui apagaria a diferença."""
    with patch("routes.galpao.db.query", return_value=[]):
        r = client.get("/api/fechamento/galpao?mes_ano=2026-08", headers=admin_headers)
    assert r.status_code == 404


def test_grava_a_contagem(client, admin_headers):
    with patch("routes.galpao.db.execute", return_value=GALPAO) as ex:
        r = client.put("/api/fechamento/galpao",
                       json={"mes_ano": "2026-08", "valor": 15000.0,
                             "observacao": "contagem do dia 31"},
                       headers=admin_headers)
    assert r.status_code == 200
    assert ex.call_args[0][1][0] == OWNER


def test_valor_negativo_recusa(client, admin_headers):
    r = client.put("/api/fechamento/galpao",
                   json={"mes_ano": "2026-08", "valor": -1}, headers=admin_headers)
    assert r.status_code == 400


def test_valor_que_nao_e_numero_recusa(client, admin_headers):
    r = client.put("/api/fechamento/galpao",
                   json={"mes_ano": "2026-08", "valor": "quinze mil"},
                   headers=admin_headers)
    assert r.status_code == 400


def test_contagem_zero_e_aceita(client, admin_headers):
    """Zero é uma contagem legítima: o galpão pode ter esvaziado."""
    with patch("routes.galpao.db.execute", return_value={**GALPAO, "valor": 0.0}):
        r = client.put("/api/fechamento/galpao",
                       json={"mes_ano": "2026-08", "valor": 0}, headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()["valor"] == 0.0
