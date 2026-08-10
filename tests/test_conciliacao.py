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


def test_listar_lote(client, admin_headers):
    lote_id = "11111111-0000-0000-0000-000000000001"
    transacao = {
        "id": "22222222-0000-0000-0000-000000000001", "lote_id": lote_id,
        "fitid": "2026080500001", "tipo": "DEBIT", "valor": 450.00,
        "data": "2026-08-05", "descricao": "Pagamento Fornecedor Flavia",
        "status": "pendente", "match_tabela": "fin_contas_pagar",
        "match_id": "33333333-0000-0000-0000-000000000001",
        "criado_por": None, "criado_em": "2026-08-10T10:00:00+00:00",
    }
    match_row = {"descricao": "Conta de luz", "valor": 450.00}

    with patch("routes.conciliacao.db.query", side_effect=[[transacao], [match_row]]):
        resp = client.get(f"/api/conciliacao/lotes/{lote_id}", headers=admin_headers)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body[0]["match_descricao"] == "Conta de luz"


def test_listar_lote_nao_encontrado(client, admin_headers):
    with patch("routes.conciliacao.db.query", return_value=[]):
        resp = client.get("/api/conciliacao/lotes/inexistente", headers=admin_headers)
    assert resp.status_code == 404


def test_confirmar_lote_aplica_acoes(client, admin_headers):
    lote_id = "11111111-0000-0000-0000-000000000001"
    transacao_match = {
        "id": "t1", "match_tabela": "fin_contas_pagar", "match_id": "c1",
        "tipo": "DEBIT", "valor": 450.00, "data": "2026-08-05", "descricao": "Pagamento X",
    }
    transacao_nova = {
        "id": "t2", "match_tabela": None, "match_id": None,
        "tipo": "DEBIT", "valor": 100.00, "data": "2026-08-06", "descricao": "Compra Y",
    }
    transacao_ignorar = {
        "id": "t3", "match_tabela": None, "match_id": None,
        "tipo": "CREDIT", "valor": 50.00, "data": "2026-08-07", "descricao": "Depósito Z",
    }
    mock_transaction, mock_cur = _mock_transaction_cursor(fetchone_results=[], fetchall_results=[])

    with patch("routes.conciliacao.db.query", return_value=[transacao_match, transacao_nova, transacao_ignorar]), \
         patch("routes.conciliacao.db.transaction", mock_transaction):
        resp = client.post(
            f"/api/conciliacao/lotes/{lote_id}/confirmar",
            json={"itens": [
                {"transacao_id": "t1", "acao": "confirmar_match"},
                {"transacao_id": "t2", "acao": "criar_conta"},
                {"transacao_id": "t3", "acao": "ignorar"},
            ]},
            headers=admin_headers,
        )

    assert resp.status_code == 200
    assert resp.get_json()["confirmados"] == 3


def test_confirmar_lote_acao_invalida(client, admin_headers):
    resp = client.post(
        "/api/conciliacao/lotes/lote1/confirmar",
        json={"itens": [{"transacao_id": "t1", "acao": "chutar"}]},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_confirmar_lote_sem_itens(client, admin_headers):
    resp = client.post(
        "/api/conciliacao/lotes/lote1/confirmar",
        json={"itens": []},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_confirmar_lote_negado_para_viewer(client, viewer_headers):
    resp = client.post(
        "/api/conciliacao/lotes/lote1/confirmar",
        json={"itens": [{"transacao_id": "t1", "acao": "ignorar"}]},
        headers=viewer_headers,
    )
    assert resp.status_code == 403
