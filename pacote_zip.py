"""Monta o .zip do mês: uma pasta por compra, com nota, pedido e comprovantes.

A pasta é da COMPRA, não do Pix: a Flávia tem 30 dias de prazo, então o
comprovante de setembro mora na pasta da compra de agosto. Um Pix que pagou duas
compras aparece nas duas pastas — repetir o arquivo custa menos que mandar a
contabilidade procurar.
"""
import io
import zipfile
from datetime import date

import openpyxl

import storage

CABECALHO = ["Fornecedor", "Data da compra", "Nº do pedido", "Valor", "Pago",
             "Pagamentos", "Em aberto", "Tem nota", "Tem comprovante"]


def _dia_mes(iso_data):
    d = date.fromisoformat(str(iso_data)[:10])
    return f"{d.day:02d}-{d.month:02d}"


def _brl(valor):
    inteiro = f"{float(valor):,.2f}"
    return "R$ " + inteiro.replace(",", "·").replace(".", ",").replace("·", ".")


def _pasta(compra):
    numero = compra.get("numero_pedido") or "sem número"
    return f"{compra['fornecedor']}/{_dia_mes(compra['data_compra'])} pedido {numero}"


def _escrever(zf, caminho_no_zip, path_no_storage):
    """Baixa do Storage e escreve. Falha vira bilhete, não exceção."""
    try:
        zf.writestr(caminho_no_zip, storage.baixar(path_no_storage))
    except storage.StorageErro as e:
        nome = caminho_no_zip.rsplit("/", 1)[-1]
        pasta = caminho_no_zip.rsplit("/", 1)[0]
        zf.writestr(f"{pasta}/FALTOU {nome}.txt",
                    f"Não consegui baixar este arquivo do Storage.\nMotivo: {e}\n")


def montar(compras):
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf:
        planilha = openpyxl.Workbook()
        aba = planilha.active
        aba.title = "Compras"
        aba.append(CABECALHO)

        for compra in compras:
            pasta = _pasta(compra)
            # A pasta existe mesmo vazia: a linha do resumo precisa ter um lugar
            # correspondente no zip.
            zf.writestr(f"{pasta}/", b"")

            if compra.get("nf_path"):
                ext = compra["nf_path"].rsplit(".", 1)[-1]
                _escrever(zf, f"{pasta}/nota-fiscal.{ext}", compra["nf_path"])
            if compra.get("pedido_path"):
                ext = compra["pedido_path"].rsplit(".", 1)[-1]
                _escrever(zf, f"{pasta}/pedido.{ext}", compra["pedido_path"])

            pago = 0.0
            datas = []
            for comp in compra.get("comprovantes", []):
                pago += float(comp["valor"])
                datas.append(_dia_mes(comp["data"]))
                if comp.get("path"):
                    ext = comp["path"].rsplit(".", 1)[-1]
                    nome = f"comprovante {_dia_mes(comp['data'])} {_brl(comp['valor'])}.{ext}"
                    _escrever(zf, f"{pasta}/{nome}", comp["path"])

            tem_comprovante = any(c.get("path") for c in compra.get("comprovantes", []))
            aba.append([
                compra["fornecedor"],
                str(compra["data_compra"])[:10],
                compra.get("numero_pedido") or "",
                float(compra["valor"]),
                pago,
                ", ".join(datas),
                float(compra["valor"]) - pago,
                "sim" if compra.get("nf_path") else "não",
                "sim" if tem_comprovante else "não",
            ])

        planilha_bytes = io.BytesIO()
        planilha.save(planilha_bytes)
        zf.writestr("resumo.xlsx", planilha_bytes.getvalue())

    return saida.getvalue()
