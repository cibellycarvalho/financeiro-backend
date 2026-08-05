from flask import Blueprint, request, jsonify, g
from datetime import date
import calendar
import requests as http_req
import db
import config
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

@bp.post("/sync-mp")
@require_auth
@require_admin
def sync_mp():
    token = config.MERCADO_PAGO_ACCESS_TOKEN
    if not token:
        return jsonify({"error": "MERCADO_PAGO_ACCESS_TOKEN não configurado"}), 503

    mes = request.args.get("mes", date.today().strftime("%Y-%m"))
    conta_ml = request.args.get("conta_ml", "YUSO")
    if conta_ml not in CONTAS_VALIDAS:
        return jsonify({"error": "conta_ml inválida"}), 400

    try:
        ano, month = int(mes[:4]), int(mes[5:7])
    except ValueError:
        return jsonify({"error": "mes deve ser YYYY-MM"}), 400

    ultimo_dia = calendar.monthrange(ano, month)[1]
    begin = f"{mes}-01T00:00:00.000-03:00"
    end = f"{mes}-{ultimo_dia:02d}T23:59:59.999-03:00"

    offset, limit, total_inserted = 0, 100, 0
    pagamentos = []

    while True:
        resp = http_req.get(
            "https://api.mercadopago.com/v1/payments/search",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "sort": "date_approved",
                "criteria": "desc",
                "range": "date_approved",
                "begin_date": begin,
                "end_date": end,
                "status": "approved",
                "limit": limit,
                "offset": offset,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return jsonify({"error": "Erro na API do Mercado Pago", "detail": resp.text[:300]}), 502

        data = resp.json()
        results = data.get("results", [])
        pagamentos.extend(results)

        paging = data.get("paging", {})
        if offset + limit >= paging.get("total", 0):
            break
        offset += limit

    db.execute(
        "DELETE FROM fin_repasses_ml WHERE origem = 'pluggy' AND conta_ml = %s AND TO_CHAR(data_referencia, 'YYYY-MM') = %s",
        (conta_ml, mes)
    )

    for p in pagamentos:
        pid = str(p.get("id", ""))
        data_ref = (p.get("date_approved") or "")[:10] or date.today().isoformat()
        valor_bruto = float(p.get("transaction_amount") or 0)
        valor_liquido = float(p.get("net_received_amount") or valor_bruto)
        taxa = round(valor_bruto - valor_liquido, 2)
        desc = p.get("description") or f"Pagamento MP #{pid}"

        db.execute(
            """INSERT INTO fin_repasses_ml
               (tipo, valor, data_referencia, descricao, conta_ml, origem, pluggy_transaction_id)
               VALUES (%s, %s, %s, %s, %s, 'pluggy', %s)""",
            ("repasse", valor_bruto, data_ref, desc, conta_ml, pid)
        )
        total_inserted += 1

        if taxa > 0:
            db.execute(
                """INSERT INTO fin_repasses_ml
                   (tipo, valor, data_referencia, descricao, conta_ml, origem, pluggy_transaction_id)
                   VALUES (%s, %s, %s, %s, %s, 'pluggy', %s)""",
                ("tarifa", taxa, data_ref, f"Taxa MP #{pid}", conta_ml, f"fee_{pid}")
            )

    return jsonify({"sincronizados": len(pagamentos), "registros": total_inserted, "periodo": mes})


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
