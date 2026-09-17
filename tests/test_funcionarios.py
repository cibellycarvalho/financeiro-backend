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


# --- lançamentos --------------------------------------------------------------

TOKEN = "pendentes/" + "0" * 32 + ".pdf"
LINHA_PAG = {"id": "l-1", "funcionario_id": FUNC, "tipo": "pagamento", "competencia": "2026-09-01", "valor": 2500.0,
             "vencimento": None, "pago_em": "2026-09-15", "numero_nf": None, "id_transacao": "E8109949120260915120000abc",
             "arquivo_path": None, "boleto_path": None, "comprovante_path": None, "observacao": None}
LINHA_DAS = {**LINHA_PAG, "id": "l-2", "tipo": "das", "valor": 75.9, "vencimento": "2026-10-20", "pago_em": None,
             "id_transacao": None}


def test_listar_lancamentos_da_competencia(client, admin_headers, mocker):
    query = _db(mocker, {"FROM fin_funcionario_lancamentos": [LINHA_PAG, LINHA_DAS]})
    r = client.get(f"/api/funcionarios/{FUNC}/lancamentos?competencia=2026-09", headers=admin_headers)
    assert r.status_code == 200
    assert [l["tipo"] for l in r.get_json()] == ["pagamento", "das"]
    assert query.call_args.args[1] == (FUNC, "2026-09-01")
    assert client.get(f"/api/funcionarios/{FUNC}/lancamentos?competencia=set", headers=admin_headers).status_code == 400


def test_meses_lista_n_meses_com_resumo_mesmo_vazios(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionario_lancamentos": [LINHA_PAG, LINHA_DAS]})
    r = client.get(f"/api/funcionarios/{FUNC}/meses?ate=2026-09&n=3", headers=admin_headers)
    assert r.status_code == 200
    meses = r.get_json()
    assert [m["competencia"] for m in meses] == ["2026-09-01", "2026-08-01", "2026-07-01"]
    assert meses[0]["falta"] == ["nf"] and meses[0]["das_em_aberto"] is True
    assert meses[1]["falta"] == ["pagamento", "das", "nf"]


def test_criar_pagamento_move_anexo_na_transacao(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "UNION ALL": []})
    cur = _transacao_fake(mocker, [{**LINHA_PAG, "arquivo_path": None}])
    mover = mocker.patch("routes.funcionarios.storage.mover")
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={
        "tipo": "pagamento", "competencia": "2026-09", "valor": 2500, "pago_em": "2026-09-15",
        "id_transacao": "E8109949120260915120000abc", "arquivo_token": TOKEN,
    }, headers=admin_headers)
    assert r.status_code == 201, r.get_json()
    insert_sql, insert_params = cur.execute.call_args_list[0].args
    assert "INSERT INTO fin_funcionario_lancamentos" in insert_sql
    assert insert_params[:3] == (FUNC, "pagamento", "2026-09-01")
    destino = f"funcionarios/{FUNC}/2026-09/pagamento-l-1.pdf"
    mover.assert_called_once_with(TOKEN, destino)
    update_sql, update_params = cur.execute.call_args_list[-1].args
    assert "SET arquivo_path = %s" in update_sql and update_params == (destino, "l-1")
    assert r.get_json()["arquivo_path"] == destino


def test_criar_pagamento_valida_valor_e_data(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE]})
    base = {"tipo": "pagamento", "competencia": "2026-09"}
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={**base, "valor": 0, "pago_em": "2026-09-15"},
                       headers=admin_headers).status_code == 400
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={**base, "valor": 10},
                       headers=admin_headers).status_code == 400
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={**base, "valor": 10, "pago_em": "15/09/2026"},
                       headers=admin_headers).status_code == 400
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={"tipo": "ferias", "competencia": "2026-09"},
                       headers=admin_headers).status_code == 400
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={**base, "valor": 10, "pago_em": "2026-09-15",
                       "arquivo_token": "pendentes/../x.pdf"}, headers=admin_headers).status_code == 400


def test_criar_das_em_aberto_com_boleto_e_recusa_o_segundo_do_mes(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "AND tipo = %s": []})
    cur = _transacao_fake(mocker, [{**LINHA_DAS, "boleto_path": None}])
    mover = mocker.patch("routes.funcionarios.storage.mover")
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={
        "tipo": "das", "competencia": "2026-09-01", "valor": 75.9, "vencimento": "2026-10-20", "boleto_token": TOKEN,
    }, headers=admin_headers)
    assert r.status_code == 201, r.get_json()
    mover.assert_called_once_with(TOKEN, f"funcionarios/{FUNC}/2026-09/das-boleto-l-2.pdf")
    assert "SET boleto_path = %s" in cur.execute.call_args_list[-1].args[0]

    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "AND tipo = %s": [LINHA_DAS]})
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={"tipo": "das", "competencia": "2026-09", "valor": 75.9},
                    headers=admin_headers)
    assert r.status_code == 409
    assert r.get_json()["existente_id"] == "l-2"


def test_criar_nf_exige_numero_ou_arquivo(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "AND tipo = %s": []})
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={"tipo": "nf", "competencia": "2026-08"},
                    headers=admin_headers)
    assert r.status_code == 400 and "número" in r.get_json()["error"]
    _transacao_fake(mocker, [{**LINHA_PAG, "id": "l-3", "tipo": "nf", "numero_nf": "123", "valor": None, "pago_em": None}])
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={"tipo": "nf", "competencia": "2026-08", "numero_nf": "123"},
                    headers=admin_headers)
    assert r.status_code == 201 and r.get_json()["valor"] is None


