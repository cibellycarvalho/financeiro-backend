import jwt
from functools import wraps
from flask import request, g, jsonify
import db

# Chave pública EC do Supabase (ES256)
_PUBLIC_KEY = {
    "kty": "EC", "crv": "P-256",
    "kid": "79884884-90d1-43e7-a2e2-205c8eb32575",
    "x": "gJMVLZQ0J2Y6McnRxUzKE-izT6-PDMkU_K_SH-Mke8I",
    "y": "EJEk6L63Eqfe6FgHjPpgaULIZ-VY7pY58QmjgXTGzfE",
}
_ec_key = jwt.algorithms.ECAlgorithm.from_jwk(_PUBLIC_KEY)

def verify_jwt(token: str) -> dict:
    payload = jwt.decode(
        token, _ec_key,
        algorithms=["ES256"],
        options={"verify_aud": False}
    )
    user_id = payload["sub"]
    email = payload.get("email", "")
    rows = db.query(
        "SELECT role FROM fin_user_roles WHERE user_id = %s", (user_id,)
    )
    fin_role = rows[0]["role"] if rows else None
    return {"user_id": user_id, "email": email, "fin_role": fin_role}

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
        except Exception:
            return jsonify({"error": "Token inválido"}), 401
        if g.user["fin_role"] is None:
            return jsonify({"error": "Acesso não autorizado ao painel financeiro"}), 403
        return f(*args, **kwargs)
    return decorated

def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if g.user.get("fin_role") != "fin_admin":
            return jsonify({"error": "Apenas administradores podem executar esta ação"}), 403
        return f(*args, **kwargs)
    return decorated
