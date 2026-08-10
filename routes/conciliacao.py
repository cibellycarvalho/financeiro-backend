import uuid
from datetime import date, timedelta
from flask import Blueprint, request, jsonify, g
import db
from auth import require_auth, require_admin
from ofx_utils import parse_ofx, melhor_candidato, JANELA_DIAS

bp = Blueprint("conciliacao", __name__)


@bp.post("/importar")
@require_auth
@require_admin
def importar():
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"error": "arquivo .ofx obrigatório"}), 400

    try:
        transacoes = parse_ofx(arquivo.stream)
    except Exception:
        return jsonify({"error": "Arquivo OFX inválido"}), 400

    if not transacoes:
        return jsonify({"error": "Nenhuma transação encontrada no arquivo"}), 400

    lote_id = str(uuid.uuid4())
    usados = set()
    duplicadas = casadas = sem_match = novas = 0

    with db.transaction() as cur:
        for txn in transacoes:
            cur.execute("SELECT id FROM fin_extrato_transacoes WHERE fitid = %s", (txn["fitid"],))
            if cur.fetchone():
                duplicadas += 1
                continue

            data_txn = date.fromisoformat(txn["data"])
            data_min = data_txn - timedelta(days=JANELA_DIAS)
            data_max = data_txn + timedelta(days=JANELA_DIAS)
            candidatos = []

            if txn["tipo"] == "DEBIT":
                cur.execute(
                    """SELECT id, data_pagamento AS data, descricao FROM fin_contas_pagar
                       WHERE status = 'pago' AND ofx_transacao_id IS NULL
                         AND valor = %s AND data_pagamento BETWEEN %s AND %s""",
                    (txn["valor"], data_min, data_max),
                )
                candidatos += [{**dict(r), "tabela": "fin_contas_pagar"} for r in cur.fetchall()]

                cur.execute(
                    """SELECT pp.id, pp.data_pagamento AS data, pf.nome AS descricao
                       FROM fin_pedido_pagamentos pp
                       JOIN fin_pedidos_fornecedor pd ON pd.id = pp.pedido_id
                       JOIN fin_fornecedores pf ON pf.id = pd.fornecedor_id
                       WHERE pp.ofx_transacao_id IS NULL AND pp.valor = %s
                         AND pp.data_pagamento BETWEEN %s AND %s""",
                    (txn["valor"], data_min, data_max),
                )
                candidatos += [{**dict(r), "tabela": "fin_pedido_pagamentos"} for r in cur.fetchall()]
            else:
                cur.execute(
                    """SELECT id, data_referencia AS data, descricao FROM fin_repasses_ml
                       WHERE ofx_transacao_id IS NULL AND valor = %s
                         AND data_referencia BETWEEN %s AND %s""",
                    (txn["valor"], data_min, data_max),
                )
                candidatos += [{**dict(r), "tabela": "fin_repasses_ml"} for r in cur.fetchall()]

            match = melhor_candidato(data_txn, candidatos, usados)
            if match:
                usados.add((match["tabela"], match["id"]))
                casadas += 1
            elif txn["tipo"] == "DEBIT":
                novas += 1
            else:
                sem_match += 1

            cur.execute(
                """INSERT INTO fin_extrato_transacoes
                     (lote_id, fitid, tipo, valor, data, descricao, match_tabela, match_id, criado_por)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    lote_id, txn["fitid"], txn["tipo"], txn["valor"], data_txn, txn["descricao"],
                    match["tabela"] if match else None, match["id"] if match else None,
                    g.user["user_id"],
                ),
            )

    inseridas = casadas + sem_match + novas
    return jsonify({
        "lote_id": lote_id if inseridas > 0 else None,
        "total": len(transacoes),
        "duplicadas": duplicadas,
        "casadas": casadas,
        "sem_match": sem_match,
        "novas": novas,
    }), 201


@bp.get("/lotes/<lote_id>")
@require_auth
def listar_lote(lote_id):
    transacoes = db.query(
        "SELECT * FROM fin_extrato_transacoes WHERE lote_id = %s ORDER BY data", (lote_id,)
    )
    if not transacoes:
        return jsonify({"error": "Lote não encontrado"}), 404

    resultado = []
    for t in transacoes:
        item = dict(t)
        row = []
        if t["match_tabela"] == "fin_contas_pagar":
            row = db.query("SELECT descricao, valor FROM fin_contas_pagar WHERE id = %s", (t["match_id"],))
        elif t["match_tabela"] == "fin_pedido_pagamentos":
            row = db.query(
                """SELECT pf.nome AS descricao, pp.valor FROM fin_pedido_pagamentos pp
                   JOIN fin_pedidos_fornecedor pd ON pd.id = pp.pedido_id
                   JOIN fin_fornecedores pf ON pf.id = pd.fornecedor_id
                   WHERE pp.id = %s""",
                (t["match_id"],),
            )
        elif t["match_tabela"] == "fin_repasses_ml":
            row = db.query("SELECT descricao, valor FROM fin_repasses_ml WHERE id = %s", (t["match_id"],))
        item["match_descricao"] = row[0]["descricao"] if row else None
        resultado.append(item)

    return jsonify(resultado)
