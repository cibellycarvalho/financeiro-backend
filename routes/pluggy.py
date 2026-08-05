from flask import Blueprint, request, jsonify, make_response
from datetime import date, timedelta
import requests as http_req
import db
import config
from auth import require_auth, require_admin

bp = Blueprint("pluggy", __name__)
PLUGGY_API = "https://api.pluggy.ai"


def _api_key():
    resp = http_req.post(
        f"{PLUGGY_API}/auth",
        json={"clientId": config.PLUGGY_CLIENT_ID, "clientSecret": config.PLUGGY_CLIENT_SECRET},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["apiKey"]


@bp.post("/connect-token")
@require_auth
@require_admin
def gerar_connect_token():
    api_key = _api_key()
    redirect_url = config.PLUGGY_REDIRECT_URL
    resp = http_req.post(
        f"{PLUGGY_API}/connect_token",
        json={"redirectUrl": redirect_url},
        headers={"X-API-KEY": api_key},
        timeout=10,
    )
    resp.raise_for_status()
    access_token = resp.json()["accessToken"]
    return jsonify({"url": f"https://connect.pluggy.ai/?connect_token={access_token}"})


@bp.get("/callback")
def callback():
    item_id = request.args.get("itemId")
    error = request.args.get("error")

    if error or not item_id:
        html = f"""<!doctype html><html><body style="font-family:sans-serif;text-align:center;padding:60px">
        <h2>❌ Erro na conexão</h2><p>{error or 'itemId não recebido'}</p>
        <a href="https://financeiro.sellerml.com.br">Voltar ao painel</a></body></html>"""
        return make_response(html, 400)

    connector_name = "Banco"
    try:
        api_key = _api_key()
        item_resp = http_req.get(
            f"{PLUGGY_API}/items/{item_id}",
            headers={"X-API-KEY": api_key},
            timeout=10,
        )
        if item_resp.ok:
            connector_name = item_resp.json().get("connector", {}).get("name", "Banco")
    except Exception:
        pass

    db.execute(
        """INSERT INTO fin_pluggy_items (item_id, connector_name)
           VALUES (%s, %s)
           ON CONFLICT (item_id) DO UPDATE
             SET connector_name = EXCLUDED.connector_name,
                 ativo = TRUE,
                 atualizado_em = NOW()""",
        (item_id, connector_name),
    )

    html = f"""<!doctype html><html><body style="font-family:sans-serif;text-align:center;padding:60px;background:#f8fafc">
    <div style="max-width:400px;margin:0 auto;background:white;border-radius:16px;padding:40px;box-shadow:0 2px 16px rgba(0,0,0,.08)">
    <div style="font-size:48px;margin-bottom:16px">✅</div>
    <h2 style="margin:0 0 8px">Conta conectada!</h2>
    <p style="color:#666;margin:0 0 24px">{connector_name} vinculado com sucesso.</p>
    <a href="https://financeiro.sellerml.com.br" style="display:inline-block;padding:12px 28px;background:#1a1a1a;color:white;border-radius:8px;text-decoration:none">
      Ir para o painel
    </a></div></body></html>"""
    return make_response(html, 200)


@bp.get("/status")
@require_auth
def status():
    items = db.query(
        "SELECT id, item_id, connector_name, ativo, criado_em FROM fin_pluggy_items WHERE ativo = TRUE ORDER BY criado_em DESC"
    )
    return jsonify({"items": items, "conectado": len(items) > 0})


@bp.post("/sync")
@require_auth
@require_admin
def sync():
    items = db.query(
        "SELECT item_id, connector_name FROM fin_pluggy_items WHERE ativo = TRUE ORDER BY criado_em DESC"
    )
    if not items:
        return jsonify({"error": "Nenhuma conta bancária conectada. Conecte o Sicredi primeiro."}), 400

    api_key = _api_key()
    hoje = date.today()
    from_date = (hoje - timedelta(days=90)).isoformat()
    to_date = hoje.isoformat()
    total_novos = 0

    for item in items:
        item_id = item["item_id"]

        acc_resp = http_req.get(
            f"{PLUGGY_API}/accounts",
            params={"itemId": item_id},
            headers={"X-API-KEY": api_key},
            timeout=10,
        )
        if not acc_resp.ok:
            continue

        for account in acc_resp.json().get("results", []):
            account_id = account["id"]
            page = 1

            while True:
                tx_resp = http_req.get(
                    f"{PLUGGY_API}/transactions",
                    params={
                        "accountId": account_id,
                        "from": from_date,
                        "to": to_date,
                        "pageSize": 500,
                        "page": page,
                    },
                    headers={"X-API-KEY": api_key},
                    timeout=15,
                )
                if not tx_resp.ok:
                    break

                data = tx_resp.json()
                transactions = data.get("results", [])

                for tx in transactions:
                    if tx.get("type") != "DEBIT":
                        continue

                    pluggy_id = tx["id"]
                    valor = abs(float(tx.get("amount") or 0))
                    descricao = (tx.get("description") or "Débito Sicredi")[:200]
                    data_tx = (tx.get("date") or "")[:10]

                    if not data_tx or valor == 0:
                        continue

                    rows_affected = db.execute(
                        """INSERT INTO fin_contas_pagar
                             (descricao, categoria, valor, vencimento, marca, status, origem, pluggy_transaction_id)
                           VALUES (%s, 'OUTRO', %s, %s, 'GERAL', 'a_confirmar', 'dda', %s)
                           ON CONFLICT (pluggy_transaction_id) DO NOTHING""",
                        (descricao, valor, data_tx, pluggy_id),
                    )
                    if rows_affected:
                        total_novos += 1

                paging = data.get("paging", {})
                if page * 500 >= paging.get("total", 0):
                    break
                page += 1

    return jsonify({"sincronizados": total_novos, "periodo": f"{from_date} → {to_date}"})
