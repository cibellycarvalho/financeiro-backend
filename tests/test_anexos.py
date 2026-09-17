import io

import pytest

import anexos

FORN = "11111111-1111-1111-1111-111111111111"
TOKEN = "pendentes/" + "a" * 32 + ".png"


def test_destino_anexo_rejeita_token_fora_de_pendentes():
    with pytest.raises(ValueError):
        anexos.destino_anexo(FORN, "pedidos", "p-9", "pendentes/../outro.pdf")
    with pytest.raises(ValueError):
        anexos.destino_anexo(FORN, "pedidos", "p-9", "pendentes/abc.pdf")  # hex curto demais
    assert anexos.destino_anexo(FORN, "pedidos", "p-9", TOKEN) == f"{FORN}/pedidos/p-9.png"


def test_destino_anexo_aceita_prefixo_composto_para_funcionarios():
    # funcionarios/<id>/<AAAA-MM>/<tipo>-<id>.<ext> — o prefixo é quem separa no mesmo bucket
    assert anexos.destino_anexo("funcionarios/f-1", "2026-09", "das-boleto-l-1", "pendentes/" + "0" * 32 + ".pdf") \
        == "funcionarios/f-1/2026-09/das-boleto-l-1.pdf"


def test_arquivo_token_valido():
    assert anexos.arquivo_token_valido(TOKEN)
    assert not anexos.arquivo_token_valido(None)
    assert not anexos.arquivo_token_valido("")
    assert not anexos.arquivo_token_valido("outro/" + "a" * 32 + ".png")
    assert not anexos.arquivo_token_valido("pendentes/" + "a" * 32 + ".gif")


def test_subir_pendente_ignora_falha_na_limpeza(mocker):
    mocker.patch("anexos.storage.limpar_pendentes", side_effect=RuntimeError("lista fora"))
    enviar = mocker.patch("anexos.storage.enviar_pendente", return_value="pendentes/x.pdf")
    assert anexos.subir_pendente(b"%PDF", "application/pdf") == "pendentes/x.pdf"
    enviar.assert_called_once_with(b"%PDF", "application/pdf")


def test_ler_arquivo_enviado_valida_tipo_e_tamanho(app):
    with app.test_request_context("/x", method="POST", data={"arquivo": (io.BytesIO(b"gif"), "a.gif", "image/gif")},
                                  content_type="multipart/form-data"):
        dados, mime, erro = anexos.ler_arquivo_enviado()
        assert dados is None and erro[1] == 400
        assert "PDF, JPG ou PNG" in erro[0].get_json()["error"]
    with app.test_request_context("/x", method="POST", data={}, content_type="multipart/form-data"):
        _, _, erro = anexos.ler_arquivo_enviado()
        assert erro[1] == 400 and "obrigatório" in erro[0].get_json()["error"]
    with app.test_request_context("/x", method="POST", data={"arquivo": (io.BytesIO(b"%PDF ok"), "a.pdf", "application/pdf")},
                                  content_type="multipart/form-data"):
        dados, mime, erro = anexos.ler_arquivo_enviado()
        assert erro is None and dados == b"%PDF ok" and mime == "application/pdf"


def test_url_anexo_filtra_pelo_dono_e_pela_coluna(app, mocker):
    # jsonify() exige app context — fora de uma rota (chamada direta, como aqui),
    # quem chama tem que abrir uma; dentro da rota real isso já vem de graça.
    query = mocker.patch("anexos.db.query", return_value=[{"boleto_path": "funcionarios/f-1/2026-09/das-boleto-l-1.pdf"}])
    mocker.patch("anexos.storage.url_assinada", return_value="https://x/assinada")
    with app.app_context():
        resposta = anexos.url_anexo("fin_funcionario_lancamentos", "funcionario_id", "f-1", "l-1", "boleto_path")
        assert resposta.get_json() == {"url": "https://x/assinada"}
    sql, params = query.call_args.args
    assert "SELECT boleto_path FROM fin_funcionario_lancamentos" in sql
    assert "funcionario_id = %s" in sql
    assert params == ("l-1", "f-1")


def test_url_anexo_sem_arquivo_404(app, mocker):
    mocker.patch("anexos.db.query", return_value=[{"arquivo_path": None}])
    with app.app_context():
        resposta, status = anexos.url_anexo("fin_pedidos_fornecedor", "fornecedor_id", FORN, "p-1")
    assert status == 404
