"""Leitura de pedido de compra e comprovante Pix por IA (visão).

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

_RE_E2E = re.compile(r"^E\d{8}(\d{4})(\d{2})(\d{2})\d{6}")
_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
