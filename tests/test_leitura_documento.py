import json
from pathlib import Path

import pytest

import leitura_documento as ld

FIX = Path(__file__).parent / "fixtures"


def _fixture(nome):
    return json.loads((FIX / nome).read_text())


# --- data_do_id_transacao ---------------------------------------------------

def test_data_do_id_transacao_le_data_do_e2e():
    assert ld.data_do_id_transacao("E8109949120260824004025qquKDYh56") == "2026-08-24"


def test_data_do_id_transacao_ignora_formato_estranho():
    assert ld.data_do_id_transacao("ABC123") is None
    assert ld.data_do_id_transacao(None) is None
    assert ld.data_do_id_transacao("") is None


# --- ler_pedido -------------------------------------------------------------

def test_ler_pedido_descarta_item_sem_produto_ou_sem_quantidade(mocker):
    mocker.patch("leitura_documento._chamar", return_value=_fixture("leitura_pedido_fl.json"))
    lido = ld.ler_pedido(b"%PDF", "application/pdf")
    assert [i["produto"] for i in lido["itens"]] == ["CABO HDMI FIBRA 8K 20M", "EMENDA RJ45 EMBORRACHADO"]
    assert lido["numero_pedido"] == "2026/9001"
    assert lido["data_pedido"] == "2026-09-01"
    assert lido["texto_vendedor"] == "Flavia"
    assert lido["total_documento"] == 21000.0


def test_ler_pedido_sem_itens_validos_levanta_leitura_falhou(mocker):
    mocker.patch("leitura_documento._chamar", return_value={"itens": [], "numero_pedido": None,
                                                              "data_pedido": None, "texto_vendedor": None,
                                                              "total_documento": None})
    with pytest.raises(ld.LeituraFalhou):
        ld.ler_pedido(b"%PDF", "application/pdf")


def test_ler_pedido_data_invalida_vira_none(mocker):
    dados = _fixture("leitura_pedido_fl.json")
    dados["data_pedido"] = "24/08/2026"
    mocker.patch("leitura_documento._chamar", return_value=dados)
    assert ld.ler_pedido(b"%PDF", "application/pdf")["data_pedido"] is None


# --- ler_comprovante --------------------------------------------------------

def test_ler_comprovante_data_vem_do_e2e_nao_da_ia(mocker):
    mocker.patch("leitura_documento._chamar", return_value=_fixture("leitura_comprovante_sicredi.json"))
    lido = ld.ler_comprovante(b"%PDF", "application/pdf")
    # a IA leu 23/08 (fuso), mas o E2E diz 24/08 00:40 — o E2E manda
    assert lido["data_pagamento"] == "2026-08-24"
    assert lido["valor"] == 30000.0
    assert lido["destinatario"] == "MIAO ATACADISTA E REPRESENTACOES LTDA"


def test_ler_comprovante_sem_e2e_mantem_data_da_ia(mocker):
    dados = _fixture("leitura_comprovante_sicredi.json")
    dados["id_transacao"] = None
    mocker.patch("leitura_documento._chamar", return_value=dados)
    assert ld.ler_comprovante(b"x", "image/png")["data_pagamento"] == "2026-08-23"


def test_ler_comprovante_valor_zero_levanta_leitura_falhou(mocker):
    dados = _fixture("leitura_comprovante_sicredi.json")
    dados["valor"] = 0
    mocker.patch("leitura_documento._chamar", return_value=dados)
    with pytest.raises(ld.LeituraFalhou):
        ld.ler_comprovante(b"x", "image/png")


# --- _chamar ----------------------------------------------------------------

def test_chamar_sem_chave_levanta_indisponivel(monkeypatch):
    monkeypatch.setattr("leitura_documento.config.ANTHROPIC_API_KEY", "")
    with pytest.raises(ld.LeituraIndisponivel):
        ld._chamar(b"x", "image/png", "instrucao", {"type": "object"})


def test_chamar_monta_bloco_document_para_pdf_e_image_para_foto(monkeypatch, mocker):
    monkeypatch.setattr("leitura_documento.config.ANTHROPIC_API_KEY", "sk-teste")
    client = mocker.MagicMock()
    bloco_texto = mocker.MagicMock(type="text", text='{"ok": true}')
    client.messages.create.return_value = mocker.MagicMock(stop_reason="end_turn", content=[bloco_texto])
    mocker.patch("leitura_documento.anthropic.Anthropic", return_value=client)

    ld._chamar(b"%PDF", "application/pdf", "instrucao", {"type": "object"})
    conteudo = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert conteudo[0]["type"] == "document"
    assert conteudo[0]["source"]["media_type"] == "application/pdf"
    assert client.messages.create.call_args.kwargs["output_config"]["format"]["type"] == "json_schema"

    ld._chamar(b"\x89PNG", "image/png", "instrucao", {"type": "object"})
    conteudo = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert conteudo[0]["type"] == "image"
    assert conteudo[0]["source"]["media_type"] == "image/png"


