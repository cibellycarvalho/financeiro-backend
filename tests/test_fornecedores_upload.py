import io

import pytest

import leitura_documento as ld
import storage

FORN = "11111111-1111-1111-1111-111111111111"
OUTRO = "22222222-2222-2222-2222-222222222222"

LIDO_PEDIDO = {
    "texto_vendedor": "Flavia",
    "numero_pedido": "2026/9001",
    "data_pedido": "2026-09-01",
    "itens": [{"produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10.0}],
    "total_documento": 20.0,
}


def _arquivo(nome="pedido.pdf", mime="application/pdf", conteudo=b"%PDF-1.4 fake"):
    return {"arquivo": (io.BytesIO(conteudo), nome, mime)}


@pytest.fixture(autouse=True)
def storage_mock(mocker):
    mocker.patch("routes.fornecedores.storage.limpar_pendentes", return_value=0)
    mocker.patch("routes.fornecedores.storage.enviar_pendente", return_value="pendentes/abc.pdf")


# --- POST /pedidos/ler ------------------------------------------------------

def test_ler_pedido_devolve_rascunho_com_sugestao_e_token(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", return_value=LIDO_PEDIDO)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=OUTRO)
    mocker.patch("routes.fornecedores.db.query", return_value=[])

    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["leitura_falhou"] is False
    assert corpo["fornecedor_sugerido_id"] == OUTRO
    assert corpo["texto_vendedor"] == "Flavia"
    assert corpo["numero_pedido"] == "2026/9001"
    assert corpo["itens"] == LIDO_PEDIDO["itens"]
    assert corpo["total_documento"] == 20.0
    assert corpo["pedido_existente"] is None
    assert corpo["arquivo_token"] == "pendentes/abc.pdf"


def test_ler_pedido_avisa_pedido_existente_no_mesmo_fornecedor(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", return_value=LIDO_PEDIDO)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=None)
    query = mocker.patch("routes.fornecedores.db.query",
                         return_value=[{"id": "p-1", "data_pedido": "2026-09-01"}])

    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.get_json()["pedido_existente"] == {"id": "p-1", "data_pedido": "2026-09-01"}
    assert query.call_args.args[1] == (FORN, "2026/9001")


def test_ler_pedido_leitura_falhou_devolve_token_e_flag(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", side_effect=ld.LeituraFalhou("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["leitura_falhou"] is True
    assert corpo["arquivo_token"] == "pendentes/abc.pdf"
    assert corpo["itens"] == []


def test_ler_pedido_api_indisponivel_503(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", side_effect=ld.LeituraIndisponivel("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 503
    assert "Lance à mão" in r.get_json()["error"]


def test_ler_pedido_sem_arquivo_400(client, admin_headers):
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data={},
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 400


def test_ler_pedido_tipo_nao_aceito_400(client, admin_headers, mocker):
    ler = mocker.patch("routes.fornecedores.leitura_documento.ler_pedido")
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler",
                    data=_arquivo("x.txt", "text/plain", b"oi"),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 400
    ler.assert_not_called()


def test_ler_pedido_maior_que_10mb_400(client, admin_headers, mocker):
    ler = mocker.patch("routes.fornecedores.leitura_documento.ler_pedido")
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler",
                    data=_arquivo(conteudo=b"x" * (10 * 1024 * 1024 + 1)),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 400
    ler.assert_not_called()


def test_ler_pedido_viewer_403(client, viewer_headers):
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=viewer_headers, content_type="multipart/form-data")
    assert r.status_code == 403


def test_ler_pedido_storage_falhou_no_envio_500_com_mensagem(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", return_value=LIDO_PEDIDO)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=None)
    mocker.patch("routes.fornecedores.db.query", return_value=[])
    mocker.patch("routes.fornecedores.storage.enviar_pendente", side_effect=storage.StorageErro("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 500
    assert "arquivo" in r.get_json()["error"].lower()


LIDO_COMPROVANTE = {
    "valor": 30000.0,
    "data_pagamento": "2026-08-24",
    "destinatario": "MIAO ATACADISTA E REPRESENTACOES LTDA",
    "id_transacao": "E8109949120260824004025qquKDYh56",
}


# --- POST /pagamentos/ler ---------------------------------------------------

def test_ler_comprovante_devolve_rascunho(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_comprovante", return_value=LIDO_COMPROVANTE)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=FORN)
    mocker.patch("routes.fornecedores.db.query", return_value=[])

    r = client.post(f"/api/fornecedores/{FORN}/pagamentos/ler", data=_arquivo("pix.png", "image/png", b"\x89PNG"),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["leitura_falhou"] is False
    assert corpo["valor"] == 30000.0
    assert corpo["data_pagamento"] == "2026-08-24"
    assert corpo["destinatario"] == LIDO_COMPROVANTE["destinatario"]
    assert corpo["id_transacao"] == LIDO_COMPROVANTE["id_transacao"]
    assert corpo["fornecedor_sugerido_id"] == FORN
    assert corpo["pagamento_existente"] is None
    assert corpo["arquivo_token"] == "pendentes/abc.pdf"


def test_ler_comprovante_avisa_e2e_ja_lancado(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_comprovante", return_value=LIDO_COMPROVANTE)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=None)
    query = mocker.patch("routes.fornecedores.db.query",
                         return_value=[{"id": "pg-1", "data_pagamento": "2026-08-24", "valor": 30000.0}])
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.get_json()["pagamento_existente"] == {"id": "pg-1", "data_pagamento": "2026-08-24", "valor": 30000.0}
    assert query.call_args.args[1] == (LIDO_COMPROVANTE["id_transacao"],)


def test_ler_comprovante_leitura_falhou_devolve_token(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_comprovante", side_effect=ld.LeituraFalhou("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["leitura_falhou"] is True
    assert r.get_json()["arquivo_token"] == "pendentes/abc.pdf"


def test_ler_comprovante_api_indisponivel_503(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_comprovante", side_effect=ld.LeituraIndisponivel("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 503