def test_pix_repetido_em_qualquer_tabela_da_409(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE],
                 "UNION ALL": [{"id": "pg-1", "data_pagamento": "2026-09-15", "valor": 2500.0, "onde": "fornecedor"}]})
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={
        "tipo": "pagamento", "competencia": "2026-09", "valor": 2500, "pago_em": "2026-09-15",
        "id_transacao": "E8109949120260915120000abc",
    }, headers=admin_headers)
    assert r.status_code == 409
    assert "15/09/2026" in r.get_json()["error"] and "fornecedor" in r.get_json()["error"]


def test_storage_falha_ao_mover_nada_gravado(client, admin_headers, mocker):
    import storage
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "UNION ALL": []})
    _transacao_fake(mocker, [{**LINHA_PAG}])
    mocker.patch("routes.funcionarios.storage.mover", side_effect=storage.StorageErro("fora"))
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={
        "tipo": "pagamento", "competencia": "2026-09", "valor": 2500, "pago_em": "2026-09-15", "arquivo_token": TOKEN,
    }, headers=admin_headers)
    assert r.status_code == 500
    assert "nada foi salvo" in r.get_json()["error"]


def test_editar_marca_das_pago_e_move_comprovante(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionario_lancamentos WHERE id = %s": [LINHA_DAS], "UNION ALL": [], "AND tipo = %s": []})
    cur = _transacao_fake(mocker, [{**LINHA_DAS, "pago_em": "2026-10-18", "id_transacao": "E81099491202610181200zz"}])
    mover = mocker.patch("routes.funcionarios.storage.mover")
    r = client.put(f"/api/funcionarios/{FUNC}/lancamentos/l-2", json={
        "pago_em": "2026-10-18", "id_transacao": "E81099491202610181200zz", "comprovante_token": TOKEN,
    }, headers=admin_headers)
    assert r.status_code == 200, r.get_json()
    update_sql, update_params = cur.execute.call_args_list[0].args
    assert "UPDATE fin_funcionario_lancamentos" in update_sql
    # mesclado com a linha atual: valor e vencimento continuam
    assert 75.9 in update_params and "2026-10-20" in update_params and "2026-10-18" in update_params
    mover.assert_called_once_with(TOKEN, f"funcionarios/{FUNC}/2026-09/das-comprovante-l-2.pdf")
    assert r.get_json()["pago_em"] == "2026-10-18"


def test_editar_competencia_de_nf_para_mes_que_ja_tem_nf_da_409(client, admin_headers, mocker):
    nf = {**LINHA_PAG, "id": "l-3", "tipo": "nf", "numero_nf": "123", "pago_em": None}
    _db(mocker, {"FROM fin_funcionario_lancamentos WHERE id = %s": [nf],
                 "AND tipo = %s": lambda params: [{**nf, "id": "l-9"}] if params[1] == "2026-08-01" else []})
    r = client.put(f"/api/funcionarios/{FUNC}/lancamentos/l-3", json={"competencia": "2026-08"}, headers=admin_headers)
    assert r.status_code == 409 and r.get_json()["existente_id"] == "l-9"


def test_editar_lancamento_inexistente_404(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionario_lancamentos WHERE id = %s": []})
    assert client.put(f"/api/funcionarios/{FUNC}/lancamentos/l-x", json={"valor": 1}, headers=admin_headers).status_code == 404


def test_apagar_lancamento(client, admin_headers, mocker):
    execute = mocker.patch("routes.funcionarios.db.execute", return_value={"id": "l-1"})
    assert client.delete(f"/api/funcionarios/{FUNC}/lancamentos/l-1", headers=admin_headers).status_code == 204
    assert execute.call_args.args[1] == ("l-1", FUNC)
    execute.return_value = None
    assert client.delete(f"/api/funcionarios/{FUNC}/lancamentos/l-1", headers=admin_headers).status_code == 404


def test_anexo_por_qual(client, admin_headers, mocker):
    url = mocker.patch("routes.funcionarios.anexos.url_anexo", return_value=jsonify_ok())
    r = client.get(f"/api/funcionarios/{FUNC}/lancamentos/l-2/anexo?qual=boleto", headers=admin_headers)
    assert r.status_code == 200
    url.assert_called_once_with("fin_funcionario_lancamentos", "funcionario_id", FUNC, "l-2", "boleto_path")
    assert client.get(f"/api/funcionarios/{FUNC}/lancamentos/l-2/anexo?qual=senha", headers=admin_headers).status_code == 400


def jsonify_ok():
    from flask import jsonify
    from app import create_app
    with create_app().app_context():
        return jsonify({"url": "https://x/assinada"})


def test_viewer_nao_grava_lancamento(client, viewer_headers):
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={}, headers=viewer_headers).status_code == 403
    assert client.put(f"/api/funcionarios/{FUNC}/lancamentos/l-1", json={}, headers=viewer_headers).status_code == 403
    assert client.delete(f"/api/funcionarios/{FUNC}/lancamentos/l-1", headers=viewer_headers).status_code == 403
