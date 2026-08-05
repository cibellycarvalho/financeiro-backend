from flask import Blueprint, request, jsonify, g
import db
from auth import require_auth, require_admin

bp = Blueprint("fornecedores", __name__)

STATUS_PEDIDO_VALIDOS = {"pendente", "pago", "parcial"}

@bp.post("")
@require_auth
@require_admin
def criar_fornecedor():
    data = request.get_json()
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"error": "nome obrigatório"}), 400
    apelido = (data.get("apelido") or "").strip() or None
    tipo = data.get("tipo_pagamento", "variavel")
    if tipo not in ("variavel", "fixo"):
        tipo = "variavel"
    row = db.execute(
        "INSERT INTO fin_fornecedores (nome, apelido, tipo_pagamento) VALUES (%s, %s, %s) RETURNING *",
        (nome, apelido, tipo)
    )
    return jsonify(row), 201


@bp.put("/<fornecedor_id>")
@require_auth
@require_admin
def editar_fornecedor(fornecedor_id):
    data = request.get_json()
    campos, params = [], []
    if "nome" in data:
        nome = (data["nome"] or "").strip()
        if not nome:
            return jsonify({"error": "nome não pode ser vazio"}), 400
        campos.append("nome = %s")
        params.append(nome)
    if "apelido" in data:
        campos.append("apelido = %s")
        params.append((data["apelido"] or "").strip() or None)
    if not campos:
        return jsonify({"error": "nenhum campo para atualizar"}), 400
    params.append(fornecedor_id)
    row = db.execute(
        f"UPDATE fin_fornecedores SET {', '.join(campos)} WHERE id = %s AND ativo = true RETURNING *",
        tuple(params)
    )
    if not row:
        return jsonify({"error": "Fornecedor não encontrado"}), 404
    return jsonify(row)


@bp.get("")
@require_auth
def listar():
    rows = db.query("""
        SELECT f.*,
               COALESCE(SUM(p.valor_total - p.valor_pago), 0) AS saldo_aberto
        FROM fin_fornecedores f
        LEFT JOIN fin_pedidos_fornecedor p
               ON p.fornecedor_id = f.id AND p.status != 'pago'
        WHERE f.ativo = true
        GROUP BY f.id
        ORDER BY f.nome
    """)
    return jsonify(rows)

@bp.get("/<fornecedor_id>/pedidos")
@require_auth
def listar_pedidos(fornecedor_id):
    status = request.args.get("status")
    conditions = ["fornecedor_id = %s"]
    params = [fornecedor_id]
    if status:
        conditions.append("status = %s")
        params.append(status)
    where = " AND ".join(conditions)
    rows = db.query(
        f"SELECT * FROM fin_pedidos_fornecedor WHERE {where} ORDER BY data_pedido DESC",
        tuple(params)
    )
    return jsonify(rows)

@bp.post("/<fornecedor_id>/pedidos")
@require_auth
@require_admin
def criar_pedido(fornecedor_id):
    data = request.get_json()
    try:
        valor_total = float(data.get("valor_total", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "valor_total inválido"}), 400

    if not data.get("data_pedido"):
        return jsonify({"error": "data_pedido obrigatória"}), 400

    row = db.execute(
        """INSERT INTO fin_pedidos_fornecedor
           (fornecedor_id, data_pedido, descricao_produtos, valor_total, prazo_combinado, criado_por)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (fornecedor_id, data["data_pedido"], data.get("descricao_produtos"),
         valor_total, data.get("prazo_combinado"), g.user["user_id"])
    )
    return jsonify(row), 201

@bp.put("/<fornecedor_id>/pedidos/<pedido_id>")
@require_auth
@require_admin
def atualizar_pedido(fornecedor_id, pedido_id):
    data = request.get_json()
    campos, params = [], []

    if "status" in data:
        if data["status"] not in STATUS_PEDIDO_VALIDOS:
            return jsonify({"error": "status inválido"}), 400
        campos.append("status = %s"); params.append(data["status"])
    if "valor_pago" in data:
        try:
            valor_pago = float(data["valor_pago"])
        except (TypeError, ValueError):
            return jsonify({"error": "valor_pago inválido"}), 400
        campos.append("valor_pago = %s"); params.append(valor_pago)
    if "data_pagamento" in data:
        campos.append("data_pagamento = %s"); params.append(data["data_pagamento"])
    if "observacao" in data:
        campos.append("observacao = %s"); params.append(data["observacao"])

    if not campos:
        return jsonify({"error": "nenhum campo para atualizar"}), 400

    params += [pedido_id, fornecedor_id]
    row = db.execute(
        f"UPDATE fin_pedidos_fornecedor SET {', '.join(campos)} WHERE id = %s AND fornecedor_id = %s RETURNING *",
        tuple(params)
    )
    if not row:
        return jsonify({"error": "Pedido não encontrado"}), 404
    return jsonify(row)
