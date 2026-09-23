"""Monta o .zip do mês: uma pasta por compra, com nota, pedido e comprovantes.

A pasta é da COMPRA, não do Pix: a Flávia tem 30 dias de prazo, então o
comprovante de setembro mora na pasta da compra de agosto. Um Pix que pagou duas
compras aparece nas duas pastas — repetir o arquivo custa menos que mandar a
contabilidade procurar.

Nomes de pasta/arquivo vêm de texto livre do banco (número do pedido, apelido
do fornecedor, descrição da conta a pagar) e não podem entrar crus no caminho
do zip: viram nível de pasta extra, caractere ilegal no Windows ou, no pior
caso, um zip slip com "..". Tudo passa por `_sanitizar` antes.
"""
import io
import re
import zipfile
from datetime import date

import openpyxl

import storage

CABECALHO = ["Fornecedor", "Data (compra ou vencimento)", "Nº do pedido", "Valor", "Pago",
             "Pagamentos", "Em aberto", "Tem nota", "Tem comprovante", "Origem"]

EXTENSOES_ACEITAS = {"pdf", "jpg", "jpeg", "png"}
_CARACTERES_ILEGAIS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _sanitizar(texto):
    """Deixa um texto livre seguro para virar nome de pasta/arquivo no zip.

    Troca caracteres ilegais no Windows (e de controle) por "-", colapsa
    espaços, recusa "." e ".." (zip slip / pasta invisível) e corta em 60
    caracteres.
    """
    texto = _CARACTERES_ILEGAIS.sub("-", str(texto))
    texto = re.sub(r"\s+", " ", texto).strip()
    if texto in ("", ".", ".."):
        texto = "-"
    return texto[:60]


def _dia_mes(iso_data):
    d = date.fromisoformat(str(iso_data)[:10])
    return f"{d.day:02d}-{d.month:02d}"


def _brl(valor):
    inteiro = f"{float(valor):,.2f}"
    return "R$ " + inteiro.replace(",", "·").replace(".", ",").replace("·", ".")


def _ext(path):
    """Extensão do arquivo, restrita à lista aceita — senão "bin"."""
    if not path:
        return "bin"
    nome = path.rsplit("/", 1)[-1]
    if "." not in nome:
        return "bin"
    ext = nome.rsplit(".", 1)[-1].lower()
    return ext if ext in EXTENSOES_ACEITAS else "bin"


def _pasta_base(compra):
    numero = _sanitizar(compra.get("numero_pedido") or "sem número")
    fornecedor = _sanitizar(compra["fornecedor"])
    return f"{fornecedor}/{_dia_mes(compra['data_compra'])} pedido {numero}"


def _escrever(zf, caminho_no_zip, path_no_storage):
    """Baixa do Storage e escreve. Falha vira bilhete, não exceção."""
    try:
        zf.writestr(caminho_no_zip, storage.baixar(path_no_storage))
    except storage.StorageErro as e:
        nome = caminho_no_zip.rsplit("/", 1)[-1]
        pasta = caminho_no_zip.rsplit("/", 1)[0]
        zf.writestr(f"{pasta}/FALTOU {nome}.txt",
                    f"Não consegui baixar este arquivo do Storage.\nMotivo: {e}\n")


def _escrever_pasta_vazia(zf, pasta):
    """Marca a entrada como diretório de verdade (bit no external_attr).

    Sem isso, o zipfile grava uma entrada de 0 byte que alguns extratores
    mostram como arquivo em vez de pasta.
    """
    info = zipfile.ZipInfo(f"{pasta}/")
    info.external_attr = 0o40755 << 16
    zf.writestr(info, b"")


def montar(compras):
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf:
        planilha = openpyxl.Workbook()
        aba = planilha.active
        aba.title = "Compras"
        aba.append(CABECALHO)

        usadas = {}
        for compra in compras:
            pasta_base = _pasta_base(compra)
            # Duas compras do mesmo fornecedor, mesmo dia, sem número geram a
            # mesma pasta_base — sem desempate, o zipfile só avisa (UserWarning)
            # e o extrator fica com a última, perdendo a outra em silêncio.
            if pasta_base in usadas:
                usadas[pasta_base] += 1
                sufixo = (str(compra.get("id") or "")[:6]) or str(usadas[pasta_base])
                pasta = f"{pasta_base} ({sufixo})"
            else:
                usadas[pasta_base] = 1
                pasta = pasta_base

            # A pasta existe mesmo vazia: a linha do resumo precisa ter um lugar
            # correspondente no zip.
            _escrever_pasta_vazia(zf, pasta)

            if compra.get("nf_path"):
                _escrever(zf, f"{pasta}/nota-fiscal.{_ext(compra['nf_path'])}", compra["nf_path"])
            if compra.get("pedido_path"):
                _escrever(zf, f"{pasta}/pedido.{_ext(compra['pedido_path'])}", compra["pedido_path"])

            comprovantes = compra.get("comprovantes") or []
            pago = 0.0
            datas = []
            for comp in comprovantes:
                pago += float(comp["valor"])
                datas.append(_dia_mes(comp["data"]))
                if comp.get("path"):
                    nome = f"comprovante {_dia_mes(comp['data'])} {_brl(comp['valor'])}.{_ext(comp['path'])}"
                    _escrever(zf, f"{pasta}/{_sanitizar(nome)}", comp["path"])

            tem_comprovante = any(c.get("path") for c in comprovantes)

            # Compra dada como paga sem amarração de Pix: pedido com
            # `pago_em` preenchido, ou conta a pagar com status='pago' —
            # nenhum dos dois tem arquivo de comprovante, mas a dívida não
            # existe mais. "Tem comprovante" continua "não": não existe
            # arquivo, só a baixa manual.
            if not comprovantes and (compra.get("pago_em") or compra.get("pago")):
                pago = float(compra["valor"])

            aba.append([
                compra["fornecedor"],
                str(compra["data_compra"])[:10],
                compra.get("numero_pedido") or "",
                round(float(compra["valor"]), 2),
                round(pago, 2),
                ", ".join(datas),
                round(float(compra["valor"]) - pago, 2),
                "sim" if compra.get("nf_path") else "não",
                "sim" if tem_comprovante else "não",
                compra.get("origem") or "pedido",
            ])

        planilha_bytes = io.BytesIO()
        planilha.save(planilha_bytes)
        zf.writestr("resumo.xlsx", planilha_bytes.getvalue())

    return saida.getvalue()
