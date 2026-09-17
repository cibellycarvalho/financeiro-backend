"""Leitura de pedido de compra, comprovante Pix, boleto DAS e nota fiscal por IA (visão).

Regra de ouro: tudo que dá para calcular, não se pergunta ao modelo. A data do
Pix Sicredi está no ID da transação; o total do pedido é a soma dos itens (a
tela recalcula). O modelo só transcreve.
"""
import base64
import json
import re
from datetime import date

import anthropic

import config


class LeituraIndisponivel(Exception):
    """Sem chave ou API fora do ar — a tela manda lançar à mão."""


class LeituraFalhou(Exception):
    """A IA respondeu, mas não deu para usar — a tela abre o cartão vazio."""


ESQUEMA_PEDIDO = {
    "type": "object",
    "properties": {
        "texto_vendedor": {"type": ["string", "null"],
                           "description": "Nome do vendedor/fornecedor como aparece no documento"},
        "numero_pedido": {"type": ["string", "null"]},
        "data_pedido": {"type": ["string", "null"], "description": "AAAA-MM-DD"},
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "produto": {"type": "string"},
                    "quantidade": {"type": "number"},
                    "valor_unitario": {"type": "number"},
                },
                "required": ["produto", "quantidade", "valor_unitario"],
                "additionalProperties": False,
            },
        },
        "total_documento": {"type": ["number", "null"]},
    },
    "required": ["texto_vendedor", "numero_pedido", "data_pedido", "itens", "total_documento"],
    "additionalProperties": False,
}

ESQUEMA_COMPROVANTE = {
    "type": "object",
    "properties": {
        "valor": {"type": "number"},
        "data_pagamento": {"type": ["string", "null"], "description": "AAAA-MM-DD"},
        "destinatario": {"type": ["string", "null"],
                         "description": "Nome de quem recebeu, como aparece no comprovante"},
        "id_transacao": {"type": ["string", "null"],
                         "description": "ID/E2E da transação Pix, exatamente como impresso"},
    },
    "required": ["valor", "data_pagamento", "destinatario", "id_transacao"],
    "additionalProperties": False,
}

INSTRUCAO_PEDIDO = (
    "Este é um pedido de compra de um fornecedor. Transcreva: o nome do vendedor "
    "ou fornecedor como está escrito, o número do pedido, a data do pedido "
    "(AAAA-MM-DD), cada item com produto, quantidade e valor unitário em reais, "
    "e o total do documento. Números no padrão brasileiro (1.000,50 = mil reais e "
    "cinquenta centavos). Não invente itens: se não estiver legível, deixe fora."
)

INSTRUCAO_COMPROVANTE = (
    "Este é um comprovante de pagamento Pix. Transcreva: o valor em reais, a data "
    "do pagamento (AAAA-MM-DD), o nome do destinatário como está escrito e o ID "
    "ou E2E da transação exatamente como impresso."
)

ESQUEMA_DAS = {
    "type": "object",
    "properties": {
        "valor": {"type": ["number", "null"], "description": "Valor total do documento, em reais"},
        "vencimento": {"type": ["string", "null"], "description": "Data de vencimento, AAAA-MM-DD"},
        "competencia": {"type": ["string", "null"],
                        "description": "Período de apuração, AAAA-MM (o mês a que o imposto se refere)"},
        "cnpj": {"type": ["string", "null"], "description": "CNPJ do contribuinte, só dígitos"},
        "nome": {"type": ["string", "null"], "description": "Nome ou razão social do contribuinte"},
    },
    "required": ["valor", "vencimento", "competencia", "cnpj", "nome"],
    "additionalProperties": False,
}

ESQUEMA_NF = {
    "type": "object",
    "properties": {
        "numero": {"type": ["string", "null"], "description": "Número da nota, como impresso"},
        "valor": {"type": ["number", "null"], "description": "Valor total dos serviços, em reais"},
        "data_emissao": {"type": ["string", "null"], "description": "AAAA-MM-DD"},
        "competencia": {"type": ["string", "null"],
                        "description": "Mês dos serviços prestados (AAAA-MM), só se a nota disser; senão null"},
        "cnpj_prestador": {"type": ["string", "null"], "description": "CNPJ de quem emitiu, só dígitos"},
        "nome_prestador": {"type": ["string", "null"], "description": "Nome de quem emitiu, como impresso"},
    },
    "required": ["numero", "valor", "data_emissao", "competencia", "cnpj_prestador", "nome_prestador"],
    "additionalProperties": False,
}

