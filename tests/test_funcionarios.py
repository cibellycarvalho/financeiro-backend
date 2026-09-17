from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

FUNC = "33333333-3333-3333-3333-333333333333"
JOSIE = {"id": FUNC, "nome": "Josie", "cnpj": "12345678000195", "valor_combinado": 2500.0, "ativo": True}


def _db(mocker, respostas):
    """db.query devolve, a cada chamada, o valor da primeira chave de `respostas`
    contida no SQL. Valor pode ser lista ou função(params) → lista."""
    def _query(sql, params=()):
        for trecho, valor in respostas.items():
            if trecho in sql:
                return valor(params) if callable(valor) else valor
        raise AssertionError(f"consulta inesperada: {sql[:120]}")
    return mocker.patch("routes.funcionarios.db.query", side_effect=_query)


def _transacao_fake(mocker, retornos):
    """db.transaction() cujo cursor devolve `retornos` em sequência no fetchone()."""
    cur = MagicMock()
    cur.fetchone.side_effect = retornos

    @contextmanager
    def _tx():
        yield cur

    mocker.patch("routes.funcionarios.db.transaction", _tx)
    return cur


# --- cadastro ---------------------------------------------------------------

def test_listar_traz_resumo_do_mes_atual(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios f": [
        {**JOSIE, "lancamentos_mes": [
            {"tipo": "pagamento", "valor": 2500.0, "pago_em": "2026-09-05", "vencimento": None, "numero_nf": None},
            {"tipo": "das", "valor": 75.9, "pago_em": None, "vencimento": "2026-10-20", "numero_nf": None},
        ]},
        {"id": "f-2", "nome": "Renata", "cnpj": None, "valor_combinado": None, "ativo": True, "lancamentos_mes": []},
    ]})
    r = client.get("/api/funcionarios", headers=admin_headers)
    assert r.status_code == 200
    josie, renata = r.get_json()
    assert josie["mes_atual"]["falta"] == ["nf"]
    assert josie["mes_atual"]["das_em_aberto"] is True
    assert josie["mes_atual"]["das_vencimento"] == "2026-10-20"
    assert josie["mes_atual"]["completo"] is False
    assert josie["mes_atual"]["total_pago"] == 2500.0
    assert renata["mes_atual"]["falta"] == ["pagamento", "das", "nf"]
    assert "lancamentos_mes" not in josie


def test_criar_exige_nome_e_normaliza_cnpj(client, admin_headers, mocker):
    execute = mocker.patch("routes.funcionarios.db.execute", return_value={**JOSIE})
    r = client.post("/api/funcionarios", json={"nome": " Josie ", "cnpj": "12.345.678/0001-95", "valor_combinado": "2500"},
                    headers=admin_headers)
    assert r.status_code == 201
    params = execute.call_args.args[1]
    assert params[:3] == ("Josie", "12345678000195", 2500.0)

    r = client.post("/api/funcionarios", json={"nome": "  "}, headers=admin_headers)
    assert r.status_code == 400
    r = client.post("/api/funcionarios", json={"nome": "X", "cnpj": "123"}, headers=admin_headers)
    assert r.status_code == 400 and "CNPJ" in r.get_json()["error"]
    r = client.post("/api/funcionarios", json={"nome": "X", "valor_combinado": -1}, headers=admin_headers)
    assert r.status_code == 400


def test_criar_com_nome_ou_cnpj_fora_de_texto_da_400_nao_500(client, admin_headers, mocker):
    execute = mocker.patch("routes.funcionarios.db.execute", return_value={**JOSIE})

    r = client.post("/api/funcionarios", json={"nome": 12345}, headers=admin_headers)
    assert r.status_code == 400

    r = client.post("/api/funcionarios", json={"nome": "X", "cnpj": ["a"]}, headers=admin_headers)
    assert r.status_code == 400

    r = client.post("/api/funcionarios", json={"nome": "X", "cnpj": 12345678000195}, headers=admin_headers)
    assert r.status_code == 201
    assert execute.call_args.args[1][:2] == ("X", "12345678000195")


def test_editar_e_desativar(client, admin_headers, mocker):
    execute = mocker.patch("routes.funcionarios.db.execute", return_value={**JOSIE, "nome": "Josie R."})
    r = client.put(f"/api/funcionarios/{FUNC}", json={"nome": "Josie R.", "cnpj": "", "valor_combinado": None},
                   headers=admin_headers)
    assert r.status_code == 200 and r.get_json()["nome"] == "Josie R."
    assert execute.call_args.args[1] == ("Josie R.", None, None, FUNC)

    execute.return_value = {"id": FUNC}
    r = client.delete(f"/api/funcionarios/{FUNC}", headers=admin_headers)
    assert r.status_code == 204
    assert "ativo = false" in execute.call_args.args[0]

    execute.return_value = None
    assert client.delete(f"/api/funcionarios/{FUNC}", headers=admin_headers).status_code == 404
    assert client.put(f"/api/funcionarios/{FUNC}", json={"nome": "X"}, headers=admin_headers).status_code == 404


def test_viewer_le_mas_nao_grava(client, viewer_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios f": []})
    assert client.get("/api/funcionarios", headers=viewer_headers).status_code == 200
    assert client.post("/api/funcionarios", json={"nome": "X"}, headers=viewer_headers).status_code == 403
    assert client.put(f"/api/funcionarios/{FUNC}", json={"nome": "X"}, headers=viewer_headers).status_code == 403
    assert client.delete(f"/api/funcionarios/{FUNC}", headers=viewer_headers).status_code == 403


# --- /pagamentos para a Caixa da Semana ---------------------------------------

def test_pagamentos_do_periodo_filtra_por_pago_em_e_so_pagamento_e_das(client, admin_headers, mocker):
    query = _db(mocker, {"JOIN fin_funcionarios f": [
        {"id": "l-1", "tipo": "pagamento", "valor": 2500.0, "data_pagamento": "2026-09-15",
         "competencia": "2026-09-01", "created_at": "x", "funcionario_nome": "Josie"},
    ]})
    r = client.get("/api/funcionarios/pagamentos?de=2026-09-14&ate=2026-09-20", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()[0]["funcionario_nome"] == "Josie"
    sql, params = query.call_args.args
    assert "tipo IN ('pagamento', 'das')" in sql
    assert "pago_em IS NOT NULL" in sql
    assert "pago_em BETWEEN %s AND %s" in sql
    assert params == ("2026-09-14", "2026-09-20")


def test_pagamentos_do_periodo_exige_datas(client, admin_headers):
    assert client.get("/api/funcionarios/pagamentos?de=x&ate=2026-09-20", headers=admin_headers).status_code == 400
