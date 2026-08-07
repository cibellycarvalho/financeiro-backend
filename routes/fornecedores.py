from flask import Blueprint, request, jsonify, g
import db
from auth import require_auth, require_admin

bp = Blueprint("fornecedores", __name__)


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
    conditions = ["p.fornecedor_id = %s"]
    params = [fornecedor_id]
    if status:
        conditions.append("p.status = %s")
        params.append(status)
    where = " AND ".join(conditions)
    rows = db.query(
        f"""SELECT p.*,
                   COALESCE(
                     json_agg(
                       json_build_object(
                         'id', i.id, 'produto', i.produto, 'quantidade', i.quantidade,
                         'valor_unitario', i.valor_unitario, 'valor_total', i.valor_total
                       ) ORDER BY i.created_at
                     ) FILTER (WHERE i.id IS NOT NULL), '[]'
                   ) AS itens
            FROM fin_pedidos_fornecedor p
            LEFT JOIN fin_pedido_itens i ON i.pedido_id = p.id
            WHERE {where}
            GROUP BY p.id
            ORDER BY p.data_pedido DESC""",
        tuple(params)
    )
    return jsonify(rows)


def _validar_itens(itens):
    """Valida a lista de itens do pedido. Retorna (itens_validados, erro)."""
    if not itens or not isinstance(itens, list):
        return None, "itens obrigatório (lista de produtos)"

    itens_validados = []
    for item in itens:
        produto = (item.get("produto") or "").strip()
        if not produto:
            return None, "produto obrigatório em cada item"
        try:
            quantidade = float(item.get("quantidade"))
            valor_unitario = float(item.get("valor_unitario"))
        except (TypeError, ValueError):
            return None, "quantidade e valor_unitario devem ser numéricos"
        if quantidade <= 0:
            return None, "quantidade deve ser maior que zero"
        if valor_unitario < 0:
            return None, "valor_unitario não pode ser negativo"
        itens_validados.append((produto, quantidade, valor_unitario))
    return itens_validados, None


@bp.post("/<fornecedor_id>/pedidos")
@require_auth
@require_admin
def criar_pedido(fornecedor_id):
    data = request.get_json()

    if not data.get("data_pedido"):
        return jsonify({"error": "data_pedido obrigatória"}), 400

    itens_validados, erro = _validar_itens(data.get("itens"))
    if erro:
        return jsonify({"error": erro}), 400

    valor_total = sum(quantidade * valor_unitario for _, quantidade, valor_unitario in itens_validados)

    with db.transaction() as cur:
        cur.execute(
            """INSERT INTO fin_pedidos_fornecedor
               (fornecedor_id, data_pedido, valor_total, observacao, criado_por)
               VALUES (%s, %s, %s, %s, %s)
               RETURNING *""",
            (fornecedor_id, data["data_pedido"], valor_total, data.get("observacao"), g.user["user_id"])
        )
        pedido = dict(cur.fetchone())

        itens_criados = []
        for produto, quantidade, valor_unitario in itens_validados:
            cur.execute(
                """INSERT INTO fin_pedido_itens (pedido_id, produto, quantidade, valor_unitario)
                   VALUES (%s, %s, %s, %s)
                   RETURNING *""",
                (pedido["id"], produto, quantidade, valor_unitario)
            )
            itens_criados.append(dict(cur.fetchone()))

    pedido["itens"] = itens_criados
    return jsonify(pedido), 201


@bp.put("/<fornecedor_id>/pedidos/<pedido_id>")
@require_auth
@require_admin
def atualizar_pedido(fornecedor_id, pedido_id):
    data = request.get_json()
    if "observacao" not in data:
        return jsonify({"error": "nenhum campo para atualizar"}), 400

    row = db.execute(
        "UPDATE fin_pedidos_fornecedor SET observacao = %s WHERE id = %s AND fornecedor_id = %s RETURNING *",
        (data["observacao"], pedido_id, fornecedor_id)
    )
    if not row:
        return jsonify({"error": "Pedido não encontrado"}), 404
    return jsonify(row)


@bp.post("/<fornecedor_id>/pedidos/<pedido_id>/pagamentos")
@require_auth
@require_admin
def registrar_pagamento(fornecedor_id, pedido_id):
    data = request.get_json()
    try:
        valor = float(data.get("valor"))
    except (TypeError, ValueError):
        return jsonify({"error": "valor inválido"}), 400
    if valor <= 0:
        return jsonify({"error": "valor deve ser maior que zero"}), 400
    if not data.get("data_pagamento"):
        return jsonify({"error": "data_pagamento obrigatória"}), 400

    pedidos = db.query(
        "SELECT * FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id)
    )
    if not pedidos:
        return jsonify({"error": "Pedido não encontrado"}), 404
    pedido = pedidos[0]

    saldo_restante = float(pedido["valor_total"]) - float(pedido["valor_pago"])
    if valor > saldo_restante:
        return jsonify({"error": f"Valor maior que o saldo restante (R$ {saldo_restante:.2f})"}), 400

    novo_valor_pago = float(pedido["valor_pago"]) + valor
    novo_status = "pago" if novo_valor_pago >= float(pedido["valor_total"]) else "parcial"

    row = db.execute(
        """UPDATE fin_pedidos_fornecedor
           SET valor_pago = %s, status = %s, data_pagamento = %s
           WHERE id = %s AND fornecedor_id = %s
           RETURNING *""",
        (novo_valor_pago, novo_status, data["data_pagamento"], pedido_id, fornecedor_id)
    )
    return jsonify(row)