INSTRUCAO_DAS = (
    "Este é um DAS (Documento de Arrecadação do Simples Nacional) de um MEI. "
    "Transcreva: o valor total do documento em reais, a data de vencimento (AAAA-MM-DD), "
    "o período de apuração (AAAA-MM — o mês a que o imposto se refere, que não é o mês "
    "do vencimento), o CNPJ do contribuinte só com dígitos e o nome ou razão social. "
    "Números no padrão brasileiro (75,90 = setenta e cinco reais e noventa centavos)."
)

INSTRUCAO_NF = (
    "Esta é uma nota fiscal de serviço (NFS-e) emitida por um prestador MEI. Transcreva: "
    "o número da nota, o valor total dos serviços em reais, a data de emissão (AAAA-MM-DD), "
    "o CNPJ e o nome do PRESTADOR (quem emitiu, não o tomador), e o mês de competência dos "
    "serviços (AAAA-MM) somente se a discriminação ou algum campo da nota disser em que mês "
    "os serviços foram prestados — se não disser, deixe competencia nula. "
    "Números no padrão brasileiro."
)

_RE_E2E = re.compile(r"^E\d{8}(\d{4})(\d{2})(\d{2})\d{6}")
_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_COMPETENCIA = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")
_RE_COMPETENCIA_BR = re.compile(r"^(\d{2})/(\d{4})$")


def data_do_id_transacao(id_transacao):
    """Sicredi/Pix: 'E' + ISPB(8) + AAAAMMDDHHMMSS + sufixo. A data mora aqui."""
    if not id_transacao:
        return None
    m = _RE_E2E.match(id_transacao.strip())
    if not m:
        return None
    ano, mes, dia = (int(x) for x in m.groups())
    try:
        return date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def _data_ou_none(texto):
    if not texto or not _RE_DATA.match(texto):
        return None
    try:
        date.fromisoformat(texto)
    except ValueError:
        return None
    return texto


def _competencia_ou_none(texto):
    """'2026-09', '2026-09-15' ou '09/2026' → '2026-09-01'. O resto → None."""
    if not isinstance(texto, str):
        return None
    t = texto.strip()
    m = _RE_COMPETENCIA.match(t)
    if m:
        ano, mes = int(m.group(1)), int(m.group(2))
    else:
        m = _RE_COMPETENCIA_BR.match(t)
        if not m:
            return None
        mes, ano = int(m.group(1)), int(m.group(2))
    try:
        return date(ano, mes, 1).isoformat()
    except ValueError:
        return None


def _cnpj_ou_none(texto):
    digitos = re.sub(r"\D", "", texto or "")
    return digitos if len(digitos) == 14 else None


def _valor_positivo_ou_none(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _bloco_arquivo(dados, mime):
    b64 = base64.standard_b64encode(dados).decode("utf-8")
    if mime == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}}
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}


def _chamar(dados, mime, instrucao, esquema):
    """Único ponto que fala com a API. Os testes mockam esta função."""
    if not config.ANTHROPIC_API_KEY:
        raise LeituraIndisponivel("ANTHROPIC_API_KEY não configurada")
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=config.LEITURA_MODEL,
            max_tokens=16000,
            messages=[{"role": "user", "content": [_bloco_arquivo(dados, mime),
                                                   {"type": "text", "text": instrucao}]}],
            output_config={"format": {"type": "json_schema", "schema": esquema}},
        )
    except anthropic.AuthenticationError as e:
        raise LeituraIndisponivel(f"chave inválida: {e}") from e
    except anthropic.RateLimitError as e:
        raise LeituraIndisponivel(f"limite da API: {e}") from e
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            raise LeituraIndisponivel(f"API fora ({e.status_code})") from e
        raise LeituraFalhou(f"API recusou a requisição ({e.status_code})") from e
    except anthropic.APIConnectionError as e:
        raise LeituraIndisponivel(f"sem conexão com a API: {e}") from e
    except anthropic.APIError as e:
        raise LeituraFalhou(f"resposta inválida da API: {e}") from e

    if resp.stop_reason == "refusal":
        raise LeituraFalhou("modelo recusou o documento")
    texto = next((b.text for b in resp.content if b.type == "text"), None)
    if not texto:
        raise LeituraFalhou("resposta sem texto")
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        raise LeituraFalhou(f"resposta não é JSON: {e}") from e


