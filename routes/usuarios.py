from flask import Blueprint, request, jsonify, g
import db
import config
import requests as http
from auth import require_auth, require_admin

bp = Blueprint("usuarios", __name__)

@bp.get("")
@require_auth
@require_admin
def listar():
    rows = db.query("SELECT user_id, role, created_at FROM fin_user_roles ORDER BY created_at")
    return jsonify(rows)

@bp.post("")
@require_auth
@require_admin
def criar():
    data = request.get_json()
    email = data.get("email", "").strip()
    role = data.get("role", "fin_viewer")

    if not email:
        return jsonify({"error": "email obrigatório"}), 400
    if role not in ("fin_admin", "fin_viewer"):
        return jsonify({"error": "role inválido"}), 400

    resp = http.get(
        f"{config.SUPABASE_URL}/auth/v1/admin/users",
        headers={
            "apikey": config.SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}"
        },
        params={"email": email}
    )
    if resp.status_code != 200:
        return jsonify({"error": "Erro ao buscar usuário no Supabase"}), 502

    users = resp.json().get("users", [])
    if not users:
        return jsonify({"error": f"Usuário {email} não encontrado. Crie a conta primeiro no Supabase."}), 404

    user_id = users[0]["id"]
    db.execute(
        "INSERT INTO fin_user_roles (user_id, role) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET role = %s",
        (user_id, role, role)
    )
    return jsonify({"user_id": user_id, "email": email, "role": role}), 201
