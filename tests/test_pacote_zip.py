import io
import zipfile
from unittest.mock import patch

import pacote_zip

COMPRA = {
    "fornecedor": "FLAVIA",
    "data_compra": "2026-08-17",
    "numero_pedido": "1234",
    "valor": 30000.0,
    "nf_path": "forn/notas/ped-1.pdf",
    "pedido_path": "forn/pedidos/ped-1.pdf",
    "comprovantes": [
        {"path": "forn/pagamentos/pg-1.pdf", "data": "2026-09-22", "valor": 30000.0},
    ],
}


def _nomes(zbytes):
    return zipfile.ZipFile(io.BytesIO(zbytes)).namelist()


def test_pasta_e_da_compra_mesmo_com_pix_do_mes_seguinte():
    with patch("storage.baixar", return_value=b"%PDF"):
        nomes = _nomes(pacote_zip.montar([COMPRA]))
    assert "FLAVIA/17-08 pedido 1234/nota-fiscal.pdf" in nomes
    assert "FLAVIA/17-08 pedido 1234/pedido.pdf" in nomes
    assert "FLAVIA/17-08 pedido 1234/comprovante 22-09 R$ 30.000,00.pdf" in nomes


def test_mesmo_comprovante_aparece_nas_duas_compras():
    a = dict(COMPRA, numero_pedido="10", valor=30000.0)
    b = dict(COMPRA, numero_pedido="11", valor=19310.0, nf_path=None, pedido_path=None,
             comprovantes=[{"path": "forn/pagamentos/pg-1.pdf", "data": "2026-09-22", "valor": 19310.0}])
    with patch("storage.baixar", return_value=b"%PDF"):
        nomes = _nomes(pacote_zip.montar([a, b]))
    assert "FLAVIA/17-08 pedido 10/comprovante 22-09 R$ 30.000,00.pdf" in nomes
    assert "FLAVIA/17-08 pedido 11/comprovante 22-09 R$ 19.310,00.pdf" in nomes


def test_arquivo_que_falha_vira_bilhete_em_vez_de_derrubar_o_zip():
    import storage as st
    with patch("storage.baixar", side_effect=st.StorageErro("sumiu")):
        conteudo = pacote_zip.montar([COMPRA])
    nomes = _nomes(conteudo)
    assert any(n.startswith("FLAVIA/17-08 pedido 1234/FALTOU") for n in nomes)


def test_compra_sem_arquivo_nenhum_ainda_tem_pasta_e_linha_no_resumo():
    vazia = dict(COMPRA, nf_path=None, pedido_path=None, comprovantes=[])
    conteudo = pacote_zip.montar([vazia])
    nomes = _nomes(conteudo)
    assert any(n.startswith("FLAVIA/17-08 pedido 1234/") for n in nomes)
    assert "resumo.xlsx" in nomes


def test_resumo_marca_o_que_falta():
    vazia = dict(COMPRA, nf_path=None, comprovantes=[])
    import openpyxl
    conteudo = pacote_zip.montar([vazia])
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        planilha = openpyxl.load_workbook(io.BytesIO(z.read("resumo.xlsx")))
    linhas = list(planilha.active.values)
    assert linhas[0][0] == "Fornecedor"
    assert "não" in linhas[1]    # tem nota = não


def test_rota_devolve_zip(client, admin_headers):
    linhas = [{
        "fornecedor": "FLAVIA", "data_compra": "2026-08-17", "numero_pedido": "1234",
        "valor": 30000.0, "nf_path": None, "pedido_path": None, "comprovantes": [],
    }]
    with patch("routes.pacote._compras_do_mes", return_value=linhas):
        resp = client.get("/api/pacote/compras/2026-08", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert "compras-2026-08.zip" in resp.headers["Content-Disposition"]


def test_mes_sem_compra_avisa_em_vez_de_zip_vazio(client, admin_headers):
    with patch("routes.pacote._compras_do_mes", return_value=[]):
        resp = client.get("/api/pacote/compras/2026-08", headers=admin_headers)
    assert resp.status_code == 404
    assert "Nenhuma compra" in resp.get_json()["error"]


def test_mes_em_formato_errado_da_400(client, admin_headers):
    resp = client.get("/api/pacote/compras/agosto", headers=admin_headers)
    assert resp.status_code == 400
