from flask import Blueprint, jsonify
from datetime import date, timedelta
import db
from auth import require_auth

bp = Blueprint("dashboard", __name__)

@bp.get("")
@require_auth
def dashboard():
    hoje = date.today()
    semana_fim = hoje + timedelta(days=7)
    mes_atual = hoje.strftime("%Y-%m")

    contas_semana = db.query(
        """SELECT id, descricao, valor, vencimento, status, categoria, marca
           FROM fin_contas_pagar
           WHERE vencimento BETWEEN %s AND %s
             AND status NOT IN ('pago')
           ORDER BY vencimento ASC""",
        (hoje.isoformat(), semana_fim.isoformat())
    )

    movimentos = db.query(
        "SELECT tipo, valor FROM fin_repasses_ml WHERE TO_CHAR(data_referencia, 'YYYY-MM') = %s",
        (mes_atual,)
    )
    repasses_bruto = sum(r["valor"] for r in movimentos if r["tipo"] == "repasse")
    cobranças = sum(r["valor"] for r in movimentos if r["tipo"] in ("cobranca", "tarifa"))

    contas_pagas = db.query(
        "SELECT valor FROM fin_contas_pagar WHERE status = 'pago' AND TO_CHAR(data_pagamento, 'YYYY-MM') = %s",
        (mes_atual,)
    )
    total_pago = sum(c["valor"] for c in contas_pagas)

    fornecedores_aberto = db.query("""
        SELECT f.nome, COALESCE(SUM(p.valor_total - p.valor_pago), 0) AS saldo_aberto
        FROM fin_fornecedores f
        JOIN fin_pedidos_fornecedor p ON p.fornecedor_id = f.id AND p.status != 'pago'
        GROUP BY f.id, f.nome
        HAVING SUM(p.valor_total - p.valor_pago) > 0
        ORDER BY saldo_aberto DESC
    """)

    return jsonify({
        "contas_semana": contas_semana,
        "totais": {
            "a_pagar_semana": sum(c["valor"] for c in contas_semana),
            "repasses_bruto_mes": repasses_bruto,
            "cobranças_ml_mes": cobranças,
            "saldo_disponivel": repasses_bruto - cobranças - total_pago,
            "fornecedores_aberto": sum(f["saldo_aberto"] for f in fornecedores_aberto),
        },
        "alertas": {
            "repasse_divergencia": False,
            "frete_divergencias": 0,
        },
        "fornecedores_aberto": fornecedores_aberto,
    })
