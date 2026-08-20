import sys
import traceback
import jwt
from jwt import PyJWKClient
from functools import wraps
from flask import request, g, jsonify
import config
import db

_jwks_client = PyJWKClient(
    f"{config.SUPABASE_URL}/auth/v1/.well-known/jwks.json",
    lifespan=3600,
)


def verify_jwt(token: str) -> dict:
    signing_key = _jwks_client.get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256"],
        options={"verify_aud": False},
    )
    user_id = payload["sub"]
    email = payload.get("email", "")
    rows = db.query(
        "SELECT role FROM fin_user_roles WHERE user_id = %s", (user_id,)
    )
    fin_role = rows[0]["role"] if rows else None
    # conta_ml e admin vêm dos metadados do Supabase — MESMA fonte que o CRM usa.
    # Uma fonte só de verdade: mudar o acesso de alguém num lugar vale nos dois
    # sistemas, em vez de duas listas que divergem com o tempo.
    metadata = payload.get("user_metadata") or {}
    return {
        "user_id": user_id,
        "email": email,
        "fin_role": fin_role,
        "conta_ml": metadata.get("conta_ml"),
        "is_admin": metadata.get("role") == "admin",
    }


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token ausente"}), 401
        token = auth_header[7:]
        try:
            g.user = verify_jwt(token)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expirado"}), 401
        except Exception as e:
            print(f"[auth] ERRO ao verificar token: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            return jsonify({"error": "Token inválido"}), 401
        if g.user["fin_role"] is None:
            return jsonify({"error": "Acesso não autorizado ao painel financeiro"}), 403
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = getattr(g, "user", {})
        if user.get("fin_role") != "fin_admin":
            return jsonify({"error": "Apenas administradores podem executar esta ação"}), 403
        return f(*args, **kwargs)
    return decorated
