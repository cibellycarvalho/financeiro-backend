from flask import Blueprint, request, jsonify, g
from datetime import date
import db
from auth import require_auth, require_admin

bp = Blueprint("repasses", __name__)

TIPOS_VALIDOS = {"repasse", "cobranca", "tarifa"}
CONTAS_VALIDAS = {"YUSO", "M12"}

@bp.get("")
@require_auth
def listar():
    mes = request.args.get("mes")
    conta_ml = request.args.get("conta_ml")

    conditions = ["1=1"]
    params = []

    if mes:
        conditions.append("TO_CHAR(data_referencia, 'YYYY-MM') = %s")
        params.append(mes)
    if conta_ml:
        conditions.append("conta_ml = %s")
        params.append(conta_ml)

    where = " AND ".join(conditions)
    rows = db.query(
        f"SELECT * FROM fin_repasses_ml WHERE {where} ORDER BY data_referencia DESC",
        tuple(params)
    )
    return jsonify(rows)

@bp.post("")
@require_auth
@require_admin
def criar():
    data = request.get_json()
    tipo = data.get("tipo", "")
    conta_ml = data.get("conta_ml", "")

    if tipo not in TIPOS_VALIDOS:
        return jsonify({"error": f"tipo inválido. Valores: {sorted(TIPOS_VALIDOS)}"}), 400
    if conta_ml not in CONTAS_VALIDAS:
        return jsonify({"error": f"conta_ml inválida. Valores: {sorted(CONTAS_VALIDAS)}"}), 400

    try:
        valor = float(data.get("valor", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "valor inválido"}), 400

    data_ref = data.get("data_referencia", date.today().isoformat())

    row = db.execute(
        """INSERT INTO fin_repasses_ml (tipo, valor, data_referencia, descricao, conta_ml)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (tipo, valor, data_ref, data.get("descricao"), conta_ml)
    )
    return jsonify(row), 201

@bp.get("/saldo")
@require_auth
def saldo():
    mes = request.args.get("mes", date.today().strftime("%Y-%m"))

    movimentos = db.query(
        "SELECT tipo, valor FROM fin_repasses_ml WHERE TO_CHAR(data_referencia, 'YYYY-MM') = %s",
        (mes,)
    )
    repasses_bruto = sum(r["valor"] for r in movimentos if r["tipo"] == "repasse")
    cobranças_ml = sum(r["valor"] for r in movimentos if r["tipo"] in ("cobranca", "tarifa"))

    contas = db.query(
        """SELECT valor FROM fin_contas_pagar
           WHERE status = 'pago'
           AND TO_CHAR(data_pagamento, 'YYYY-MM') = %s""",
        (mes,)
    )
    contas_pagas = sum(c["valor"] for c in contas)

    return jsonify({
        "periodo": mes,
        "repasses_bruto": repasses_bruto,
        "cobranças_ml": cobranças_ml,
        "contas_pagas": contas_pagas,
        "saldo_disponivel": repasses_bruto - cobranças_ml - contas_pagas
    })
