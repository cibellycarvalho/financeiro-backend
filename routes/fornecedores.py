from flask import Blueprint, request, jsonify, g
import db
from auth import require_auth, require_admin

bp = Blueprint("fornecedores", __name__)


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


@bp.delete("/<fornecedor_id>")
@require_auth
@require_admin
def excluir_fornecedor(fornecedor_id):
    fornecedores = db.query(
        "SELECT id FROM fin_fornecedores WHERE id = %s AND ativo = true",
        (fornecedor_id,)
    )
    if not fornecedores:
        return jsonify({"error": "Fornecedor não encontrado"}), 404

    saldo_row = db.query(
        """SELECT COALESCE(SUM(valor_total - valor_pago), 0) AS saldo_aberto
           FROM fin_pedidos_fornecedor
           WHERE fornecedor_id = %s AND status != 'pago'""",
        (fornecedor_id,)
    )
    saldo_aberto = float(saldo_row[0]["saldo_aberto"])
    if saldo_aberto > 0:
        return jsonify({"error": "Fornecedor possui saldo em aberto e não pode ser excluído"}), 400

    row = db.execute(
        "UPDATE fin_fornecedores SET ativo = false WHERE id = %s RETURNING *",
        (fornecedor_id,)
    )
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
    conditions = ["p.fornecedor_id = %s"]
    params = [fornecedor_id]
    if status:
        conditions.append("p.status = %s")
        params.append(status)
    where = " AND ".join(conditions)
    rows = db.query(
        f"""SELECT p.*,
                   COALESCE(
                     (SELECT json_agg(
                        json_build_object(
                          'id', i.id, 'produto', i.produto, 'quantidade', i.quantidade,
                          'valor_unitario', i.valor_unitario, 'valor_total', i.valor_total
                        ) ORDER BY i.created_at
                      ) FROM fin_pedido_itens i WHERE i.pedido_id = p.id), '[]'
                   ) AS itens,
                   COALESCE(
                     (SELECT json_agg(
                        json_build_object('id', pg.id, 'valor', pg.valor, 'data_pagamento', pg.data_pagamento)
                        ORDER BY pg.data_pagamento, pg.created_at
                      ) FROM fin_pedido_pagamentos pg WHERE pg.pedido_id = p.id), '[]'
                   ) AS pagamentos
            FROM fin_pedidos_fornecedor p
            WHERE {where}
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


def _recalcular_pedido(cur, pedido_id, fornecedor_id):
    """Recalcula valor_pago/status do pedido somando fin_pedido_pagamentos.
    Deve rodar dentro de uma transação, após inserir/editar/excluir um pagamento."""
    cur.execute(
        "SELECT COALESCE(SUM(valor), 0) AS total, MAX(data_pagamento) AS ultima_data "
        "FROM fin_pedido_pagamentos WHERE pedido_id = %s",
        (pedido_id,)
    )
    soma = dict(cur.fetchone())
    total_pago = float(soma["total"])

    cur.execute("SELECT valor_total FROM fin_pedidos_fornecedor WHERE id = %s", (pedido_id,))
    valor_total = float(dict(cur.fetchone())["valor_total"])

    if total_pago >= valor_total:
        novo_status = "pago"
    elif total_pago > 0:
        novo_status = "parcial"
    else:
        novo_status = "pendente"

    cur.execute(
        """UPDATE fin_pedidos_fornecedor
           SET valor_pago = %s, status = %s, data_pagamento = %s
           WHERE id = %s AND fornecedor_id = %s
           RETURNING *""",
        (total_pago, novo_status, soma["ultima_data"], pedido_id, fornecedor_id)
    )
    return dict(cur.fetchone())


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

    with db.transaction() as cur:
        cur.execute(
            """INSERT INTO fin_pedido_pagamentos (pedido_id, valor, data_pagamento, criado_por)
               VALUES (%s, %s, %s, %s)
               RETURNING *""",
            (pedido_id, valor, data["data_pagamento"], g.user["user_id"])
        )
        pagamento = dict(cur.fetchone())
        pedido_atualizado = _recalcular_pedido(cur, pedido_id, fornecedor_id)

    pedido_atualizado["pagamento"] = pagamento
    return jsonify(pedido_atualizado)


@bp.put("/<fornecedor_id>/pedidos/<pedido_id>/pagamentos/<pagamento_id>")
@require_auth
@require_admin
def editar_pagamento(fornecedor_id, pedido_id, pagamento_id):
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

    pagamentos_atuais = db.query(
        "SELECT valor FROM fin_pedido_pagamentos WHERE id = %s AND pedido_id = %s",
        (pagamento_id, pedido_id)
    )
    if not pagamentos_atuais:
        return jsonify({"error": "Pagamento não encontrado"}), 404
    valor_atual = float(pagamentos_atuais[0]["valor"])

    saldo_sem_este = float(pedido["valor_total"]) - (float(pedido["valor_pago"]) - valor_atual)
    if valor > saldo_sem_este:
        return jsonify({"error": f"Valor maior que o saldo disponível (R$ {saldo_sem_este:.2f})"}), 400

    with db.transaction() as cur:
        cur.execute(
            """UPDATE fin_pedido_pagamentos SET valor = %s, data_pagamento = %s
               WHERE id = %s AND pedido_id = %s
               RETURNING *""",
            (valor, data["data_pagamento"], pagamento_id, pedido_id)
        )
        pagamento = dict(cur.fetchone())
        pedido_atualizado = _recalcular_pedido(cur, pedido_id, fornecedor_id)

    pedido_atualizado["pagamento"] = pagamento
    return jsonify(pedido_atualizado)


@bp.delete("/<fornecedor_id>/pedidos/<pedido_id>/pagamentos/<pagamento_id>")
@require_auth
@require_admin
def excluir_pagamento(fornecedor_id, pedido_id, pagamento_id):
    pedidos = db.query(
        "SELECT id FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id)
    )
    if not pedidos:
        return jsonify({"error": "Pedido não encontrado"}), 404

    pagamentos = db.query(
        "SELECT id FROM fin_pedido_pagamentos WHERE id = %s AND pedido_id = %s",
        (pagamento_id, pedido_id)
    )
    if not pagamentos:
        return jsonify({"error": "Pagamento não encontrado"}), 404

    with db.transaction() as cur:
        cur.execute(
            "DELETE FROM fin_pedido_pagamentos WHERE id = %s AND pedido_id = %s",
            (pagamento_id, pedido_id)
        )
        pedido_atualizado = _recalcular_pedido(cur, pedido_id, fornecedor_id)

    return jsonify(pedido_atualizado)