def test_chamar_recusa_vira_leitura_falhou(monkeypatch, mocker):
    monkeypatch.setattr("leitura_documento.config.ANTHROPIC_API_KEY", "sk-teste")
    client = mocker.MagicMock()
    client.messages.create.return_value = mocker.MagicMock(stop_reason="refusal", content=[])
    mocker.patch("leitura_documento.anthropic.Anthropic", return_value=client)
    with pytest.raises(ld.LeituraFalhou):
        ld._chamar(b"x", "image/png", "instrucao", {"type": "object"})


def test_chamar_erro_de_conexao_vira_indisponivel(monkeypatch, mocker):
    import anthropic
    monkeypatch.setattr("leitura_documento.config.ANTHROPIC_API_KEY", "sk-teste")
    client = mocker.MagicMock()
    client.messages.create.side_effect = anthropic.APIConnectionError(request=mocker.MagicMock())
    mocker.patch("leitura_documento.anthropic.Anthropic", return_value=client)
    with pytest.raises(ld.LeituraIndisponivel):
        ld._chamar(b"x", "image/png", "instrucao", {"type": "object"})


def test_chamar_resposta_invalida_vira_leitura_falhou(monkeypatch, mocker):
    import anthropic
    monkeypatch.setattr("leitura_documento.config.ANTHROPIC_API_KEY", "sk-teste")
    client = mocker.MagicMock()
    client.messages.create.side_effect = anthropic.APIResponseValidationError(
        response=mocker.MagicMock(status_code=200, headers={}), body=None
    )
    mocker.patch("leitura_documento.anthropic.Anthropic", return_value=client)
    with pytest.raises(ld.LeituraFalhou):
        ld._chamar(b"x", "image/png", "instrucao", {"type": "object"})


# --- ler_boleto_das ---------------------------------------------------------

def test_ler_boleto_das_normaliza_competencia_e_cnpj(mocker):
    mocker.patch("leitura_documento._chamar", return_value=_fixture("leitura_das.json"))
    lido = ld.ler_boleto_das(b"%PDF", "application/pdf")
    assert lido == {
        "valor": 75.9,
        "vencimento": "2026-10-20",
        "competencia": "2026-09-01",
        "cnpj": "12345678000195",
        "nome": "JOSIE DA SILVA 12345678000195",
    }


def test_ler_boleto_das_valor_zero_levanta_leitura_falhou(mocker):
    dados = _fixture("leitura_das.json")
    dados["valor"] = 0
    mocker.patch("leitura_documento._chamar", return_value=dados)
    with pytest.raises(ld.LeituraFalhou):
        ld.ler_boleto_das(b"x", "image/png")


def test_ler_boleto_das_competencia_ilegivel_vira_none(mocker):
    dados = _fixture("leitura_das.json")
    dados["competencia"] = "setembro"
    dados["cnpj"] = "123"
    mocker.patch("leitura_documento._chamar", return_value=dados)
    lido = ld.ler_boleto_das(b"x", "image/png")
    assert lido["competencia"] is None
    assert lido["cnpj"] is None


def test_competencia_ou_none_aceita_os_tres_formatos():
    assert ld._competencia_ou_none("2026-09") == "2026-09-01"
    assert ld._competencia_ou_none("2026-09-15") == "2026-09-01"
    assert ld._competencia_ou_none("09/2026") == "2026-09-01"
    assert ld._competencia_ou_none("13/2026") is None
    assert ld._competencia_ou_none(None) is None


# --- ler_nota_fiscal --------------------------------------------------------

def test_ler_nota_fiscal_sem_competencia_usa_mes_da_emissao_e_marca(mocker):
    mocker.patch("leitura_documento._chamar", return_value=_fixture("leitura_nf.json"))
    lido = ld.ler_nota_fiscal(b"%PDF", "application/pdf")
    assert lido["numero"] == "000000123"
    assert lido["valor"] == 2500.0
    assert lido["data_emissao"] == "2026-09-05"
    assert lido["competencia"] == "2026-09-01"
    assert lido["competencia_inferida"] is True
    assert lido["cnpj_prestador"] == "12345678000195"


def test_ler_nota_fiscal_com_competencia_na_nota_nao_infere(mocker):
    dados = _fixture("leitura_nf.json")
    dados["competencia"] = "08/2026"   # a NF de agosto do Fabrício, emitida em setembro
    mocker.patch("leitura_documento._chamar", return_value=dados)
    lido = ld.ler_nota_fiscal(b"%PDF", "application/pdf")
    assert lido["competencia"] == "2026-08-01"
    assert lido["competencia_inferida"] is False


def test_ler_nota_fiscal_sem_numero_nem_valor_levanta_leitura_falhou(mocker):
    dados = _fixture("leitura_nf.json")
    dados["numero"] = None
    dados["valor"] = None
    mocker.patch("leitura_documento._chamar", return_value=dados)
    with pytest.raises(ld.LeituraFalhou):
        ld.ler_nota_fiscal(b"%PDF", "application/pdf")
