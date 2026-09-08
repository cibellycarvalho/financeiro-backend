import aliases


def test_normalizar_tira_acento_caixa_e_espacos():
    assert aliases.normalizar("  Multivale   Montagem É Estruturas Ltda ") == "multivale montagem e estruturas ltda"
    assert aliases.normalizar("FLÁVIA") == "flavia"


def test_sugerir_fornecedor_usa_alias_norm(mocker):
    query = mocker.patch("aliases.db.query", return_value=[{"fornecedor_id": "f-1"}])
    assert aliases.sugerir_fornecedor("Flávia", "vendedor") == "f-1"
    sql, params = query.call_args.args
    assert "alias_norm = %s" in sql
    assert params == ("vendedor", "flavia")


def test_sugerir_fornecedor_sem_texto_nao_consulta(mocker):
    query = mocker.patch("aliases.db.query")
    assert aliases.sugerir_fornecedor(None, "vendedor") is None
    assert aliases.sugerir_fornecedor("   ", "destinatario") is None
    query.assert_not_called()


def test_sugerir_fornecedor_sem_match_devolve_none(mocker):
    mocker.patch("aliases.db.query", return_value=[])
    assert aliases.sugerir_fornecedor("Ninguem", "vendedor") is None


def test_aprender_alias_faz_upsert_trocando_dono(mocker):
    execute = mocker.patch("aliases.db.execute")
    aliases.aprender_alias("f-2", "MIAO Atacadista", "destinatario")
    sql, params = execute.call_args.args
    assert "ON CONFLICT (origem, alias_norm) DO UPDATE SET fornecedor_id = EXCLUDED.fornecedor_id" in sql
    assert params == ("f-2", "MIAO Atacadista", "miao atacadista", "destinatario")


def test_aprender_alias_sem_texto_nao_grava(mocker):
    execute = mocker.patch("aliases.db.execute")
    aliases.aprender_alias("f-2", "", "vendedor")
    execute.assert_not_called()
