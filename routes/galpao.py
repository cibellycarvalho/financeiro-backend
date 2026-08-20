"""Contagem mensal do galpão — mercadoria que o Mercado Livre não enxerga.

Portado do CRM (`routes/estoque_mensal.py`) em 19/08/2026.

**Só o galpão migrou.** O estoque mensal ficou no CRM porque o `POST /estoque`
captura o Full e o FBM direto da API do Mercado Livre — é integração com o ML,
que só existe lá. Mover só a leitura deixaria ler e gravar o mesmo dado em
serviços diferentes, que divergem com o tempo. O galpão não tem nada disso: é um
número que ela conta e digita.

**Não passa pela trava de loja, e isso é correto.** A contagem é um fato do
NEGÓCIO dela, não de uma loja: a tabela é chaveada por dono da conta e mês
(`owner_user_id`, `mes_ano`), sem `conta_ml`. Não há loja a proteger aqui.

O dono é o id do usuário no Supabase. O CRM o chama de `id` e o Painel de
`user_id` — mesmo valor, o `sub` do token. Se divergissem, uma contagem gravada
de um lado não seria encontrada do outro.
"""
from flask import Blueprint, request, jsonify, g

import db
from auth import require_auth

bp = Blueprint("galpao", __name__)


def _mes_ano_valido(mes_ano):
    try:
        ano, mes = str(mes_ano).split("-")
        return len(ano) == 4 and int(ano) > 0 and 1 <= int(mes) <= 12
    except Exception:
        return False


def _serializar(linha):
    saida = dict(linha)
    saida["valor"] = float(saida["valor"])
    atualizado = saida.get("atualizado_em")
    if hasattr(atualizado, "isoformat"):
        saida["atualizado_em"] = atualizado.isoformat()
    return saida


@bp.get("/galpao")
@require_auth
def ler_galpao():
    mes_ano = request.args.get("mes_ano", "")
    if not _mes_ano_valido(mes_ano):
        return jsonify({"error": "mes_ano inválido (esperado AAAA-MM)"}), 400

    linhas = db.query(
        """SELECT mes_ano, valor, observacao, atualizado_em
             FROM fechamento_galpao_mensal
            WHERE owner_user_id = %s AND mes_ano = %s""",
        (g.user["user_id"], mes_ano),
    )
    if not linhas:
        # 404, nunca valor 0: "não contei" e "contei e deu zero" significam
        # coisas opostas no fechamento, e devolver zero apagaria a diferença.
        return jsonify({"error": "Galpão deste mês ainda não foi registrado"}), 404
    return jsonify(_serializar(linhas[0]))


@bp.put("/galpao")
@require_auth
def salvar_galpao():
    corpo = request.get_json(silent=True) or {}
    if not _mes_ano_valido(corpo.get("mes_ano", "")):
        return jsonify({"error": "mes_ano inválido (esperado AAAA-MM)"}), 400

    try:
        valor = float(corpo.get("valor"))
    except (TypeError, ValueError):
        return jsonify({"error": "valor precisa ser um número"}), 400
    if valor < 0:
        return jsonify({"error": "valor não pode ser negativo"}), 400

    linha = db.execute(
        """INSERT INTO fechamento_galpao_mensal
             (owner_user_id, mes_ano, valor, observacao, atualizado_em)
           VALUES (%s, %s, %s, %s, NOW())
           ON CONFLICT (owner_user_id, mes_ano) DO UPDATE SET
             valor = EXCLUDED.valor,
             observacao = EXCLUDED.observacao,
             atualizado_em = NOW()
           RETURNING mes_ano, valor, observacao, atualizado_em""",
        (g.user["user_id"], corpo["mes_ano"], valor, corpo.get("observacao") or None),
    )
    return jsonify(_serializar(linha))
