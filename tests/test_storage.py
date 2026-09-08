from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import storage


def _resp(status=200, json_data=None):
    r = MagicMock()
    r.status_code = status
    r.ok = status < 400
    r.json.return_value = json_data or {}
    r.text = ""
    return r


def test_enviar_pendente_sobe_para_pasta_pendentes(mocker):
    post = mocker.patch("storage.requests.post", return_value=_resp(200))
    caminho = storage.enviar_pendente(b"%PDF-1.4", "application/pdf")
    assert caminho.startswith("pendentes/") and caminho.endswith(".pdf")
    url = post.call_args.args[0]
    assert url.endswith(f"/storage/v1/object/fornecedores/{caminho}")
    headers = post.call_args.kwargs["headers"]
    assert headers["Content-Type"] == "application/pdf"
    assert headers["Authorization"].startswith("Bearer ")


def test_enviar_pendente_rejeita_mime_desconhecido():
    with pytest.raises(storage.StorageErro):
        storage.enviar_pendente(b"x", "text/plain")


def test_enviar_pendente_erro_http_vira_storage_erro(mocker):
    mocker.patch("storage.requests.post", return_value=_resp(500))
    with pytest.raises(storage.StorageErro):
        storage.enviar_pendente(b"x", "image/png")


def test_mover_chama_endpoint_move(mocker):
    post = mocker.patch("storage.requests.post", return_value=_resp(200))
    storage.mover("pendentes/a.pdf", "f1/pedidos/p1.pdf")
    assert post.call_args.args[0].endswith("/storage/v1/object/move")
    assert post.call_args.kwargs["json"] == {
        "bucketId": "fornecedores",
        "sourceKey": "pendentes/a.pdf",
        "destinationKey": "f1/pedidos/p1.pdf",
    }


def test_url_assinada_monta_url_completa(mocker):
    mocker.patch("storage.requests.post",
                 return_value=_resp(200, {"signedURL": "/object/sign/fornecedores/f1/pedidos/p1.pdf?token=abc"}))
    url = storage.url_assinada("f1/pedidos/p1.pdf")
    assert url.endswith("/storage/v1/object/sign/fornecedores/f1/pedidos/p1.pdf?token=abc")


def test_limpar_pendentes_apaga_so_os_velhos(mocker):
    agora = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    velho = (agora - timedelta(hours=30)).isoformat()
    novo = (agora - timedelta(hours=2)).isoformat()
    post = mocker.patch("storage.requests.post", return_value=_resp(200, [
        {"name": "velho.pdf", "created_at": velho},
        {"name": "novo.pdf", "created_at": novo},
    ]))
    delete = mocker.patch("storage.requests.delete", return_value=_resp(200))
    apagados = storage.limpar_pendentes(agora=agora)
    assert apagados == 1
    assert post.call_args.args[0].endswith("/storage/v1/object/list/fornecedores")
    assert delete.call_args.kwargs["json"] == {"prefixes": ["pendentes/velho.pdf"]}


def test_limpar_pendentes_sem_velhos_nao_chama_delete(mocker):
    agora = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    mocker.patch("storage.requests.post", return_value=_resp(200, [
        {"name": "novo.pdf", "created_at": (agora - timedelta(hours=1)).isoformat()},
    ]))
    delete = mocker.patch("storage.requests.delete")
    assert storage.limpar_pendentes(agora=agora) == 0
    delete.assert_not_called()
