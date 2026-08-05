import os
from dotenv import load_dotenv

load_dotenv(override=False)

DATABASE_URL = os.environ["DATABASE_URL"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
SECRET_KEY = os.environ["SECRET_KEY"]
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:5174,https://financeiro.sellerml.com.br"
).split(",")

MERCADO_PAGO_ACCESS_TOKEN = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN")

PLUGGY_CLIENT_ID = os.environ.get("PLUGGY_CLIENT_ID", "")
PLUGGY_CLIENT_SECRET = os.environ.get("PLUGGY_CLIENT_SECRET", "")
PLUGGY_REDIRECT_URL = os.environ.get(
    "PLUGGY_REDIRECT_URL",
    "https://financeiro.sellerml.com.br/api/pluggy/callback",
)
