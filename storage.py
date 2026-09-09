"""Cliente mínimo da REST do Supabase Storage para os anexos de fornecedores.

Sem SDK: são quatro chamadas HTTP e o `requests` já está no projeto. O bucket é
privado; a tela nunca recebe caminho, só URL assinada gerada no clique.
"""
import uuid
from datetime import datetime, timedelta, timezone

import requests

import config

BUCKET = "fornecedores"
EXTENSOES = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}
_PENDENTES_TTL = timedelta(hours=24)


class StorageErro(Exception):
    pass


def _base():
    return f"{config.SUPABASE_URL}/storage/v1"


def _headers(extra=None):
    # Os dois cabeçalhos, como em routes/usuarios.py: as chaves novas
    # (sb_secret_...) não são JWT, e sem o `apikey` o Storage tenta lê-las como
    # token e responde "Invalid Compact JWS".
    h = {
        "apikey": config.SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}",
    }
    if extra:
        h.update(extra)
    return h


def _checar(resp, acao):
    if not resp.ok:
        raise StorageErro(f"Storage: falha ao {acao} ({resp.status_code}): {resp.text[:200]}")


def enviar_pendente(dados: bytes, mime: str) -> str:
    """Sobe para pendentes/ e devolve o caminho — é o arquivo_token da tela."""
    ext = EXTENSOES.get(mime)
    if not ext:
        raise StorageErro(f"tipo de arquivo não aceito: {mime}")
    caminho = f"pendentes/{uuid.uuid4().hex}.{ext}"
    resp = requests.post(
        f"{_base()}/object/{BUCKET}/{caminho}",
        data=dados,
        headers=_headers({"Content-Type": mime, "x-upsert": "false"}),
        timeout=30,
    )
    _checar(resp, "enviar arquivo")
    return caminho


def mover(origem: str, destino: str) -> None:
    resp = requests.post(
        f"{_base()}/object/move",
        json={"bucketId": BUCKET, "sourceKey": origem, "destinationKey": destino},
        headers=_headers(),
        timeout=30,
    )
    _checar(resp, "mover arquivo")


def url_assinada(caminho: str, segundos: int = 3600) -> str:
    resp = requests.post(
        f"{_base()}/object/sign/{BUCKET}/{caminho}",
        json={"expiresIn": segundos},
        headers=_headers(),
        timeout=15,
    )
    _checar(resp, "assinar URL")
    return f"{_base()}{resp.json()['signedURL']}"


def limpar_pendentes(agora: datetime | None = None) -> int:
    """Apaga o que ficou em pendentes/ há mais de 24 h (upload sem salvar).

    Chamado no início de cada leitura — sem cron. Falha aqui não impede a
    leitura: quem chama decide engolir ou não.
    """
    agora = agora or datetime.now(timezone.utc)
    resp = requests.post(
        f"{_base()}/object/list/{BUCKET}",
        json={"prefix": "pendentes/", "limit": 1000, "offset": 0},
        headers=_headers(),
        timeout=15,
    )
    _checar(resp, "listar pendentes")
    velhos = []
    for obj in resp.json():
        try:
            criado = datetime.fromisoformat(obj["created_at"].replace("Z", "+00:00"))
        except (TypeError, ValueError, AttributeError, KeyError):
            continue
        if agora - criado > _PENDENTES_TTL:
            velhos.append(f"pendentes/{obj['name']}")
    if not velhos:
        return 0
    resp = requests.delete(
        f"{_base()}/object/{BUCKET}",
        json={"prefixes": velhos},
        headers=_headers(),
        timeout=30,
    )
    _checar(resp, "apagar pendentes")
    return len(velhos)
