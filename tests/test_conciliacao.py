import io
import os
from datetime import date
from unittest.mock import patch, MagicMock

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "extrato_exemplo.ofx")


def _mock_transaction_cursor(fetchone_results, fetchall_results):
    mock_cur = MagicMock()
    mock_cur.fetchone.side_effect = fetchone_results
    mock_cur.fetchall.side_effect = fetchall_results
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_cur
    mock_ctx.__exit__.return_value = False
    mock_transaction = MagicMock(return_value=mock_ctx)
    return mock_transaction, mock_cur


def test_importar_casa_credito_e_cria_pendencia_para_debito(client, admin_headers):
    fixture_bytes = open(FIXTURE_PATH, "rb").read()
    match_repasse = {"id": "r1", "data": date(2026, 8, 6), "descricao": "Repasse ML Agosto"}

    mock_transaction, mock_cur = _mock_transaction_cursor(
        fetchone_results=[None, None],
        fetchall_results=[[], [], [match_repasse]],
    )

    with patch("routes.conciliacao.db.transaction", mock_transaction):
        resp = client.post(
            "/api/conciliacao/importar",
            data={"arquivo": (io.BytesIO(fixture_bytes), "extrato.ofx")},
            content_type="multipart/form-data",
            headers=admin_headers,
        )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["total"] == 2
    assert body["duplicadas"] == 0
    assert body["casadas"] == 1
    assert body["novas"] == 1
    assert body["sem_match"] == 0
    assert body["lote_id"] is not None


def test_importar_todas_duplicadas_retorna_lote_id_none(client, admin_headers):
    fixture_bytes = open(FIXTURE_PATH, "rb").read()
    mock_transaction, mock_cur = _mock_transaction_cursor(
        fetchone_results=[{"id": "existing1"}, {"id": "existing2"}],
        fetchall_results=[],
    )

    with patch("routes.conciliacao.db.transaction", mock_transaction):
        resp = client.post(
            "/api/conciliacao/importar",
            data={"arquivo": (io.BytesIO(fixture_bytes), "extrato.ofx")},
            content_type="multipart/form-data",
            headers=admin_headers,
        )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["lote_id"] is None
    assert body["duplicadas"] == 2


def test_importar_sem_arquivo_retorna_400(client, admin_headers):
    resp = client.post("/api/conciliacao/importar", headers=admin_headers)
    assert resp.status_code == 400


def test_importar_negado_para_viewer(client, viewer_headers):
    fixture_bytes = open(FIXTURE_PATH, "rb").read()
    resp = client.post(
        "/api/conciliacao/importar",
        data={"arquivo": (io.BytesIO(fixture_bytes), "extrato.ofx")},
        content_type="multipart/form-data",
        headers=viewer_headers,
    )
    assert resp.status_code == 403
