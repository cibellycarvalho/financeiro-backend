"""Planejamento da Caixa da Semana: saldo em conta, reserva, agenda do Mercado
Pago e as escolhas de "Descontar / Não descontar" de cada pagamento.

Não há conciliação bancária, então esses números são informados por pessoa. No
navegador, cada aparelho via um painel diferente; aqui todo mundo vê o mesmo.
Desenho da ordem de serviço de 14/09/2026 (frontend/docs).
"""
import json
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, g

import db
from auth import require_auth

bp = Blueprint("planejamento", __name__)

_DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _segunda(texto):
    """Exige segunda-feira em vez de arrumar sozinho: com a semana na chave
    primária, aceitar uma terça criaria outra linha para a mesma semana."""
    try:
        d = datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None, (jsonify({"error": "semana deve ser uma data YYYY-MM-DD"}), 400)
    if d.weekday() != 0:
        return None, (jsonify({"error": f"semana deve ser uma segunda-feira; {texto} é {_DIAS[d.weekday()]}"}), 400)
    return d, None


def _numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _agenda_invalida(agenda, semana):
    if not isinstance(agenda, dict):
        return "agenda deve ser um objeto de data para valor"
    dias = {(semana + timedelta(days=i)).isoformat() for i in range(7)}
    for chave, valor in agenda.items():
        if chave not in dias:
            return f"{chave} não está na semana de {semana.isoformat()}"
        if not _numero(valor):
            return f"valor de {chave} deve ser número"
    return None


def _ajustes_invalidos(ajustes):
    if not isinstance(ajustes, dict) or not all(isinstance(v, bool) for v in ajustes.values()):
        return "ajustes_pagamento deve ser um objeto de id para verdadeiro/falso"
    return None


@bp.get("/<semana>")
@require_auth
def ler(semana):
    d, erro = _segunda(semana)
    if erro:
        return erro
    rows = db.query("SELECT * FROM fin_planejamento_semana WHERE semana = %s", (d.isoformat(),))
    if not rows:
        # Semana nunca informada é o estado normal de toda segunda de manhã.
        return jsonify({
            "semana": d.isoformat(), "saldo_conta": None, "saldo_em": None,
            "reserva_aplicada": None, "agenda": {}, "ajustes_pagamento": {},
            "updated_at": None,
        })
    return jsonify(rows[0])


@bp.put("/<semana>")
@require_auth   # de propósito sem @require_admin: os dois donos preenchem (14/09/2026)
def gravar(semana):
    d, erro = _segunda(semana)
    if erro:
        return erro
    data = request.get_json(silent=True) or {}

    def numero(campo):
        v = data.get(campo)
        if v is None or v == "":
            return None, None
        if not _numero(v):
            return None, f"{campo} inválido"
        return float(v), None

    saldo, e1 = numero("saldo_conta")
    reserva, e2 = numero("reserva_aplicada")
    if e1 or e2:
        return jsonify({"error": e1 or e2}), 400
    if reserva is not None and reserva < 0:
        return jsonify({"error": "reserva_aplicada não pode ser negativa"}), 400

    agenda = data.get("agenda", {})
    ajustes = data.get("ajustes_pagamento", {})
    problema = _agenda_invalida(agenda, d) or _ajustes_invalidos(ajustes)
    if problema:
        return jsonify({"error": problema}), 400

    # saldo_em só anda quando o saldo muda: é ele que diz o que já estava fora
    # da conta na regra anti-desconto-duplo. Salvar a agenda não pode mexer nele.
    row = db.execute(
        """INSERT INTO fin_planejamento_semana
               (semana, saldo_conta, saldo_em, reserva_aplicada, agenda, ajustes_pagamento,
                informado_por, updated_at)
           VALUES (%s, %s, CASE WHEN %s::numeric IS NULL THEN NULL ELSE now() END,
                   %s, %s::jsonb, %s::jsonb, %s, now())
           ON CONFLICT (semana) DO UPDATE
               SET saldo_em = CASE
                       WHEN fin_planejamento_semana.saldo_conta IS DISTINCT FROM EXCLUDED.saldo_conta
                       THEN CASE WHEN EXCLUDED.saldo_conta IS NULL THEN NULL ELSE now() END
                       ELSE fin_planejamento_semana.saldo_em END,
                   saldo_conta = EXCLUDED.saldo_conta,
                   reserva_aplicada = EXCLUDED.reserva_aplicada,
                   agenda = EXCLUDED.agenda,
                   ajustes_pagamento = EXCLUDED.ajustes_pagamento,
                   informado_por = EXCLUDED.informado_por,
                   updated_at = now()
           RETURNING *""",
        (d.isoformat(), saldo, saldo, reserva, json.dumps(agenda), json.dumps(ajustes),
         g.user["user_id"])
    )
    return jsonify(row)