def ler_pedido(dados, mime):
    bruto = _chamar(dados, mime, INSTRUCAO_PEDIDO, ESQUEMA_PEDIDO)
    itens = []
    for item in bruto.get("itens") or []:
        produto = (item.get("produto") or "").strip()
        try:
            quantidade = float(item.get("quantidade"))
            valor_unitario = float(item.get("valor_unitario"))
        except (TypeError, ValueError):
            continue
        if not produto or quantidade <= 0 or valor_unitario < 0:
            continue
        itens.append({"produto": produto, "quantidade": quantidade, "valor_unitario": valor_unitario})
    if not itens:
        raise LeituraFalhou("nenhum item legível")
    total = bruto.get("total_documento")
    return {
        "texto_vendedor": (bruto.get("texto_vendedor") or "").strip() or None,
        "numero_pedido": (bruto.get("numero_pedido") or "").strip() or None,
        "data_pedido": _data_ou_none(bruto.get("data_pedido")),
        "itens": itens,
        "total_documento": float(total) if isinstance(total, (int, float)) else None,
    }


def ler_comprovante(dados, mime):
    bruto = _chamar(dados, mime, INSTRUCAO_COMPROVANTE, ESQUEMA_COMPROVANTE)
    try:
        valor = float(bruto.get("valor"))
    except (TypeError, ValueError):
        valor = 0
    if valor <= 0:
        raise LeituraFalhou("valor do Pix não legível")
    id_transacao = (bruto.get("id_transacao") or "").strip() or None
    return {
        "valor": valor,
        "data_pagamento": data_do_id_transacao(id_transacao) or _data_ou_none(bruto.get("data_pagamento")),
        "destinatario": (bruto.get("destinatario") or "").strip() or None,
        "id_transacao": id_transacao,
    }


def ler_boleto_das(dados, mime):
    bruto = _chamar(dados, mime, INSTRUCAO_DAS, ESQUEMA_DAS)
    valor = _valor_positivo_ou_none(bruto.get("valor"))
    if valor is None:
        raise LeituraFalhou("valor do DAS não legível")
    return {
        "valor": valor,
        "vencimento": _data_ou_none(bruto.get("vencimento")),
        "competencia": _competencia_ou_none(bruto.get("competencia")),
        "cnpj": _cnpj_ou_none(bruto.get("cnpj")),
        "nome": (bruto.get("nome") or "").strip() or None,
    }


def ler_nota_fiscal(dados, mime):
    bruto = _chamar(dados, mime, INSTRUCAO_NF, ESQUEMA_NF)
    numero = (bruto.get("numero") or "").strip() or None
    valor = _valor_positivo_ou_none(bruto.get("valor"))
    if numero is None and valor is None:
        raise LeituraFalhou("nota sem número nem valor legíveis")
    data_emissao = _data_ou_none(bruto.get("data_emissao"))
    competencia = _competencia_ou_none(bruto.get("competencia"))
    # A nota não diz o mês do serviço: assume o da emissão, e a tela avisa
    # (é assim que a NF de agosto emitida em setembro pode ir para agosto).
    inferida = competencia is None
    if inferida and data_emissao:
        competencia = data_emissao[:7] + "-01"
    return {
        "numero": numero,
        "valor": valor,
        "data_emissao": data_emissao,
        "competencia": competencia,
        "competencia_inferida": inferida,
        "cnpj_prestador": _cnpj_ou_none(bruto.get("cnpj_prestador")),
        "nome_prestador": (bruto.get("nome_prestador") or "").strip() or None,
    }
