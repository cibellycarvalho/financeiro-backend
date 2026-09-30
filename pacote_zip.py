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
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import openpyxl

import storage

CABECALHO = ["Fornecedor", "Data (compra ou vencimento)", "Nº do pedido", "Valor", "Pago",
             "Pagamentos", "Em aberto", "Marcada como paga", "Tem nota", "Tem comprovante",
             "Origem", "Categoria"]

# Poucos workers de propósito: o gargalo é a latência do Storage, não a CPU,
# e o serviço roda com 2 workers de gunicorn — abrir dezenas de conexões por
# download faria o mês grande competir consigo mesmo.
BAIXAR_EM_PARALELO = 6

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


def _baixar_tudo(paths):
    """Baixa os arquivos do Storage em paralelo e devolve {path: bytes|erro}.

    Fix round 3 (CRITICAL 3): um mês real tem ~90 arquivos; em série isso
    passa do timeout do gunicorn e o worker morre sem mensagem na tela. O
    paralelismo é só de rede — o zip continua sendo escrito numa thread só,
    porque zipfile não é thread-safe.

    Falha de um arquivo vira o erro guardado no dicionário (vira bilhete
    FALTOU na hora de escrever), nunca uma exceção que derrube o zip.
    """
    unicos = list(dict.fromkeys(p for p in paths if p))
    if not unicos:
        return {}

    def _um(path):
        try:
            return storage.baixar(path)
        except storage.StorageErro as e:
            return e
        except Exception as e:   # rede/driver: vira bilhete, não 500
            return storage.StorageErro(str(e))

    with ThreadPoolExecutor(max_workers=min(BAIXAR_EM_PARALELO, len(unicos))) as executor:
        return dict(zip(unicos, executor.map(_um, unicos)))


def _escrever(zf, caminho_no_zip, path_no_storage, baixados):
    """Escreve o que já foi baixado. Devolve True se o arquivo entrou mesmo.

    Fix round 3 (IMPORTANT 1): quem chama precisa saber que virou bilhete,
    senão o resumo diz "tem nota: sim" para um arquivo que não está no zip —
    e é pelo resumo que ela vê o que falta antes de mandar.
    """
    conteudo = baixados.get(path_no_storage,
                            storage.StorageErro("arquivo não foi baixado"))
    if isinstance(conteudo, Exception):
        nome = caminho_no_zip.rsplit("/", 1)[-1]
        pasta = caminho_no_zip.rsplit("/", 1)[0]
        zf.writestr(f"{pasta}/FALTOU {nome}.txt",
                    f"Não consegui baixar este arquivo do Storage.\nMotivo: {conteudo}\n")
        return False
    zf.writestr(caminho_no_zip, conteudo)
    return True


def _escrever_pasta_vazia(zf, pasta):
    """Marca a entrada como diretório de verdade (bit no external_attr).

    Sem isso, o zipfile grava uma entrada de 0 byte que alguns extratores
    mostram como arquivo em vez de pasta.
    """
    info = zipfile.ZipInfo(f"{pasta}/")
    info.external_attr = 0o40755 << 16
    zf.writestr(info, b"")


def _marca(tem, baixou):
    """"sim", "não" ou "sim (faltou baixar)" — o arquivo existe no banco mas
    não entrou no zip, então o lugar dele tem um bilhete FALTOU."""
    if not tem:
        return "não"
    return "sim" if baixou else "sim (faltou baixar)"


def _pastas(compras):
    """Decide a pasta de cada compra, desempatando as que colidem."""
    usadas = {}
    saida = []
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
        saida.append((pasta, compra))
    return saida


def montar(compras):
    planejadas = _pastas(compras)

    # Tudo que precisa vir do Storage, de uma vez: um comprovante que pagou
    # duas compras é baixado uma vez só e escrito nas duas pastas.
    paths = []
    for _pasta, compra in planejadas:
        paths.append(compra.get("nf_path"))
        paths.append(compra.get("pedido_path"))
        for comp in (compra.get("comprovantes") or []):
            paths.append(comp.get("path"))
    baixados = _baixar_tudo(paths)

    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf:
        planilha = openpyxl.Workbook()
        aba = planilha.active
        aba.title = "Compras"
        aba.append(CABECALHO)

        for pasta, compra in planejadas:
            # A pasta existe mesmo vazia: a linha do resumo precisa ter um lugar
            # correspondente no zip.
            _escrever_pasta_vazia(zf, pasta)

            nota_ok = True
            if compra.get("nf_path"):
                nota_ok = _escrever(zf, f"{pasta}/nota-fiscal.{_ext(compra['nf_path'])}",
                                    compra["nf_path"], baixados)
            if compra.get("pedido_path"):
                _escrever(zf, f"{pasta}/pedido.{_ext(compra['pedido_path'])}",
                          compra["pedido_path"], baixados)

            comprovantes = compra.get("comprovantes") or []
            pago = 0.0
            datas = []
            comprovante_ok = True
            for comp in comprovantes:
                pago += float(comp["valor"])
                datas.append(_dia_mes(comp["data"]))
                if comp.get("path"):
                    nome = f"comprovante {_dia_mes(comp['data'])} {_brl(comp['valor'])}.{_ext(comp['path'])}"
                    if not _escrever(zf, f"{pasta}/{_sanitizar(nome)}", comp["path"], baixados):
                        comprovante_ok = False

            tem_comprovante = any(c.get("path") for c in comprovantes)

            # Fix round 3 (CRITICAL 2b): "Pago" é a soma dos links, e só.
            # Antes, a compra com `pago_em` e sem link entrava como paga no
            # resumo — e a mesma quantia aparecia de novo na compra que
            # recebeu o link daquele Pix, contando o dinheiro duas vezes. A
            # marcação manual passa a ser uma coluna à parte: é o que o banco
            # diz que é, uma baixa sem pagamento amarrado.
            marcada_paga = bool(compra.get("pago_em") or compra.get("pago"))

            aba.append([
                compra["fornecedor"],
                str(compra["data_compra"])[:10],
                compra.get("numero_pedido") or "",
                round(float(compra["valor"]), 2),
                round(pago, 2),
                ", ".join(datas),
                round(float(compra["valor"]) - pago, 2),
                "sim" if marcada_paga else "não",
                _marca(compra.get("nf_path"), nota_ok),
                _marca(tem_comprovante, comprovante_ok),
                compra.get("origem") or "pedido",
                compra.get("categoria") or "",
            ])

        planilha_bytes = io.BytesIO()
        planilha.save(planilha_bytes)
        zf.writestr("resumo.xlsx", planilha_bytes.getvalue())

    return saida.getvalue()
