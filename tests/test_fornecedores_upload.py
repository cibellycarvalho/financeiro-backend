import io
from contextlib import contextmanager
from unittest.mock import MagicMock

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


def _transacao_fake(mocker, retornos):
    """db.transaction() cujo cursor devolve `retornos` em sequência no fetchone()."""
    cur = MagicMock()
    cur.fetchone.side_effect = retornos

    @contextmanager
    def _tx():
        yield cur

    mocker.patch("routes.fornecedores.db.transaction", _tx)
    return cur


PEDIDO_NOVO = {"id": "p-9", "fornecedor_id": FORN, "data_pedido": "2026-09-01", "valor_total": 20.0}
ITEM_NOVO = {"id": "i-1", "pedido_id": "p-9", "produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10.0}
TOKEN = "pendentes/" + "0" * 32 + ".pdf"


# --- POST /pedidos com campos novos ----------------------------------------

def test_criar_pedido_grava_numero_move_anexo_e_aprende_alias(client, admin_headers, mocker):
    cur = _transacao_fake(mocker, [PEDIDO_NOVO, ITEM_NOVO])
    mover = mocker.patch("routes.fornecedores.storage.mover")
    aprender = mocker.patch("routes.fornecedores.aliases.aprender_alias")

    r = client.post(f"/api/fornecedores/{FORN}/pedidos", json={
        "data_pedido": "2026-09-01",
        "itens": [{"produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10}],
        "numero_pedido": "2026/9001",
        "arquivo_token": TOKEN,
        "alias_vendedor": "Flavia",
    }, headers=admin_headers)
    assert r.status_code == 201

    insert_sql, insert_params = cur.execute.call_args_list[0].args
    assert "numero_pedido" in insert_sql
    assert "2026/9001" in insert_params

    mover.assert_called_once_with(TOKEN, f"{FORN}/pedidos/p-9.pdf")
    update_sql, update_params = cur.execute.call_args_list[-1].args
    assert "arquivo_path" in update_sql
    assert update_params == (f"{FORN}/pedidos/p-9.pdf", "p-9")

    aprender.assert_called_once_with(FORN, "Flavia", "vendedor")
    assert r.get_json()["arquivo_path"] == f"{FORN}/pedidos/p-9.pdf"


def test_criar_pedido_sem_campos_novos_continua_igual(client, admin_headers, mocker):
    cur = _transacao_fake(mocker, [PEDIDO_NOVO, ITEM_NOVO])
    mover = mocker.patch("routes.fornecedores.storage.mover")
    aprender = mocker.patch("routes.fornecedores.aliases.aprender_alias")
    r = client.post(f"/api/fornecedores/{FORN}/pedidos", json={
        "data_pedido": "2026-09-01",
        "itens": [{"produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10}],
    }, headers=admin_headers)
    assert r.status_code == 201
    mover.assert_not_called()
    aprender.assert_not_called()


def test_criar_pedido_storage_falhou_nao_grava(client, admin_headers, mocker):
    _transacao_fake(mocker, [PEDIDO_NOVO, ITEM_NOVO])
    mocker.patch("routes.fornecedores.storage.mover", side_effect=storage.StorageErro("x"))
    aprender = mocker.patch("routes.fornecedores.aliases.aprender_alias")
    r = client.post(f"/api/fornecedores/{FORN}/pedidos", json={
        "data_pedido": "2026-09-01",
        "itens": [{"produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10}],
        "arquivo_token": TOKEN,
    }, headers=admin_headers)
    assert r.status_code == 500
    assert "anexo" in r.get_json()["error"].lower()
    aprender.assert_not_called()


def test_criar_pedido_arquivo_token_forjado_400(client, admin_headers, mocker):
    transacao = mocker.patch("routes.fornecedores.db.transaction")
    mover = mocker.patch("routes.fornecedores.storage.mover")
    r = client.post(f"/api/fornecedores/{FORN}/pedidos", json={
        "data_pedido": "2026-09-01",
        "itens": [{"produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10}],
        "arquivo_token": f"{OUTRO}/pagamentos/abc.pdf",
    }, headers=admin_headers)
    assert r.status_code == 400
    assert "arquivo_token" in r.get_json()["error"]
    transacao.assert_not_called()
    mover.assert_not_called()


def test_destino_anexo_rejeita_token_fora_de_pendentes():
    from routes.fornecedores import _destino_anexo
    with pytest.raises(ValueError):
        _destino_anexo(FORN, "pedidos", "p-9", "pendentes/../outro.pdf")
    with pytest.raises(ValueError):
        _destino_anexo(FORN, "pedidos", "p-9", "pendentes/abc.pdf")  # hex curto demais
    assert _destino_anexo(FORN, "pedidos", "p-9", "pendentes/" + "a" * 32 + ".png") == f"{FORN}/pedidos/p-9.png"


# --- POST /pagamentos com campos novos -------------------------------------

PAGAMENTO_NOVO = {"id": "pg-9", "fornecedor_id": FORN, "valor": 30000.0, "data_pagamento": "2026-08-24"}


def _saldo(mocker, valor):
    mocker.patch("routes.fornecedores._saldo_aberto_fornecedor", return_value=valor)


def test_registrar_pagamento_grava_e2e_move_anexo_e_aprende_alias(client, admin_headers, mocker):
    _saldo(mocker, 100000.0)
    query = mocker.patch("routes.fornecedores.db.query")
    # 1ª: fornecedor existe; 2ª: nenhum pagamento com esse E2E
    query.side_effect = [[{"id": FORN}], []]
    execute = mocker.patch("routes.fornecedores.db.execute")
    execute.side_effect = [dict(PAGAMENTO_NOVO), {**PAGAMENTO_NOVO, "arquivo_path": f"{FORN}/pagamentos/pg-9.pdf"}]
    mover = mocker.patch("routes.fornecedores.storage.mover")
    aprender = mocker.patch("routes.fornecedores.aliases.aprender_alias")

    r = client.post(f"/api/fornecedores/{FORN}/pagamentos", json={
        "valor": 30000, "data_pagamento": "2026-08-24",
        "id_transacao": "E8109949120260824004025qquKDYh56",
        "arquivo_token": TOKEN,
        "alias_destinatario": "MIAO ATACADISTA E REPRESENTACOES LTDA",
    }, headers=admin_headers)
    assert r.status_code == 201
    insert_sql, insert_params = execute.call_args_list[0].args
    assert "id_transacao" in insert_sql
    assert "E8109949120260824004025qquKDYh56" in insert_params
    mover.assert_called_once_with(TOKEN, f"{FORN}/pagamentos/pg-9.pdf")
    aprender.assert_called_once_with(FORN, "MIAO ATACADISTA E REPRESENTACOES LTDA", "destinatario")
    assert r.get_json()["arquivo_path"] == f"{FORN}/pagamentos/pg-9.pdf"


def test_registrar_pagamento_e2e_repetido_409(client, admin_headers, mocker):
    _saldo(mocker, 100000.0)
    query = mocker.patch("routes.fornecedores.db.query")
    query.side_effect = [[{"id": FORN}], [{"id": "pg-1", "data_pagamento": "2026-08-24", "valor": 30000.0}]]
    execute = mocker.patch("routes.fornecedores.db.execute")
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos", json={
        "valor": 30000, "data_pagamento": "2026-08-24",
        "id_transacao": "E8109949120260824004025qquKDYh56",
    }, headers=admin_headers)
    assert r.status_code == 409
    assert "já foi lançado" in r.get_json()["error"]
    execute.assert_not_called()


def test_registrar_pagamento_sem_campos_novos_continua_igual(client, admin_headers, mocker):
    _saldo(mocker, 100000.0)
    mocker.patch("routes.fornecedores.db.query", return_value=[{"id": FORN}])
    mocker.patch("routes.fornecedores.db.execute", return_value=dict(PAGAMENTO_NOVO))
    mover = mocker.patch("routes.fornecedores.storage.mover")
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos",
                    json={"valor": 30000, "data_pagamento": "2026-08-24"}, headers=admin_headers)
    assert r.status_code == 201
    mover.assert_not_called()


def test_registrar_pagamento_arquivo_token_forjado_400(client, admin_headers, mocker):
    _saldo(mocker, 100000.0)
    query = mocker.patch("routes.fornecedores.db.query", return_value=[{"id": FORN}])
    execute = mocker.patch("routes.fornecedores.db.execute")
    mover = mocker.patch("routes.fornecedores.storage.mover")
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos", json={
        "valor": 30000, "data_pagamento": "2026-08-24",
        "arquivo_token": f"{OUTRO}/pagamentos/abc.pdf",
    }, headers=admin_headers)
    assert r.status_code == 400
    assert "arquivo_token" in r.get_json()["error"]
    execute.assert_not_called()
    mover.assert_not_called()


# --- GET .../anexo ----------------------------------------------------------

def test_anexo_pedido_devolve_url_assinada(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.db.query", return_value=[{"arquivo_path": f"{FORN}/pedidos/p-1.pdf"}])
    mocker.patch("routes.fornecedores.storage.url_assinada", return_value="https://x/assinada")
    r = client.get(f"/api/fornecedores/{FORN}/pedidos/p-1/anexo", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json() == {"url": "https://x/assinada"}


def test_anexo_pedido_sem_arquivo_404(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.db.query", return_value=[{"arquivo_path": None}])
    r = client.get(f"/api/fornecedores/{FORN}/pedidos/p-1/anexo", headers=admin_headers)
    assert r.status_code == 404


def test_anexo_pagamento_devolve_url_assinada(client, admin_headers, mocker):
    query = mocker.patch("routes.fornecedores.db.query", return_value=[{"arquivo_path": f"{FORN}/pagamentos/pg-1.png"}])
    mocker.patch("routes.fornecedores.storage.url_assinada", return_value="https://x/assinada2")
    r = client.get(f"/api/fornecedores/{FORN}/pagamentos/pg-1/anexo", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json() == {"url": "https://x/assinada2"}
    assert "fin_pagamentos_fornecedor" in query.call_args.args[0]


def test_anexo_viewer_pode_ver(client, viewer_headers, mocker):
    mocker.patch("routes.fornecedores.db.query", return_value=[{"arquivo_path": f"{FORN}/pedidos/p-1.pdf"}])
    mocker.patch("routes.fornecedores.storage.url_assinada", return_value="https://x/assinada")
    r = client.get(f"/api/fornecedores/{FORN}/pedidos/p-1/anexo", headers=viewer_headers)
    assert r.status_code == 200
