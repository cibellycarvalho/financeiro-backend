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

# Leitura de documentos por IA (upload do pedido de compra). Sem chave, os
# endpoints /ler respondem 503 e o resto do sistema segue igual.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LEITURA_MODEL = os.environ.get("LEITURA_MODEL", "claude-opus-5")
