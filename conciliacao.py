"""Conciliação bancária por extrato OFX (27/10/2026).

Funções puras: ler o OFX e sugerir com o que cada movimento casa. A rota em
routes/bancos.py busca os candidatos no banco e grava o resultado.

Qualquer banco exporta OFX (Itaú, Sicredi, Nubank...) — por isso o formato,
e não a API de um banco: o sistema não pode ficar preso a um banco só.
"""
import re
from datetime import date, timedelta

_TRN = re.compile(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", re.S | re.I)


def _tag(bloco, nome):
    m = re.search(rf"<{nome}>([^<\r\n]*)", bloco, re.I)
    return m.group(1).strip() if m else None


def _data(texto):
    if not texto or len(texto) < 8 or not texto[:8].isdigit():
        return None
    return date(int(texto[:4]), int(texto[4:6]), int(texto[6:8]))


def _valor(texto):
    if texto is None:
        return None
    t = texto.strip()
    if "," in t and "." in t:
        t = t.replace(".", "")
    return round(float(t.replace(",", ".")), 2)


def ler_ofx(conteudo):
    """{"movimentos": [{fitid, data, valor, descricao}], "saldo": float|None, "saldo_em": date|None}.

    Aceita OFX 1.x (SGML, tags sem fechar) e 2.x (XML). Valor negativo = saída.
    """
    if isinstance(conteudo, bytes):
        try:
            conteudo = conteudo.decode("utf-8")
        except UnicodeDecodeError:
            conteudo = conteudo.decode("latin-1")
    movimentos = []
    for bloco in _TRN.findall(conteudo):
        d, v = _data(_tag(bloco, "DTPOSTED")), _valor(_tag(bloco, "TRNAMT"))
        if d is None or v is None:
            continue
        memo = _tag(bloco, "MEMO") or ""
        nome = _tag(bloco, "NAME") or ""
        partes = [memo] + ([nome] if nome and nome != memo else [])
        descricao = " · ".join(x for x in partes if x) or None
        fitid = _tag(bloco, "FITID") or f"{d.isoformat()}|{v}|{descricao}"
        movimentos.append({"fitid": fitid, "data": d, "valor": v, "descricao": descricao})
    if not movimentos and "<OFX>" not in conteudo.upper():
        raise ValueError("arquivo não parece um extrato OFX")
    bal = re.search(r"<LEDGERBAL>(.*?)(?:</LEDGERBAL>|<AVAILBAL>|</STMTRS>)", conteudo, re.S | re.I)
    saldo = _valor(_tag(bal.group(1), "BALAMT")) if bal else None
    saldo_em = _data(_tag(bal.group(1), "DTASOF")) if bal else None
    return {"movimentos": movimentos, "saldo": saldo, "saldo_em": saldo_em}


def sugerir(mov, candidatos, folga_dias=3):
    """Com o que este movimento casa. Função pura.

    `candidatos`: [{tipo, id, valor (positivo), data, texto, pago}] — contas a
    pagar, pagamentos a fornecedor e a funcionário já lançados.

    - Entrada do Mercado Pago → casado com "Repasse do Mercado Pago".
    - Saída com UM candidato de mesmo valor e mesma data, já lançado como pago
      → casado sozinho.
    - Saída com candidato de mesmo valor até `folga_dias` de distância →
      sugerido (ela confirma com um clique).
    - Sem candidato → novo.
    Devolve {status, casado_tipo, casado_id, casado_texto}.
    """
    vazio = {"casado_tipo": None, "casado_id": None, "casado_texto": None}
    desc = (mov.get("descricao") or "").upper()
    if mov["valor"] > 0:
        if "MERCADO PAGO" in desc or "MERCADOPAGO" in desc:
            return {"status": "casado", "casado_tipo": "repasse_mp", "casado_id": None,
                    "casado_texto": "Repasse do Mercado Pago"}
        return {"status": "novo", **vazio}
    alvo = round(-mov["valor"], 2)
    perto = [c for c in candidatos
             if abs(round(float(c["valor"]), 2) - alvo) < 0.005
             and c.get("data") and abs((c["data"] - mov["data"]).days) <= folga_dias]
    if not perto:
        return {"status": "novo", **vazio}
    perto.sort(key=lambda c: abs((c["data"] - mov["data"]).days))
    c = perto[0]
    exato = [p for p in perto if p["data"] == mov["data"] and p.get("pago")]
    status = "casado" if len(exato) == 1 and exato[0] is c else "sugerido"
    return {"status": status, "casado_tipo": c["tipo"], "casado_id": c["id"], "casado_texto": c["texto"]}
