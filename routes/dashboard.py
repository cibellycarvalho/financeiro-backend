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

    contas_pendentes_mes = db.query(
        "SELECT valor FROM fin_contas_pagar WHERE status IN ('pendente', 'vencido') AND TO_CHAR(vencimento, 'YYYY-MM') = %s",
        (mes_atual,)
    )
    total_pendente = sum(c["valor"] for c in contas_pendentes_mes)

    fornecedores_aberto = db.query("""
        WITH saldos AS (
            SELECT f.nome,
                   COALESCE((SELECT SUM(p.valor_total) FROM fin_pedidos_fornecedor p WHERE p.fornecedor_id = f.id), 0)
                   - COALESCE((SELECT SUM(pg.valor) FROM fin_pagamentos_fornecedor pg WHERE pg.fornecedor_id = f.id), 0)
                   AS saldo_aberto
            FROM fin_fornecedores f
            WHERE f.ativo = true
        )
        SELECT * FROM saldos WHERE saldo_aberto > 0 ORDER BY saldo_aberto DESC
    """)
    total_fornecedores = sum(f["saldo_aberto"] for f in fornecedores_aberto)

    return jsonify({
        "contas_semana": contas_semana,
        "totais": {
            "a_pagar_semana": sum(c["valor"] for c in contas_semana),
            "repasses_bruto_mes": repasses_bruto,
            "cobranças_ml_mes": cobranças,
            "saldo_disponivel": repasses_bruto - cobranças - total_pago - total_pendente - total_fornecedores,
            "fornecedores_aberto": total_fornecedores,
            # As duas parcelas abaixo ja eram calculadas aqui e ficavam so na
            # subtracao. A tela agora escreve a conta embaixo do saldo — sem
            # elas, o numero aparece do nada e a pessoa nao tem como discordar
            # dele. Custam zero: sao as mesmas somas de sempre.
            "contas_pagas_mes": total_pago,
            "contas_pendentes_mes": total_pendente,
            "n_contas_semana": len(contas_semana),
            "n_fornecedores_aberto": len(fornecedores_aberto),
        },
        "alertas": {
            "repasse_divergencia": False,
            "frete_divergencias": 0,
        },
        "fornecedores_aberto": fornecedores_aberto,
    })
