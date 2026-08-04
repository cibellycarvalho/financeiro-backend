from flask import Blueprint, request, jsonify, g
from datetime import date, timedelta
import db
from auth import require_auth, require_admin

bp = Blueprint("contas", __name__)

CATEGORIAS_VALIDAS = {"FORNECEDOR", "CONTABILIDADE", "IMPOSTO_DAS", "SISTEMA", "OUTRO"}
MARCAS_VALIDAS = {"YUSO", "M12", "GERAL"}
STATUS_VALIDOS = {"pendente", "a_confirmar", "pago", "vencido"}

@bp.get("")
@require_auth
def listar():
    periodo = request.args.get("periodo")
    status = request.args.get("status")
    marca = request.args.get("marca")

    conditions = ["1=1"]
    params = []

    if periodo == "semana":
        hoje = date.today()
        conditions.append("vencimento BETWEEN %s AND %s")
        params += [hoje.isoformat(), (hoje + timedelta(days=7)).isoformat()]
    elif periodo == "mes":
        hoje = date.today()
        conditions.append("DATE_TRUNC('month', vencimento) = DATE_TRUNC('month', %s::date)")
        params.append(hoje.isoformat())

    if status:
        conditions.append("status = %s")
        params.append(status)
    if marca:
        conditions.append("marca = %s")
        params.append(marca)

    where = " AND ".join(conditions)
    rows = db.query(
        f"SELECT * FROM fin_contas_pagar WHERE {where} ORDER BY vencimento ASC",
        tuple(params)
    )
    return jsonify(rows)

@bp.post("")
@require_auth
@require_admin
def criar():
    data = request.get_json()
    descricao = data.get("descricao", "").strip()
    categoria = data.get("categoria", "")
    try:
        valor = float(data.get("valor", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "valor inválido"}), 400
    vencimento = data.get("vencimento")
    marca = data.get("marca", "GERAL")
    observacao = data.get("observacao")

    if not descricao:
        return jsonify({"error": "descricao obrigatória"}), 400
    if categoria not in CATEGORIAS_VALIDAS:
        return jsonify({"error": f"categoria inválida. Valores: {sorted(CATEGORIAS_VALIDAS)}"}), 400
    if marca not in MARCAS_VALIDAS:
        return jsonify({"error": f"marca inválida. Valores: {sorted(MARCAS_VALIDAS)}"}), 400
    if not vencimento:
        return jsonify({"error": "vencimento obrigatório"}), 400

    row = db.execute(
        """INSERT INTO fin_contas_pagar
           (descricao, categoria, valor, vencimento, marca, observacao, criado_por)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (descricao, categoria, valor, vencimento, marca, observacao, g.user["user_id"])
    )
    return jsonify(row), 201

@bp.put("/<conta_id>")
@require_auth
@require_admin
def atualizar(conta_id):
    data = request.get_json()
    campos = []
    params = []

    if "status" in data:
        if data["status"] not in STATUS_VALIDOS:
            return jsonify({"error": "status inválido"}), 400
        campos.append("status = %s")
        params.append(data["status"])
    if "data_pagamento" in data:
        campos.append("data_pagamento = %s")
        params.append(data["data_pagamento"])
    if "observacao" in data:
        campos.append("observacao = %s")
        params.append(data["observacao"])
    if "valor" in data:
        campos.append("valor = %s")
        params.append(float(data["valor"]))
    if "vencimento" in data:
        campos.append("vencimento = %s")
        params.append(data["vencimento"])

    if not campos:
        return jsonify({"error": "nenhum campo para atualizar"}), 400

    params.append(conta_id)
    row = db.execute(
        f"UPDATE fin_contas_pagar SET {', '.join(campos)} WHERE id = %s RETURNING *",
        tuple(params)
    )
    if not row:
        return jsonify({"error": "Conta não encontrada"}), 404
    return jsonify(row)

@bp.delete("/<conta_id>")
@require_auth
@require_admin
def deletar(conta_id):
    db.execute("DELETE FROM fin_contas_pagar WHERE id = %s", (conta_id,))
    return "", 204
