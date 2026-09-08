# Upload do pedido de compra — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dentro de um fornecedor, subir um pedido de compra (PDF/foto), conferir o que a IA leu, dizer se já foi pago (subindo o comprovante do Pix) e salvar pedido + pagamento com os arquivos anexados.

**Architecture:** Dois endpoints novos no `financeiro-backend` que só leem (`/pedidos/ler`, `/pagamentos/ler`): recebem o arquivo, sobem para `pendentes/` no Supabase Storage, chamam a API da Anthropic com saída em JSON Schema e devolvem um rascunho. Salvar continua nos endpoints existentes (`POST /pedidos`, `POST /pagamentos`), que ganham campos opcionais e movem o arquivo para a pasta definitiva dentro da transação. No frontend, um componente `UploadPedidoCompra` conduz o fluxo; a tabela de itens do "Novo pedido" vira componente compartilhado.

**Tech Stack:** Flask + psycopg2 (backend), `anthropic` (SDK Python, `client.messages.create` com `output_config.format` json_schema), `requests` contra a REST do Supabase Storage, React 18 + axios (frontend). Testes backend com pytest + fixtures gravadas; frontend por harness de preview (sem framework).

**Spec:** `docs/superpowers/specs/2026-09-08-upload-pedido-compra-design.md`

## Global Constraints

- Modelo da IA: `claude-opus-5` (default de `config.LEITURA_MODEL`; trocável por env sem deploy de código).
- Tipos aceitos: `application/pdf`, `image/jpeg`, `image/png`. Limite 10 MB, um arquivo por vez.
- A IA **nunca grava**. Só `POST /pedidos` e `POST /pagamentos` gravam, e só quando ela clica Salvar.
- `numero_pedido` não é único (só avisa). `id_transacao` é único parcial (avisa na tela; banco garante).
- Bucket `fornecedores` é privado; a tela só recebe URL assinada de 1 h, no clique.
- Nenhum PDF/comprovante real da Cibelly vai para o repositório — fixtures sintéticas.
- Commits em português, no padrão do repo (`feat:`, `fix:`, `docs:`, `test:`), com `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Backend na branch `feat/upload-pedido-compra` (já existe, com o spec). Frontend em branch de mesmo nome.
- Rodar testes com `venv/bin/python -m pytest tests -q` a partir de `/Users/macbookpro/Desktop/Claude/financeiro-backend`.

---

## Mapa de arquivos

**financeiro-backend**
- Create `supabase/migrations/20260908_upload_pedido_compra.sql` — colunas novas, tabela de aliases, bucket.
- Modify `config.py` — `ANTHROPIC_API_KEY`, `LEITURA_MODEL`.
- Modify `requirements.txt` — `anthropic`.
- Create `storage.py` — cliente REST do Supabase Storage (enviar pendente, mover, URL assinada, limpar pendentes).
- Create `leitura_documento.py` — chamada à IA + pós-processamento; exceções `LeituraIndisponivel` e `LeituraFalhou`.
- Create `aliases.py` — normalização, `sugerir_fornecedor`, `aprender_alias`.
- Modify `routes/fornecedores.py` — endpoints `/ler`, `/anexo`; campos novos em criar pedido / registrar pagamento.
- Create `tests/test_storage.py`, `tests/test_leitura_documento.py`, `tests/test_aliases.py`, `tests/test_fornecedores_upload.py`.
- Create `tests/fixtures/leitura_pedido_fl.json`, `tests/fixtures/leitura_comprovante_sicredi.json` — respostas gravadas (sintéticas).

**financeiro-frontend**
- Create `src/components/ItensPedidoForm.jsx` — tabela de itens editável (extraída do "Novo pedido").
- Create `src/components/UploadPedidoCompra.jsx` — o fluxo inteiro.
- Modify `src/pages/Fornecedores.jsx` — usa `ItensPedidoForm`, monta o botão de upload, 📎 nas linhas.

---

### Task 1: Migração, config e dependência

**Files:**
- Create: `supabase/migrations/20260908_upload_pedido_compra.sql`
- Modify: `config.py`
- Modify: `requirements.txt`
- Test: `tests/test_config_leitura.py`

**Interfaces:**
- Produces: `config.ANTHROPIC_API_KEY` (str ou `""`), `config.LEITURA_MODEL` (str, default `"claude-opus-5"`); tabela `fin_fornecedor_aliases`; colunas `fin_pedidos_fornecedor.numero_pedido/arquivo_path`, `fin_pagamentos_fornecedor.id_transacao/arquivo_path`; bucket `fornecedores`.

- [ ] **Step 1: Escrever a migração**

```sql
-- supabase/migrations/20260908_upload_pedido_compra.sql
-- Upload do pedido de compra com leitura por IA (spec 2026-09-08).

ALTER TABLE fin_pedidos_fornecedor
  ADD COLUMN numero_pedido TEXT,
  ADD COLUMN arquivo_path TEXT;
CREATE INDEX idx_pedidos_fornecedor_numero
  ON fin_pedidos_fornecedor(fornecedor_id, numero_pedido);

ALTER TABLE fin_pagamentos_fornecedor
  ADD COLUMN id_transacao TEXT,
  ADD COLUMN arquivo_path TEXT;
-- O mesmo comprovante não entra duas vezes por acidente: a tela avisa, o banco garante.
CREATE UNIQUE INDEX idx_pagamentos_fornecedor_id_transacao
  ON fin_pagamentos_fornecedor(id_transacao) WHERE id_transacao IS NOT NULL;

-- alias_norm é calculado em Python (minúsculas, sem acento, espaços colapsados).
-- unaccent() do Postgres não é imutável e por isso não entra em índice único.
CREATE TABLE fin_fornecedor_aliases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fornecedor_id UUID NOT NULL REFERENCES fin_fornecedores(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  origem TEXT NOT NULL CHECK (origem IN ('vendedor', 'destinatario')),
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX idx_fornecedor_aliases_norm
  ON fin_fornecedor_aliases(origem, alias_norm);
ALTER TABLE fin_fornecedor_aliases ENABLE ROW LEVEL SECURITY;

-- Semente: o que já se sabe da Flavia (card "FL") em 08/09/2026.
INSERT INTO fin_fornecedor_aliases (fornecedor_id, alias, alias_norm, origem)
SELECT f.id, v.alias, v.alias_norm, v.origem
FROM fin_fornecedores f
JOIN (VALUES
  ('Flavia', 'flavia', 'vendedor'),
  ('Multivale Montagem E Estruturas Ltda', 'multivale montagem e estruturas ltda', 'destinatario'),
  ('MIAO ATACADISTA E REPRESENTACOES LTDA', 'miao atacadista e representacoes ltda', 'destinatario')
) AS v(alias, alias_norm, origem) ON true
WHERE f.apelido = 'FL';

INSERT INTO storage.buckets (id, name, public)
VALUES ('fornecedores', 'fornecedores', false);
```

- [ ] **Step 2: Escrever o teste de config**

```python
# tests/test_config_leitura.py
import importlib


def test_config_leitura_tem_defaults(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LEITURA_MODEL", raising=False)
    import config
    importlib.reload(config)
    assert config.ANTHROPIC_API_KEY == ""
    assert config.LEITURA_MODEL == "claude-opus-5"


def test_config_leitura_le_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-teste")
    monkeypatch.setenv("LEITURA_MODEL", "claude-sonnet-5")
    import config
    importlib.reload(config)
    assert config.ANTHROPIC_API_KEY == "sk-teste"
    assert config.LEITURA_MODEL == "claude-sonnet-5"
```

- [ ] **Step 3: Rodar o teste e ver falhar**

Run: `venv/bin/python -m pytest tests/test_config_leitura.py -v`
Expected: FAIL — `AttributeError: module 'config' has no attribute 'ANTHROPIC_API_KEY'`

- [ ] **Step 4: Adicionar as duas variáveis em `config.py`** (no fim do arquivo)

```python
# Leitura de documentos por IA (upload do pedido de compra). Sem chave, os
# endpoints /ler respondem 503 e o resto do sistema segue igual.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LEITURA_MODEL = os.environ.get("LEITURA_MODEL", "claude-opus-5")
```

- [ ] **Step 5: Adicionar o SDK em `requirements.txt` e instalar**

Adicionar a linha `anthropic==1.4.0` (usar a última 1.x publicada em `pip index versions anthropic`; fixar a versão exata como as demais).

Run: `venv/bin/pip install -r requirements.txt`

- [ ] **Step 6: Rodar o teste e ver passar**

Run: `venv/bin/python -m pytest tests/test_config_leitura.py -v`
Expected: PASS (2 testes)

- [ ] **Step 7: Rodar a suíte inteira** (garantir que `reload(config)` não quebrou nada)

Run: `venv/bin/python -m pytest tests -q`
Expected: todos passando (77 anteriores + 2)

- [ ] **Step 8: Commit**

```bash
git add supabase/migrations/20260908_upload_pedido_compra.sql config.py requirements.txt tests/test_config_leitura.py
git commit -m "feat: migração, config e SDK para leitura de pedidos por IA

Colunas numero_pedido/arquivo_path e id_transacao/arquivo_path, tabela
fin_fornecedor_aliases (alias_norm calculado em Python — unaccent não
entra em índice único) e bucket privado 'fornecedores'.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Cliente do Supabase Storage (`storage.py`)

**Files:**
- Create: `storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `config.SUPABASE_URL`, `config.SUPABASE_SERVICE_KEY`.
- Produces:
  - `storage.BUCKET = "fornecedores"`
  - `storage.EXTENSOES = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}`
  - `storage.enviar_pendente(dados: bytes, mime: str) -> str` — devolve o caminho `pendentes/<hex>.<ext>` (é o `arquivo_token`).
  - `storage.mover(origem: str, destino: str) -> None`
  - `storage.url_assinada(caminho: str, segundos: int = 3600) -> str`
  - `storage.limpar_pendentes(agora: datetime | None = None) -> int` — apaga objetos de `pendentes/` com mais de 24 h; devolve quantos apagou.
  - `storage.StorageErro(Exception)`

- [ ] **Step 1: Escrever os testes**

```python
# tests/test_storage.py
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import storage


def _resp(status=200, json_data=None):
    r = MagicMock()
    r.status_code = status
    r.ok = status < 400
    r.json.return_value = json_data or {}
    r.text = ""
    return r


def test_enviar_pendente_sobe_para_pasta_pendentes(mocker):
    post = mocker.patch("storage.requests.post", return_value=_resp(200))
    caminho = storage.enviar_pendente(b"%PDF-1.4", "application/pdf")
    assert caminho.startswith("pendentes/") and caminho.endswith(".pdf")
    url = post.call_args.args[0]
    assert url.endswith(f"/storage/v1/object/fornecedores/{caminho}")
    headers = post.call_args.kwargs["headers"]
    assert headers["Content-Type"] == "application/pdf"
    assert headers["Authorization"].startswith("Bearer ")


def test_enviar_pendente_rejeita_mime_desconhecido():
    with pytest.raises(storage.StorageErro):
        storage.enviar_pendente(b"x", "text/plain")


def test_enviar_pendente_erro_http_vira_storage_erro(mocker):
    mocker.patch("storage.requests.post", return_value=_resp(500))
    with pytest.raises(storage.StorageErro):
        storage.enviar_pendente(b"x", "image/png")


def test_mover_chama_endpoint_move(mocker):
    post = mocker.patch("storage.requests.post", return_value=_resp(200))
    storage.mover("pendentes/a.pdf", "f1/pedidos/p1.pdf")
    assert post.call_args.args[0].endswith("/storage/v1/object/move")
    assert post.call_args.kwargs["json"] == {
        "bucketId": "fornecedores",
        "sourceKey": "pendentes/a.pdf",
        "destinationKey": "f1/pedidos/p1.pdf",
    }


def test_url_assinada_monta_url_completa(mocker):
    mocker.patch("storage.requests.post",
                 return_value=_resp(200, {"signedURL": "/object/sign/fornecedores/f1/pedidos/p1.pdf?token=abc"}))
    url = storage.url_assinada("f1/pedidos/p1.pdf")
    assert url.endswith("/storage/v1/object/sign/fornecedores/f1/pedidos/p1.pdf?token=abc")


def test_limpar_pendentes_apaga_so_os_velhos(mocker):
    agora = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    velho = (agora - timedelta(hours=30)).isoformat()
    novo = (agora - timedelta(hours=2)).isoformat()
    post = mocker.patch("storage.requests.post", return_value=_resp(200, [
        {"name": "velho.pdf", "created_at": velho},
        {"name": "novo.pdf", "created_at": novo},
    ]))
    delete = mocker.patch("storage.requests.delete", return_value=_resp(200))
    apagados = storage.limpar_pendentes(agora=agora)
    assert apagados == 1
    assert post.call_args.args[0].endswith("/storage/v1/object/list/fornecedores")
    assert delete.call_args.kwargs["json"] == {"prefixes": ["pendentes/velho.pdf"]}


def test_limpar_pendentes_sem_velhos_nao_chama_delete(mocker):
    agora = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)
    mocker.patch("storage.requests.post", return_value=_resp(200, [
        {"name": "novo.pdf", "created_at": (agora - timedelta(hours=1)).isoformat()},
    ]))
    delete = mocker.patch("storage.requests.delete")
    assert storage.limpar_pendentes(agora=agora) == 0
    delete.assert_not_called()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'storage'`

- [ ] **Step 3: Implementar `storage.py`**

```python
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
    h = {"Authorization": f"Bearer {config.SUPABASE_SERVICE_KEY}"}
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
        criado = datetime.fromisoformat(obj["created_at"].replace("Z", "+00:00"))
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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `venv/bin/python -m pytest tests/test_storage.py -v`
Expected: PASS (7 testes)

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage.py
git commit -m "feat: cliente REST do Supabase Storage para anexos de fornecedores

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Leitura por IA (`leitura_documento.py`)

**Files:**
- Create: `leitura_documento.py`
- Create: `tests/fixtures/leitura_pedido_fl.json`, `tests/fixtures/leitura_comprovante_sicredi.json`
- Test: `tests/test_leitura_documento.py`

**Interfaces:**
- Consumes: `config.ANTHROPIC_API_KEY`, `config.LEITURA_MODEL`.
- Produces:
  - `leitura_documento.LeituraIndisponivel(Exception)` — sem chave / API fora → HTTP 503.
  - `leitura_documento.LeituraFalhou(Exception)` — resposta inválida ou vazia → cartão vazio.
  - `leitura_documento.data_do_id_transacao(id_transacao: str | None) -> str | None` — `"AAAA-MM-DD"` ou `None`.
  - `leitura_documento.ler_pedido(dados: bytes, mime: str) -> dict` com chaves `texto_vendedor: str|None`, `numero_pedido: str|None`, `data_pedido: str|None`, `itens: list[{produto, quantidade, valor_unitario}]`, `total_documento: float|None`. Levanta `LeituraFalhou` se `itens` ficar vazio.
  - `leitura_documento.ler_comprovante(dados: bytes, mime: str) -> dict` com `valor: float`, `data_pagamento: str|None`, `destinatario: str|None`, `id_transacao: str|None`. Levanta `LeituraFalhou` se `valor` não for > 0.
  - `leitura_documento._chamar(dados, mime, instrucao, esquema) -> dict` — ponto único de contato com a API (o que os testes mockam).

- [ ] **Step 1: Criar as fixtures (sintéticas — nomes e números inventados)**

```json
// tests/fixtures/leitura_pedido_fl.json
{
  "texto_vendedor": "Flavia",
  "numero_pedido": "2026/9001",
  "data_pedido": "2026-09-01",
  "itens": [
    {"produto": "CABO HDMI FIBRA 8K 20M", "quantidade": 150, "valor_unitario": 100.0},
    {"produto": "EMENDA RJ45 EMBORRACHADO", "quantidade": 3000, "valor_unitario": 2.0},
    {"produto": "", "quantidade": 1, "valor_unitario": 5.0},
    {"produto": "ITEM SEM QUANTIDADE", "quantidade": 0, "valor_unitario": 9.0}
  ],
  "total_documento": 21000.0
}
```

```json
// tests/fixtures/leitura_comprovante_sicredi.json
{
  "valor": 30000.0,
  "data_pagamento": "2026-08-23",
  "destinatario": "MIAO ATACADISTA E REPRESENTACOES LTDA",
  "id_transacao": "E8109949120260824004025qquKDYh56"
}
```

- [ ] **Step 2: Escrever os testes**

```python
# tests/test_leitura_documento.py
import json
from pathlib import Path

import pytest

import leitura_documento as ld

FIX = Path(__file__).parent / "fixtures"


def _fixture(nome):
    return json.loads((FIX / nome).read_text())


# --- data_do_id_transacao ---------------------------------------------------

def test_data_do_id_transacao_le_data_do_e2e():
    assert ld.data_do_id_transacao("E8109949120260824004025qquKDYh56") == "2026-08-24"


def test_data_do_id_transacao_ignora_formato_estranho():
    assert ld.data_do_id_transacao("ABC123") is None
    assert ld.data_do_id_transacao(None) is None
    assert ld.data_do_id_transacao("") is None


# --- ler_pedido -------------------------------------------------------------

def test_ler_pedido_descarta_item_sem_produto_ou_sem_quantidade(mocker):
    mocker.patch("leitura_documento._chamar", return_value=_fixture("leitura_pedido_fl.json"))
    lido = ld.ler_pedido(b"%PDF", "application/pdf")
    assert [i["produto"] for i in lido["itens"]] == ["CABO HDMI FIBRA 8K 20M", "EMENDA RJ45 EMBORRACHADO"]
    assert lido["numero_pedido"] == "2026/9001"
    assert lido["data_pedido"] == "2026-09-01"
    assert lido["texto_vendedor"] == "Flavia"
    assert lido["total_documento"] == 21000.0


def test_ler_pedido_sem_itens_validos_levanta_leitura_falhou(mocker):
    mocker.patch("leitura_documento._chamar", return_value={"itens": [], "numero_pedido": None,
                                                              "data_pedido": None, "texto_vendedor": None,
                                                              "total_documento": None})
    with pytest.raises(ld.LeituraFalhou):
        ld.ler_pedido(b"%PDF", "application/pdf")


def test_ler_pedido_data_invalida_vira_none(mocker):
    dados = _fixture("leitura_pedido_fl.json")
    dados["data_pedido"] = "24/08/2026"
    mocker.patch("leitura_documento._chamar", return_value=dados)
    assert ld.ler_pedido(b"%PDF", "application/pdf")["data_pedido"] is None


# --- ler_comprovante --------------------------------------------------------

def test_ler_comprovante_data_vem_do_e2e_nao_da_ia(mocker):
    mocker.patch("leitura_documento._chamar", return_value=_fixture("leitura_comprovante_sicredi.json"))
    lido = ld.ler_comprovante(b"%PDF", "application/pdf")
    # a IA leu 23/08 (fuso), mas o E2E diz 24/08 00:40 — o E2E manda
    assert lido["data_pagamento"] == "2026-08-24"
    assert lido["valor"] == 30000.0
    assert lido["destinatario"] == "MIAO ATACADISTA E REPRESENTACOES LTDA"


def test_ler_comprovante_sem_e2e_mantem_data_da_ia(mocker):
    dados = _fixture("leitura_comprovante_sicredi.json")
    dados["id_transacao"] = None
    mocker.patch("leitura_documento._chamar", return_value=dados)
    assert ld.ler_comprovante(b"x", "image/png")["data_pagamento"] == "2026-08-23"


def test_ler_comprovante_valor_zero_levanta_leitura_falhou(mocker):
    dados = _fixture("leitura_comprovante_sicredi.json")
    dados["valor"] = 0
    mocker.patch("leitura_documento._chamar", return_value=dados)
    with pytest.raises(ld.LeituraFalhou):
        ld.ler_comprovante(b"x", "image/png")


# --- _chamar ----------------------------------------------------------------

def test_chamar_sem_chave_levanta_indisponivel(monkeypatch):
    monkeypatch.setattr("leitura_documento.config.ANTHROPIC_API_KEY", "")
    with pytest.raises(ld.LeituraIndisponivel):
        ld._chamar(b"x", "image/png", "instrucao", {"type": "object"})


def test_chamar_monta_bloco_document_para_pdf_e_image_para_foto(monkeypatch, mocker):
    monkeypatch.setattr("leitura_documento.config.ANTHROPIC_API_KEY", "sk-teste")
    client = mocker.MagicMock()
    bloco_texto = mocker.MagicMock(type="text", text='{"ok": true}')
    client.messages.create.return_value = mocker.MagicMock(stop_reason="end_turn", content=[bloco_texto])
    mocker.patch("leitura_documento.anthropic.Anthropic", return_value=client)

    ld._chamar(b"%PDF", "application/pdf", "instrucao", {"type": "object"})
    conteudo = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert conteudo[0]["type"] == "document"
    assert conteudo[0]["source"]["media_type"] == "application/pdf"
    assert client.messages.create.call_args.kwargs["output_config"]["format"]["type"] == "json_schema"

    ld._chamar(b"\x89PNG", "image/png", "instrucao", {"type": "object"})
    conteudo = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert conteudo[0]["type"] == "image"
    assert conteudo[0]["source"]["media_type"] == "image/png"


def test_chamar_recusa_vira_leitura_falhou(monkeypatch, mocker):
    monkeypatch.setattr("leitura_documento.config.ANTHROPIC_API_KEY", "sk-teste")
    client = mocker.MagicMock()
    client.messages.create.return_value = mocker.MagicMock(stop_reason="refusal", content=[])
    mocker.patch("leitura_documento.anthropic.Anthropic", return_value=client)
    with pytest.raises(ld.LeituraFalhou):
        ld._chamar(b"x", "image/png", "instrucao", {"type": "object"})


def test_chamar_erro_de_conexao_vira_indisponivel(monkeypatch, mocker):
    import anthropic
    monkeypatch.setattr("leitura_documento.config.ANTHROPIC_API_KEY", "sk-teste")
    client = mocker.MagicMock()
    client.messages.create.side_effect = anthropic.APIConnectionError(request=mocker.MagicMock())
    mocker.patch("leitura_documento.anthropic.Anthropic", return_value=client)
    with pytest.raises(ld.LeituraIndisponivel):
        ld._chamar(b"x", "image/png", "instrucao", {"type": "object"})
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_leitura_documento.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'leitura_documento'`

- [ ] **Step 4: Implementar `leitura_documento.py`**

```python
"""Leitura de pedido de compra e comprovante Pix por IA (visão).

Regra de ouro: tudo que dá para calcular, não se pergunta ao modelo. A data do
Pix Sicredi está no ID da transação; o total do pedido é a soma dos itens (a
tela recalcula). O modelo só transcreve.
"""
import base64
import json
import re
from datetime import date

import anthropic

import config


class LeituraIndisponivel(Exception):
    """Sem chave ou API fora do ar — a tela manda lançar à mão."""


class LeituraFalhou(Exception):
    """A IA respondeu, mas não deu para usar — a tela abre o cartão vazio."""


ESQUEMA_PEDIDO = {
    "type": "object",
    "properties": {
        "texto_vendedor": {"type": ["string", "null"],
                           "description": "Nome do vendedor/fornecedor como aparece no documento"},
        "numero_pedido": {"type": ["string", "null"]},
        "data_pedido": {"type": ["string", "null"], "description": "AAAA-MM-DD"},
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "produto": {"type": "string"},
                    "quantidade": {"type": "number"},
                    "valor_unitario": {"type": "number"},
                },
                "required": ["produto", "quantidade", "valor_unitario"],
                "additionalProperties": False,
            },
        },
        "total_documento": {"type": ["number", "null"]},
    },
    "required": ["texto_vendedor", "numero_pedido", "data_pedido", "itens", "total_documento"],
    "additionalProperties": False,
}

ESQUEMA_COMPROVANTE = {
    "type": "object",
    "properties": {
        "valor": {"type": "number"},
        "data_pagamento": {"type": ["string", "null"], "description": "AAAA-MM-DD"},
        "destinatario": {"type": ["string", "null"],
                         "description": "Nome de quem recebeu, como aparece no comprovante"},
        "id_transacao": {"type": ["string", "null"],
                         "description": "ID/E2E da transação Pix, exatamente como impresso"},
    },
    "required": ["valor", "data_pagamento", "destinatario", "id_transacao"],
    "additionalProperties": False,
}

INSTRUCAO_PEDIDO = (
    "Este é um pedido de compra de um fornecedor. Transcreva: o nome do vendedor "
    "ou fornecedor como está escrito, o número do pedido, a data do pedido "
    "(AAAA-MM-DD), cada item com produto, quantidade e valor unitário em reais, "
    "e o total do documento. Números no padrão brasileiro (1.000,50 = mil reais e "
    "cinquenta centavos). Não invente itens: se não estiver legível, deixe fora."
)

INSTRUCAO_COMPROVANTE = (
    "Este é um comprovante de pagamento Pix. Transcreva: o valor em reais, a data "
    "do pagamento (AAAA-MM-DD), o nome do destinatário como está escrito e o ID "
    "ou E2E da transação exatamente como impresso."
)

_RE_E2E = re.compile(r"^E\d{8}(\d{4})(\d{2})(\d{2})\d{6}")
_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def data_do_id_transacao(id_transacao):
    """Sicredi/Pix: 'E' + ISPB(8) + AAAAMMDDHHMMSS + sufixo. A data mora aqui."""
    if not id_transacao:
        return None
    m = _RE_E2E.match(id_transacao.strip())
    if not m:
        return None
    ano, mes, dia = (int(x) for x in m.groups())
    try:
        return date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def _data_ou_none(texto):
    if not texto or not _RE_DATA.match(texto):
        return None
    try:
        date.fromisoformat(texto)
    except ValueError:
        return None
    return texto


def _bloco_arquivo(dados, mime):
    b64 = base64.standard_b64encode(dados).decode("utf-8")
    if mime == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": mime, "data": b64}}
    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}


def _chamar(dados, mime, instrucao, esquema):
    """Único ponto que fala com a API. Os testes mockam esta função."""
    if not config.ANTHROPIC_API_KEY:
        raise LeituraIndisponivel("ANTHROPIC_API_KEY não configurada")
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    try:
        resp = client.messages.create(
            model=config.LEITURA_MODEL,
            max_tokens=16000,
            messages=[{"role": "user", "content": [_bloco_arquivo(dados, mime),
                                                   {"type": "text", "text": instrucao}]}],
            output_config={"format": {"type": "json_schema", "schema": esquema}},
        )
    except anthropic.AuthenticationError as e:
        raise LeituraIndisponivel(f"chave inválida: {e}") from e
    except anthropic.RateLimitError as e:
        raise LeituraIndisponivel(f"limite da API: {e}") from e
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            raise LeituraIndisponivel(f"API fora ({e.status_code})") from e
        raise LeituraFalhou(f"API recusou a requisição ({e.status_code})") from e
    except anthropic.APIConnectionError as e:
        raise LeituraIndisponivel(f"sem conexão com a API: {e}") from e

    if resp.stop_reason == "refusal":
        raise LeituraFalhou("modelo recusou o documento")
    texto = next((b.text for b in resp.content if b.type == "text"), None)
    if not texto:
        raise LeituraFalhou("resposta sem texto")
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        raise LeituraFalhou(f"resposta não é JSON: {e}") from e


def ler_pedido(dados, mime):
    bruto = _chamar(dados, mime, INSTRUCAO_PEDIDO, ESQUEMA_PEDIDO)
    itens = []
    for item in bruto.get("itens") or []:
        produto = (item.get("produto") or "").strip()
        try:
            quantidade = float(item.get("quantidade"))
            valor_unitario = float(item.get("valor_unitario"))
        except (TypeError, ValueError):
            continue
        if not produto or quantidade <= 0 or valor_unitario < 0:
            continue
        itens.append({"produto": produto, "quantidade": quantidade, "valor_unitario": valor_unitario})
    if not itens:
        raise LeituraFalhou("nenhum item legível")
    total = bruto.get("total_documento")
    return {
        "texto_vendedor": (bruto.get("texto_vendedor") or "").strip() or None,
        "numero_pedido": (bruto.get("numero_pedido") or "").strip() or None,
        "data_pedido": _data_ou_none(bruto.get("data_pedido")),
        "itens": itens,
        "total_documento": float(total) if isinstance(total, (int, float)) else None,
    }


def ler_comprovante(dados, mime):
    bruto = _chamar(dados, mime, INSTRUCAO_COMPROVANTE, ESQUEMA_COMPROVANTE)
    try:
        valor = float(bruto.get("valor"))
    except (TypeError, ValueError):
        valor = 0
    if valor <= 0:
        raise LeituraFalhou("valor do Pix não legível")
    id_transacao = (bruto.get("id_transacao") or "").strip() or None
    return {
        "valor": valor,
        "data_pagamento": data_do_id_transacao(id_transacao) or _data_ou_none(bruto.get("data_pagamento")),
        "destinatario": (bruto.get("destinatario") or "").strip() or None,
        "id_transacao": id_transacao,
    }
```

- [ ] **Step 5: Rodar e ver passar**

Run: `venv/bin/python -m pytest tests/test_leitura_documento.py -v`
Expected: PASS (12 testes)

- [ ] **Step 6: Commit**

```bash
git add leitura_documento.py tests/test_leitura_documento.py tests/fixtures/
git commit -m "feat: leitura de pedido e comprovante por IA com saída em JSON Schema

A data do Pix vem do ID da transação, não do que o modelo leu.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Aliases de fornecedor (`aliases.py`)

**Files:**
- Create: `aliases.py`
- Test: `tests/test_aliases.py`

**Interfaces:**
- Consumes: `db.query`, `db.execute`.
- Produces:
  - `aliases.normalizar(texto: str) -> str` — minúsculas, sem acento, espaços colapsados.
  - `aliases.sugerir_fornecedor(texto: str | None, origem: str) -> str | None` — `fornecedor_id` ou `None`.
  - `aliases.aprender_alias(fornecedor_id: str, texto: str | None, origem: str) -> None` — upsert; alias existente troca de dono.

- [ ] **Step 1: Escrever os testes**

```python
# tests/test_aliases.py
import aliases


def test_normalizar_tira_acento_caixa_e_espacos():
    assert aliases.normalizar("  Multivale   Montagem É Estruturas Ltda ") == "multivale montagem e estruturas ltda"
    assert aliases.normalizar("FLÁVIA") == "flavia"


def test_sugerir_fornecedor_usa_alias_norm(mocker):
    query = mocker.patch("aliases.db.query", return_value=[{"fornecedor_id": "f-1"}])
    assert aliases.sugerir_fornecedor("Flávia", "vendedor") == "f-1"
    sql, params = query.call_args.args
    assert "alias_norm = %s" in sql
    assert params == ("vendedor", "flavia")


def test_sugerir_fornecedor_sem_texto_nao_consulta(mocker):
    query = mocker.patch("aliases.db.query")
    assert aliases.sugerir_fornecedor(None, "vendedor") is None
    assert aliases.sugerir_fornecedor("   ", "destinatario") is None
    query.assert_not_called()


def test_sugerir_fornecedor_sem_match_devolve_none(mocker):
    mocker.patch("aliases.db.query", return_value=[])
    assert aliases.sugerir_fornecedor("Ninguem", "vendedor") is None


def test_aprender_alias_faz_upsert_trocando_dono(mocker):
    execute = mocker.patch("aliases.db.execute")
    aliases.aprender_alias("f-2", "MIAO Atacadista", "destinatario")
    sql, params = execute.call_args.args
    assert "ON CONFLICT (origem, alias_norm) DO UPDATE SET fornecedor_id = EXCLUDED.fornecedor_id" in sql
    assert params == ("f-2", "MIAO Atacadista", "miao atacadista", "destinatario")


def test_aprender_alias_sem_texto_nao_grava(mocker):
    execute = mocker.patch("aliases.db.execute")
    aliases.aprender_alias("f-2", "", "vendedor")
    execute.assert_not_called()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_aliases.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aliases'`

- [ ] **Step 3: Implementar `aliases.py`**

```python
"""Quem é o fornecedor deste documento?

Um alias liga o texto que aparece no documento ("Flavia" no pedido, "Multivale
Montagem E Estruturas Ltda" no Pix) a um fornecedor do painel. A lista aprende
sozinha: cada vez que ela salva, o texto lido vira alias do fornecedor escolhido.
Sem tela de administração — se um alias ficar errado, corrige-se no banco.
"""
import unicodedata

import db


def normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.lower().split())


def sugerir_fornecedor(texto, origem):
    if not texto or not texto.strip():
        return None
    rows = db.query(
        "SELECT fornecedor_id FROM fin_fornecedor_aliases WHERE origem = %s AND alias_norm = %s",
        (origem, normalizar(texto)),
    )
    return rows[0]["fornecedor_id"] if rows else None


def aprender_alias(fornecedor_id, texto, origem):
    if not texto or not texto.strip():
        return
    db.execute(
        """INSERT INTO fin_fornecedor_aliases (fornecedor_id, alias, alias_norm, origem)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (origem, alias_norm) DO UPDATE SET fornecedor_id = EXCLUDED.fornecedor_id""",
        (fornecedor_id, texto.strip(), normalizar(texto), origem),
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `venv/bin/python -m pytest tests/test_aliases.py -v`
Expected: PASS (6 testes)

- [ ] **Step 5: Commit**

```bash
git add aliases.py tests/test_aliases.py
git commit -m "feat: aliases de fornecedor que aprendem com o que ela salva

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Endpoint `POST /<id>/pedidos/ler`

**Files:**
- Modify: `routes/fornecedores.py` (adicionar imports e a rota, logo depois de `listar_pedidos`)
- Test: `tests/test_fornecedores_upload.py`

**Interfaces:**
- Consumes: `storage.enviar_pendente`, `storage.limpar_pendentes`, `storage.StorageErro`, `leitura_documento.ler_pedido`, `leitura_documento.LeituraIndisponivel/LeituraFalhou`, `aliases.sugerir_fornecedor`, `db.query`.
- Produces:
  - `routes.fornecedores._ler_arquivo_enviado() -> (bytes, mime, None) | (None, None, (resposta, status))` — validação compartilhada com a Task 6.
  - Resposta 200 do `/pedidos/ler` conforme o spec, mais `leitura_falhou: bool`. Quando `leitura_falhou` é `true`, só `arquivo_token` e `leitura_falhou` vêm preenchidos.
  - 400 arquivo ausente/tipo/tamanho; 503 `{"error": "Leitura automática indisponível agora. Lance à mão."}`.

- [ ] **Step 1: Escrever os testes**

```python
# tests/test_fornecedores_upload.py
import io

import pytest

import leitura_documento as ld
import storage

FORN = "11111111-1111-1111-1111-111111111111"
OUTRO = "22222222-2222-2222-2222-222222222222"

LIDO_PEDIDO = {
    "texto_vendedor": "Flavia",
    "numero_pedido": "2026/9001",
    "data_pedido": "2026-09-01",
    "itens": [{"produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10.0}],
    "total_documento": 20.0,
}


def _arquivo(nome="pedido.pdf", mime="application/pdf", conteudo=b"%PDF-1.4 fake"):
    return {"arquivo": (io.BytesIO(conteudo), nome, mime)}


@pytest.fixture(autouse=True)
def storage_mock(mocker):
    mocker.patch("routes.fornecedores.storage.limpar_pendentes", return_value=0)
    mocker.patch("routes.fornecedores.storage.enviar_pendente", return_value="pendentes/abc.pdf")


# --- POST /pedidos/ler ------------------------------------------------------

def test_ler_pedido_devolve_rascunho_com_sugestao_e_token(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", return_value=LIDO_PEDIDO)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=OUTRO)
    mocker.patch("routes.fornecedores.db.query", return_value=[])

    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["leitura_falhou"] is False
    assert corpo["fornecedor_sugerido_id"] == OUTRO
    assert corpo["texto_vendedor"] == "Flavia"
    assert corpo["numero_pedido"] == "2026/9001"
    assert corpo["itens"] == LIDO_PEDIDO["itens"]
    assert corpo["total_documento"] == 20.0
    assert corpo["pedido_existente"] is None
    assert corpo["arquivo_token"] == "pendentes/abc.pdf"


def test_ler_pedido_avisa_pedido_existente_no_mesmo_fornecedor(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", return_value=LIDO_PEDIDO)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=None)
    query = mocker.patch("routes.fornecedores.db.query",
                         return_value=[{"id": "p-1", "data_pedido": "2026-09-01"}])

    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.get_json()["pedido_existente"] == {"id": "p-1", "data_pedido": "2026-09-01"}
    assert query.call_args.args[1] == (FORN, "2026/9001")


def test_ler_pedido_leitura_falhou_devolve_token_e_flag(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", side_effect=ld.LeituraFalhou("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["leitura_falhou"] is True
    assert corpo["arquivo_token"] == "pendentes/abc.pdf"
    assert corpo["itens"] == []


def test_ler_pedido_api_indisponivel_503(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", side_effect=ld.LeituraIndisponivel("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 503
    assert "Lance à mão" in r.get_json()["error"]


def test_ler_pedido_sem_arquivo_400(client, admin_headers):
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data={},
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 400


def test_ler_pedido_tipo_nao_aceito_400(client, admin_headers, mocker):
    ler = mocker.patch("routes.fornecedores.leitura_documento.ler_pedido")
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler",
                    data=_arquivo("x.txt", "text/plain", b"oi"),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 400
    ler.assert_not_called()


def test_ler_pedido_maior_que_10mb_400(client, admin_headers, mocker):
    ler = mocker.patch("routes.fornecedores.leitura_documento.ler_pedido")
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler",
                    data=_arquivo(conteudo=b"x" * (10 * 1024 * 1024 + 1)),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 400
    ler.assert_not_called()


def test_ler_pedido_viewer_403(client, viewer_headers):
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=viewer_headers, content_type="multipart/form-data")
    assert r.status_code == 403


def test_ler_pedido_storage_falhou_no_envio_500_com_mensagem(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_pedido", return_value=LIDO_PEDIDO)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=None)
    mocker.patch("routes.fornecedores.db.query", return_value=[])
    mocker.patch("routes.fornecedores.storage.enviar_pendente", side_effect=storage.StorageErro("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pedidos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 500
    assert "arquivo" in r.get_json()["error"].lower()
```

Conferir como o `require_admin` do projeto responde para viewer (403) — abrir `auth.py` e, se for 401, ajustar o teste `test_ler_pedido_viewer_403` para o código que o projeto usa.

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_fornecedores_upload.py -v`
Expected: FAIL — 404 em todos (rota não existe); o de viewer também 404.

- [ ] **Step 3: Implementar a validação do arquivo e a rota** em `routes/fornecedores.py`

No topo do arquivo, junto dos imports existentes:

```python
import aliases
import leitura_documento
import storage
```

Logo depois de `listar_pedidos`:

```python
_TAMANHO_MAX = 10 * 1024 * 1024
MSG_LEITURA_INDISPONIVEL = "Leitura automática indisponível agora. Lance à mão."


def _ler_arquivo_enviado():
    """Valida o multipart 'arquivo'. Devolve (dados, mime, None) ou (None, None, (resposta, status))."""
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        return None, None, (jsonify({"error": "arquivo obrigatório"}), 400)
    mime = arquivo.mimetype
    if mime not in storage.EXTENSOES:
        return None, None, (jsonify({"error": "Só PDF, JPG ou PNG"}), 400)
    dados = arquivo.read()
    if len(dados) > _TAMANHO_MAX:
        return None, None, (jsonify({"error": "Arquivo maior que 10 MB"}), 400)
    return dados, mime, None


def _subir_pendente(dados, mime):
    """Limpa pendentes velhos e sobe o arquivo. Falha de limpeza não impede a leitura."""
    try:
        storage.limpar_pendentes()
    except storage.StorageErro:
        pass
    return storage.enviar_pendente(dados, mime)


@bp.post("/<fornecedor_id>/pedidos/ler")
@require_auth
@require_admin
def ler_pedido_arquivo(fornecedor_id):
    dados, mime, erro = _ler_arquivo_enviado()
    if erro:
        return erro

    try:
        lido = leitura_documento.ler_pedido(dados, mime)
    except leitura_documento.LeituraIndisponivel:
        return jsonify({"error": MSG_LEITURA_INDISPONIVEL}), 503
    except leitura_documento.LeituraFalhou:
        lido = None

    try:
        token = _subir_pendente(dados, mime)
    except storage.StorageErro:
        return jsonify({"error": "Não consegui guardar o arquivo. Tente de novo."}), 500

    if lido is None:
        return jsonify({
            "leitura_falhou": True, "arquivo_token": token,
            "fornecedor_sugerido_id": None, "texto_vendedor": None,
            "numero_pedido": None, "data_pedido": None, "itens": [],
            "total_documento": None, "pedido_existente": None,
        })

    existente = None
    if lido["numero_pedido"]:
        rows = db.query(
            """SELECT id, data_pedido FROM fin_pedidos_fornecedor
               WHERE fornecedor_id = %s AND numero_pedido = %s
               ORDER BY created_at DESC LIMIT 1""",
            (fornecedor_id, lido["numero_pedido"]),
        )
        if rows:
            existente = {"id": rows[0]["id"], "data_pedido": rows[0]["data_pedido"]}

    return jsonify({
        "leitura_falhou": False,
        "arquivo_token": token,
        "fornecedor_sugerido_id": aliases.sugerir_fornecedor(lido["texto_vendedor"], "vendedor"),
        "texto_vendedor": lido["texto_vendedor"],
        "numero_pedido": lido["numero_pedido"],
        "data_pedido": lido["data_pedido"],
        "itens": lido["itens"],
        "total_documento": lido["total_documento"],
        "pedido_existente": existente,
    })
```

Nota: `data_pedido` vindo do banco é `date`; o `jsonify` do Flask serializa como RFC 1123. O teste usa string porque o `db.query` está mockado. O frontend já trata os dois formatos (`formatData` / `mesDe` em UTC).

- [ ] **Step 4: Rodar e ver passar**

Run: `venv/bin/python -m pytest tests/test_fornecedores_upload.py -v`
Expected: PASS (9 testes)

- [ ] **Step 5: Rodar a suíte inteira**

Run: `venv/bin/python -m pytest tests -q`
Expected: tudo passando

- [ ] **Step 6: Commit**

```bash
git add routes/fornecedores.py tests/test_fornecedores_upload.py
git commit -m "feat: endpoint que lê um pedido de compra enviado (só leitura, não grava)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Endpoint `POST /<id>/pagamentos/ler`

**Files:**
- Modify: `routes/fornecedores.py` (logo depois de `listar_pagamentos`)
- Test: `tests/test_fornecedores_upload.py` (acrescentar)

**Interfaces:**
- Consumes: `_ler_arquivo_enviado`, `_subir_pendente`, `leitura_documento.ler_comprovante`, `aliases.sugerir_fornecedor`, `db.query`.
- Produces: resposta 200 conforme o spec: `valor`, `data_pagamento`, `destinatario`, `id_transacao`, `fornecedor_sugerido_id`, `pagamento_existente` (`{id, data_pagamento, valor}` ou `null`), `arquivo_token`, `leitura_falhou`.

- [ ] **Step 1: Acrescentar os testes** ao fim de `tests/test_fornecedores_upload.py`

```python
LIDO_COMPROVANTE = {
    "valor": 30000.0,
    "data_pagamento": "2026-08-24",
    "destinatario": "MIAO ATACADISTA E REPRESENTACOES LTDA",
    "id_transacao": "E8109949120260824004025qquKDYh56",
}


# --- POST /pagamentos/ler ---------------------------------------------------

def test_ler_comprovante_devolve_rascunho(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_comprovante", return_value=LIDO_COMPROVANTE)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=FORN)
    mocker.patch("routes.fornecedores.db.query", return_value=[])

    r = client.post(f"/api/fornecedores/{FORN}/pagamentos/ler", data=_arquivo("pix.png", "image/png", b"\x89PNG"),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 200
    corpo = r.get_json()
    assert corpo["leitura_falhou"] is False
    assert corpo["valor"] == 30000.0
    assert corpo["data_pagamento"] == "2026-08-24"
    assert corpo["destinatario"] == LIDO_COMPROVANTE["destinatario"]
    assert corpo["id_transacao"] == LIDO_COMPROVANTE["id_transacao"]
    assert corpo["fornecedor_sugerido_id"] == FORN
    assert corpo["pagamento_existente"] is None
    assert corpo["arquivo_token"] == "pendentes/abc.pdf"


def test_ler_comprovante_avisa_e2e_ja_lancado(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_comprovante", return_value=LIDO_COMPROVANTE)
    mocker.patch("routes.fornecedores.aliases.sugerir_fornecedor", return_value=None)
    query = mocker.patch("routes.fornecedores.db.query",
                         return_value=[{"id": "pg-1", "data_pagamento": "2026-08-24", "valor": 30000.0}])
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.get_json()["pagamento_existente"] == {"id": "pg-1", "data_pagamento": "2026-08-24", "valor": 30000.0}
    assert query.call_args.args[1] == (LIDO_COMPROVANTE["id_transacao"],)


def test_ler_comprovante_leitura_falhou_devolve_token(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_comprovante", side_effect=ld.LeituraFalhou("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["leitura_falhou"] is True
    assert r.get_json()["arquivo_token"] == "pendentes/abc.pdf"


def test_ler_comprovante_api_indisponivel_503(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.leitura_documento.ler_comprovante", side_effect=ld.LeituraIndisponivel("x"))
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos/ler", data=_arquivo(),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 503
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_fornecedores_upload.py -k comprovante -v`
Expected: FAIL — 404

- [ ] **Step 3: Implementar a rota** (depois de `listar_pagamentos`)

```python
@bp.post("/<fornecedor_id>/pagamentos/ler")
@require_auth
@require_admin
def ler_comprovante_arquivo(fornecedor_id):
    dados, mime, erro = _ler_arquivo_enviado()
    if erro:
        return erro

    try:
        lido = leitura_documento.ler_comprovante(dados, mime)
    except leitura_documento.LeituraIndisponivel:
        return jsonify({"error": MSG_LEITURA_INDISPONIVEL}), 503
    except leitura_documento.LeituraFalhou:
        lido = None

    try:
        token = _subir_pendente(dados, mime)
    except storage.StorageErro:
        return jsonify({"error": "Não consegui guardar o arquivo. Tente de novo."}), 500

    if lido is None:
        return jsonify({
            "leitura_falhou": True, "arquivo_token": token,
            "valor": None, "data_pagamento": None, "destinatario": None,
            "id_transacao": None, "fornecedor_sugerido_id": None, "pagamento_existente": None,
        })

    existente = None
    if lido["id_transacao"]:
        rows = db.query(
            "SELECT id, data_pagamento, valor FROM fin_pagamentos_fornecedor WHERE id_transacao = %s",
            (lido["id_transacao"],),
        )
        if rows:
            existente = {"id": rows[0]["id"], "data_pagamento": rows[0]["data_pagamento"],
                         "valor": float(rows[0]["valor"])}

    return jsonify({
        "leitura_falhou": False,
        "arquivo_token": token,
        "valor": lido["valor"],
        "data_pagamento": lido["data_pagamento"],
        "destinatario": lido["destinatario"],
        "id_transacao": lido["id_transacao"],
        "fornecedor_sugerido_id": aliases.sugerir_fornecedor(lido["destinatario"], "destinatario"),
        "pagamento_existente": existente,
    })
```

- [ ] **Step 4: Rodar e ver passar**

Run: `venv/bin/python -m pytest tests/test_fornecedores_upload.py -v`
Expected: PASS (13 testes)

- [ ] **Step 5: Commit**

```bash
git add routes/fornecedores.py tests/test_fornecedores_upload.py
git commit -m "feat: endpoint que lê um comprovante Pix enviado

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Salvar pedido com número, anexo e alias

**Files:**
- Modify: `routes/fornecedores.py` — função `criar_pedido`, e `listar_pedidos` (SELECT já é `p.*`, então `numero_pedido` e `arquivo_path` saem sozinhos — nada a mudar ali)
- Test: `tests/test_fornecedores_upload.py` (acrescentar)

**Interfaces:**
- Consumes: `storage.mover`, `aliases.aprender_alias`, `db.transaction`.
- Produces: `POST /<id>/pedidos` aceita `numero_pedido` (str, opcional), `arquivo_token` (str, opcional), `alias_vendedor` (str, opcional). Grava `numero_pedido`; se `arquivo_token`, move para `<fornecedor_id>/pedidos/<pedido_id>.<ext>` **dentro da transação** e grava `arquivo_path`; se `alias_vendedor`, aprende o alias depois do commit.

- [ ] **Step 1: Ver como os testes existentes de `criar_pedido` mockam a transação**

Run: `grep -n "transaction\|cur\b" tests/test_fornecedores.py | head -20`

Copiar o mesmo padrão de mock de `db.transaction` (um `MagicMock` cujo `__enter__` devolve um cursor com `fetchone` sequenciado) nos testes abaixo. Se o arquivo usa um helper (por exemplo `_cursor_fake`), reutilizar.

- [ ] **Step 2: Acrescentar os testes**

```python
from contextlib import contextmanager
from unittest.mock import MagicMock


def _transacao_fake(mocker, retornos):
    """db.transaction() cujo cursor devolve `retornos` em sequência no fetchone()."""
    cur = MagicMock()
    cur.fetchone.side_effect = retornos

    @contextmanager
    def _tx():
        yield cur

    mocker.patch("routes.fornecedores.db.transaction", _tx)
    return cur


PEDIDO_NOVO = {"id": "p-9", "fornecedor_id": FORN, "data_pedido": "2026-09-01", "valor_total": 20.0}
ITEM_NOVO = {"id": "i-1", "pedido_id": "p-9", "produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10.0}


# --- POST /pedidos com campos novos ----------------------------------------

def test_criar_pedido_grava_numero_move_anexo_e_aprende_alias(client, admin_headers, mocker):
    cur = _transacao_fake(mocker, [PEDIDO_NOVO, ITEM_NOVO])
    mover = mocker.patch("routes.fornecedores.storage.mover")
    aprender = mocker.patch("routes.fornecedores.aliases.aprender_alias")

    r = client.post(f"/api/fornecedores/{FORN}/pedidos", json={
        "data_pedido": "2026-09-01",
        "itens": [{"produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10}],
        "numero_pedido": "2026/9001",
        "arquivo_token": "pendentes/abc.pdf",
        "alias_vendedor": "Flavia",
    }, headers=admin_headers)
    assert r.status_code == 201

    insert_sql, insert_params = cur.execute.call_args_list[0].args
    assert "numero_pedido" in insert_sql
    assert "2026/9001" in insert_params

    mover.assert_called_once_with("pendentes/abc.pdf", f"{FORN}/pedidos/p-9.pdf")
    update_sql, update_params = cur.execute.call_args_list[-1].args
    assert "arquivo_path" in update_sql
    assert update_params == (f"{FORN}/pedidos/p-9.pdf", "p-9")

    aprender.assert_called_once_with(FORN, "Flavia", "vendedor")
    assert r.get_json()["arquivo_path"] == f"{FORN}/pedidos/p-9.pdf"


def test_criar_pedido_sem_campos_novos_continua_igual(client, admin_headers, mocker):
    cur = _transacao_fake(mocker, [PEDIDO_NOVO, ITEM_NOVO])
    mover = mocker.patch("routes.fornecedores.storage.mover")
    aprender = mocker.patch("routes.fornecedores.aliases.aprender_alias")
    r = client.post(f"/api/fornecedores/{FORN}/pedidos", json={
        "data_pedido": "2026-09-01",
        "itens": [{"produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10}],
    }, headers=admin_headers)
    assert r.status_code == 201
    mover.assert_not_called()
    aprender.assert_not_called()


def test_criar_pedido_storage_falhou_nao_grava(client, admin_headers, mocker):
    _transacao_fake(mocker, [PEDIDO_NOVO, ITEM_NOVO])
    mocker.patch("routes.fornecedores.storage.mover", side_effect=storage.StorageErro("x"))
    aprender = mocker.patch("routes.fornecedores.aliases.aprender_alias")
    r = client.post(f"/api/fornecedores/{FORN}/pedidos", json={
        "data_pedido": "2026-09-01",
        "itens": [{"produto": "CABO HDMI", "quantidade": 2, "valor_unitario": 10}],
        "arquivo_token": "pendentes/abc.pdf",
    }, headers=admin_headers)
    assert r.status_code == 500
    assert "anexo" in r.get_json()["error"].lower()
    aprender.assert_not_called()
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_fornecedores_upload.py -k criar_pedido -v`
Expected: FAIL — `mover` não chamado / `numero_pedido` ausente do INSERT.

- [ ] **Step 4: Alterar `criar_pedido`**

Substituir o corpo a partir de `valor_total = ...` por:

```python
    valor_total = sum(quantidade * valor_unitario for _, quantidade, valor_unitario in itens_validados)
    numero_pedido = (data.get("numero_pedido") or "").strip() or None
    arquivo_token = (data.get("arquivo_token") or "").strip() or None
    alias_vendedor = data.get("alias_vendedor")

    try:
        with db.transaction() as cur:
            cur.execute(
                """INSERT INTO fin_pedidos_fornecedor
                   (fornecedor_id, data_pedido, valor_total, observacao, numero_pedido, criado_por)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (fornecedor_id, data["data_pedido"], valor_total, data.get("observacao"),
                 numero_pedido, g.user["user_id"])
            )
            pedido = dict(cur.fetchone())

            itens_criados = []
            for produto, quantidade, valor_unitario in itens_validados:
                cur.execute(
                    """INSERT INTO fin_pedido_itens (pedido_id, produto, quantidade, valor_unitario)
                       VALUES (%s, %s, %s, %s)
                       RETURNING *""",
                    (pedido["id"], produto, quantidade, valor_unitario)
                )
                itens_criados.append(dict(cur.fetchone()))

            # O anexo move dentro da transação: se o Storage falhar, nada é gravado.
            if arquivo_token:
                destino = _destino_anexo(fornecedor_id, "pedidos", pedido["id"], arquivo_token)
                storage.mover(arquivo_token, destino)
                cur.execute(
                    "UPDATE fin_pedidos_fornecedor SET arquivo_path = %s WHERE id = %s",
                    (destino, pedido["id"])
                )
                pedido["arquivo_path"] = destino
    except storage.StorageErro:
        return jsonify({"error": "Não consegui guardar o anexo; o pedido não foi salvo. Tente de novo."}), 500

    if alias_vendedor:
        aliases.aprender_alias(fornecedor_id, alias_vendedor, "vendedor")

    pedido["itens"] = itens_criados
    return jsonify(pedido), 201
```

E, junto dos helpers (`_ler_arquivo_enviado`), adicionar:

```python
def _destino_anexo(fornecedor_id, pasta, registro_id, arquivo_token):
    ext = arquivo_token.rsplit(".", 1)[-1]
    return f"{fornecedor_id}/{pasta}/{registro_id}.{ext}"
```

- [ ] **Step 5: Rodar e ver passar; rodar a suíte inteira** (os testes antigos de `criar_pedido` em `test_fornecedores.py` precisam continuar verdes)

Run: `venv/bin/python -m pytest tests -q`
Expected: tudo passando. Se algum teste antigo conferir a tupla exata do INSERT, atualizar a expectativa para incluir `numero_pedido` (`None`) na 5ª posição.

- [ ] **Step 6: Commit**

```bash
git add routes/fornecedores.py tests/test_fornecedores_upload.py tests/test_fornecedores.py
git commit -m "feat: pedido salva número, anexo (dentro da transação) e aprende alias do vendedor

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: Salvar pagamento com E2E, anexo e alias; endpoints `/anexo`

**Files:**
- Modify: `routes/fornecedores.py` — `registrar_pagamento`; rotas novas `GET /<id>/pedidos/<pid>/anexo` e `GET /<id>/pagamentos/<pgid>/anexo`
- Test: `tests/test_fornecedores_upload.py` (acrescentar)

**Interfaces:**
- Consumes: `storage.mover`, `storage.url_assinada`, `aliases.aprender_alias`, `_destino_anexo`.
- Produces:
  - `POST /<id>/pagamentos` aceita `id_transacao`, `arquivo_token`, `alias_destinatario` (opcionais). 409 `{"error": "Esse comprovante já foi lançado em DD/MM/AAAA (R$ X)"}` se `id_transacao` já existir.
  - `GET /<id>/pedidos/<pid>/anexo` → `{"url": ...}`; 404 se o pedido não tem anexo.
  - `GET /<id>/pagamentos/<pgid>/anexo` → idem.

- [ ] **Step 1: Acrescentar os testes**

```python
PAGAMENTO_NOVO = {"id": "pg-9", "fornecedor_id": FORN, "valor": 30000.0, "data_pagamento": "2026-08-24"}


def _saldo(mocker, valor):
    mocker.patch("routes.fornecedores._saldo_aberto_fornecedor", return_value=valor)


# --- POST /pagamentos com campos novos -------------------------------------

def test_registrar_pagamento_grava_e2e_move_anexo_e_aprende_alias(client, admin_headers, mocker):
    _saldo(mocker, 100000.0)
    query = mocker.patch("routes.fornecedores.db.query")
    # 1ª: fornecedor existe; 2ª: nenhum pagamento com esse E2E
    query.side_effect = [[{"id": FORN}], []]
    execute = mocker.patch("routes.fornecedores.db.execute")
    execute.side_effect = [dict(PAGAMENTO_NOVO), {**PAGAMENTO_NOVO, "arquivo_path": f"{FORN}/pagamentos/pg-9.pdf"}]
    mover = mocker.patch("routes.fornecedores.storage.mover")
    aprender = mocker.patch("routes.fornecedores.aliases.aprender_alias")

    r = client.post(f"/api/fornecedores/{FORN}/pagamentos", json={
        "valor": 30000, "data_pagamento": "2026-08-24",
        "id_transacao": "E8109949120260824004025qquKDYh56",
        "arquivo_token": "pendentes/abc.pdf",
        "alias_destinatario": "MIAO ATACADISTA E REPRESENTACOES LTDA",
    }, headers=admin_headers)
    assert r.status_code == 201
    insert_sql, insert_params = execute.call_args_list[0].args
    assert "id_transacao" in insert_sql
    assert "E8109949120260824004025qquKDYh56" in insert_params
    mover.assert_called_once_with("pendentes/abc.pdf", f"{FORN}/pagamentos/pg-9.pdf")
    aprender.assert_called_once_with(FORN, "MIAO ATACADISTA E REPRESENTACOES LTDA", "destinatario")
    assert r.get_json()["arquivo_path"] == f"{FORN}/pagamentos/pg-9.pdf"


def test_registrar_pagamento_e2e_repetido_409(client, admin_headers, mocker):
    _saldo(mocker, 100000.0)
    query = mocker.patch("routes.fornecedores.db.query")
    query.side_effect = [[{"id": FORN}], [{"id": "pg-1", "data_pagamento": "2026-08-24", "valor": 30000.0}]]
    execute = mocker.patch("routes.fornecedores.db.execute")
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos", json={
        "valor": 30000, "data_pagamento": "2026-08-24",
        "id_transacao": "E8109949120260824004025qquKDYh56",
    }, headers=admin_headers)
    assert r.status_code == 409
    assert "já foi lançado" in r.get_json()["error"]
    execute.assert_not_called()


def test_registrar_pagamento_sem_campos_novos_continua_igual(client, admin_headers, mocker):
    _saldo(mocker, 100000.0)
    mocker.patch("routes.fornecedores.db.query", return_value=[{"id": FORN}])
    mocker.patch("routes.fornecedores.db.execute", return_value=dict(PAGAMENTO_NOVO))
    mover = mocker.patch("routes.fornecedores.storage.mover")
    r = client.post(f"/api/fornecedores/{FORN}/pagamentos",
                    json={"valor": 30000, "data_pagamento": "2026-08-24"}, headers=admin_headers)
    assert r.status_code == 201
    mover.assert_not_called()


# --- GET .../anexo ----------------------------------------------------------

def test_anexo_pedido_devolve_url_assinada(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.db.query", return_value=[{"arquivo_path": f"{FORN}/pedidos/p-1.pdf"}])
    mocker.patch("routes.fornecedores.storage.url_assinada", return_value="https://x/assinada")
    r = client.get(f"/api/fornecedores/{FORN}/pedidos/p-1/anexo", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json() == {"url": "https://x/assinada"}


def test_anexo_pedido_sem_arquivo_404(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.db.query", return_value=[{"arquivo_path": None}])
    r = client.get(f"/api/fornecedores/{FORN}/pedidos/p-1/anexo", headers=admin_headers)
    assert r.status_code == 404


def test_anexo_pagamento_devolve_url_assinada(client, admin_headers, mocker):
    query = mocker.patch("routes.fornecedores.db.query", return_value=[{"arquivo_path": f"{FORN}/pagamentos/pg-1.png"}])
    mocker.patch("routes.fornecedores.storage.url_assinada", return_value="https://x/assinada2")
    r = client.get(f"/api/fornecedores/{FORN}/pagamentos/pg-1/anexo", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json() == {"url": "https://x/assinada2"}
    assert "fin_pagamentos_fornecedor" in query.call_args.args[0]


def test_anexo_viewer_pode_ver(client, viewer_headers, mocker):
    mocker.patch("routes.fornecedores.db.query", return_value=[{"arquivo_path": f"{FORN}/pedidos/p-1.pdf"}])
    mocker.patch("routes.fornecedores.storage.url_assinada", return_value="https://x/assinada")
    r = client.get(f"/api/fornecedores/{FORN}/pedidos/p-1/anexo", headers=viewer_headers)
    assert r.status_code == 200
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_fornecedores_upload.py -k "registrar_pagamento or anexo" -v`
Expected: FAIL (INSERT sem `id_transacao`; rotas `/anexo` 404)

- [ ] **Step 3: Alterar `registrar_pagamento`**

Substituir a partir de `saldo_aberto = _saldo_aberto_fornecedor(fornecedor_id)`:

```python
    saldo_aberto = _saldo_aberto_fornecedor(fornecedor_id)
    if valor > saldo_aberto:
        return jsonify({"error": f"Valor maior que o saldo em aberto (R$ {saldo_aberto:.2f})"}), 400

    id_transacao = (data.get("id_transacao") or "").strip() or None
    arquivo_token = (data.get("arquivo_token") or "").strip() or None
    alias_destinatario = data.get("alias_destinatario")

    # Checagem antes do INSERT para responder 409 com mensagem; o índice único
    # parcial no banco segue como garantia final.
    if id_transacao:
        repetidos = db.query(
            "SELECT id, data_pagamento, valor FROM fin_pagamentos_fornecedor WHERE id_transacao = %s",
            (id_transacao,)
        )
        if repetidos:
            quando = repetidos[0]["data_pagamento"]
            quando = quando.strftime("%d/%m/%Y") if hasattr(quando, "strftime") else quando
            return jsonify({"error": f"Esse comprovante já foi lançado em {quando} "
                                     f"(R$ {float(repetidos[0]['valor']):.2f})"}), 409

    row = db.execute(
        """INSERT INTO fin_pagamentos_fornecedor (fornecedor_id, valor, data_pagamento, id_transacao, criado_por)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING *""",
        (fornecedor_id, valor, data["data_pagamento"], id_transacao, g.user["user_id"])
    )

    if arquivo_token:
        destino = _destino_anexo(fornecedor_id, "pagamentos", row["id"], arquivo_token)
        try:
            storage.mover(arquivo_token, destino)
        except storage.StorageErro:
            # O pagamento já está gravado (é db.execute, não transação): não
            # desfazer — ela vê o pagamento sem clipe e pode subir de novo depois.
            row["arquivo_path"] = None
            row["aviso"] = "Pagamento salvo, mas o anexo não pôde ser guardado."
            return jsonify(row), 201
        row = db.execute(
            "UPDATE fin_pagamentos_fornecedor SET arquivo_path = %s WHERE id = %s RETURNING *",
            (destino, row["id"])
        )

    if alias_destinatario:
        aliases.aprender_alias(fornecedor_id, alias_destinatario, "destinatario")

    return jsonify(row), 201
```

Nota de desenho: o spec diz "tudo ou nada" no Storage. Em `criar_pedido` isso vale porque já há transação. Aqui o pagamento é um `db.execute` só; trocar por transação para cobrir um caso raro não vale o risco de mexer no que já funciona — o aviso na resposta cobre.

- [ ] **Step 4: Adicionar as rotas de anexo** (depois de `excluir_pagamento`)

```python
def _url_anexo(tabela, registro_id, fornecedor_id):
    rows = db.query(
        f"SELECT arquivo_path FROM {tabela} WHERE id = %s AND fornecedor_id = %s",
        (registro_id, fornecedor_id)
    )
    if not rows or not rows[0]["arquivo_path"]:
        return jsonify({"error": "Sem anexo"}), 404
    try:
        return jsonify({"url": storage.url_assinada(rows[0]["arquivo_path"])})
    except storage.StorageErro:
        return jsonify({"error": "Não consegui abrir o anexo agora. Tente de novo."}), 500


@bp.get("/<fornecedor_id>/pedidos/<pedido_id>/anexo")
@require_auth
def anexo_pedido(fornecedor_id, pedido_id):
    return _url_anexo("fin_pedidos_fornecedor", pedido_id, fornecedor_id)


@bp.get("/<fornecedor_id>/pagamentos/<pagamento_id>/anexo")
@require_auth
def anexo_pagamento(fornecedor_id, pagamento_id):
    return _url_anexo("fin_pagamentos_fornecedor", pagamento_id, fornecedor_id)
```

(`tabela` é constante do código, nunca entrada do usuário — o f-string é seguro.)

- [ ] **Step 5: Rodar tudo e ver passar**

Run: `venv/bin/python -m pytest tests -q`
Expected: tudo passando. Se algum teste antigo de `registrar_pagamento` em `test_fornecedores.py` conferir a tupla exata do INSERT ou a contagem de `db.query`, ajustar (agora há `id_transacao` como 4º parâmetro e, quando informado, uma consulta a mais).

- [ ] **Step 6: Commit**

```bash
git add routes/fornecedores.py tests/test_fornecedores_upload.py tests/test_fornecedores.py
git commit -m "feat: pagamento salva E2E (409 se repetido), anexo e alias; endpoints de anexo assinado

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Aplicar migração, criar bucket e configurar o EasyPanel

**Files:** nenhum no repo (operação).

**Interfaces:**
- Produces: banco de produção com as colunas/tabela/bucket; `ANTHROPIC_API_KEY` e (opcional) `LEITURA_MODEL` no serviço `financeiro-backend` do EasyPanel.

- [ ] **Step 1: Aplicar a migração no Supabase**

Usar a ferramenta MCP do Supabase (`apply_migration`, projeto `tywirfmaosfztcmalbno`, nome `upload_pedido_compra`) com o conteúdo de `supabase/migrations/20260908_upload_pedido_compra.sql`. Se a MCP não estiver disponível, colar no SQL Editor do painel do Supabase.

- [ ] **Step 2: Conferir**

SQL:
```sql
SELECT column_name FROM information_schema.columns
WHERE table_name IN ('fin_pedidos_fornecedor','fin_pagamentos_fornecedor')
  AND column_name IN ('numero_pedido','arquivo_path','id_transacao');
SELECT alias, origem FROM fin_fornecedor_aliases;
SELECT id, public FROM storage.buckets WHERE id = 'fornecedores';
```
Expected: 4 colunas, 3 aliases da Flavia, bucket privado.

- [ ] **Step 3: Chave da Anthropic no EasyPanel**

Pedir à Cibelly a chave (ou usar a mesma do CRM, se ela autorizar) e adicionar `ANTHROPIC_API_KEY` nas variáveis de ambiente do serviço `financeiro-backend` no EasyPanel. **Não** colocar a chave em arquivo do repo nem no chat. Salvar e deixar o serviço reiniciar.

- [ ] **Step 4: Verificar no ar**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://financeiro.cravelli.com.br/api/fornecedores
```
Expected: `401` (backend de pé). Sem token não dá para testar `/ler` por curl — fica para o smoke test da Task 13.

---

### Task 10 (frontend): Extrair `ItensPedidoForm`

**Files:**
- Create: `src/components/ItensPedidoForm.jsx`
- Modify: `src/pages/Fornecedores.jsx` — o bloco `<div>` com "Itens do pedido" dentro do `<form onSubmit={handleSubmit}>`, e as funções `atualizarItem`, `adicionarItem`, `removerItem`, `totalDoItem`, `totalDoPedido`, `ITEM_VAZIO`.

**Interfaces:**
- Produces: `ItensPedidoForm({ itens, onChange })` — `itens` é `[{produto, quantidade, valor_unitario}]` (strings ou números); `onChange(novosItens)`. Exporta também `ITEM_VAZIO` e `totalDosItens(itens) -> number`.
- Comportamento idêntico ao atual: grid `2fr 1fr 1fr 1fr auto`, "+ Adicionar produto", ✕ desabilitado quando só há 1 linha, "Total do pedido".

- [ ] **Step 1: Criar a branch no frontend**

```bash
cd /Users/macbookpro/Desktop/Claude/financeiro-frontend
git checkout main && git pull -q && git checkout -b feat/upload-pedido-compra
```

- [ ] **Step 2: Criar o componente**

```jsx
// src/components/ItensPedidoForm.jsx
// Tabela de itens de um pedido — usada pelo "Novo pedido" e pelo upload do
// pedido de compra. Um lugar só para manter aparência e validação.

export const ITEM_VAZIO = { produto: '', quantidade: '', valor_unitario: '' }

const inputStyle = { display: 'block', width: '100%', padding: 8, marginTop: 4, borderRadius: 'var(--radius-sm)', border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', boxSizing: 'border-box' }

function formatMoeda(valor) {
  return Number(valor || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}

export function totalDoItem(item) {
  return (parseFloat(item.quantidade) || 0) * (parseFloat(item.valor_unitario) || 0)
}

export function totalDosItens(itens) {
  return itens.reduce((soma, item) => soma + totalDoItem(item), 0)
}

export default function ItensPedidoForm({ itens, onChange }) {
  function atualizar(index, campo, valor) {
    onChange(itens.map((item, i) => i === index ? { ...item, [campo]: valor } : item))
  }
  function adicionar() { onChange([...itens, { ...ITEM_VAZIO }]) }
  function remover(index) { onChange(itens.filter((_, i) => i !== index)) }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>Itens do pedido</span>
        <button type="button" onClick={adicionar}
          style={{ padding: '6px 14px', fontSize: 13, background: 'transparent', color: 'var(--color-accent-solid)', border: '1px solid var(--color-accent-solid)', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }}>
          + Adicionar produto
        </button>
      </div>

      {itens.map((item, i) => (
        <div key={i} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr auto', gap: 8, marginBottom: 8, alignItems: 'end' }}>
          <label style={{ fontSize: 12 }}>Produto<br />
            <input required value={item.produto} onChange={e => atualizar(i, 'produto', e.target.value)} style={inputStyle} />
          </label>
          <label style={{ fontSize: 12 }}>Quantidade<br />
            <input required type="number" step="0.01" min="0.01" value={item.quantidade} onChange={e => atualizar(i, 'quantidade', e.target.value)} style={inputStyle} />
          </label>
          <label style={{ fontSize: 12 }}>Valor unit. (R$)<br />
            <input required type="number" step="0.01" min="0" value={item.valor_unitario} onChange={e => atualizar(i, 'valor_unitario', e.target.value)} style={inputStyle} />
          </label>
          <div style={{ fontSize: 12 }}>Total<br />
            <div style={{ padding: '8px 0', fontWeight: 600 }}>{formatMoeda(totalDoItem(item))}</div>
          </div>
          <button type="button" onClick={() => remover(i)} disabled={itens.length === 1}
            style={{ padding: 8, background: 'transparent', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', cursor: itens.length === 1 ? 'not-allowed' : 'pointer', color: 'var(--color-text-muted)', opacity: itens.length === 1 ? 0.4 : 1 }}>
            ✕
          </button>
        </div>
      ))}

      <div style={{ textAlign: 'right', fontWeight: 700, marginTop: 8, fontSize: 15 }}>
        Total do pedido: {formatMoeda(totalDosItens(itens))}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Usar no `Fornecedores.jsx`**

1. Adicionar `import ItensPedidoForm, { ITEM_VAZIO, totalDosItens } from '../components/ItensPedidoForm'`.
2. Remover a constante `ITEM_VAZIO` local e as funções `atualizarItem`, `adicionarItem`, `removerItem`, `totalDoItem`; trocar `const totalDoPedido = form.itens.reduce(...)` por `const totalDoPedido = totalDosItens(form.itens)` (ou remover se só era usado dentro do bloco extraído).
3. Dentro do `<form onSubmit={handleSubmit}>`, substituir todo o `<div>` que começa em `<div style={{ display: 'flex', justifyContent: 'space-between', ... }}><span ...>Itens do pedido</span>` e termina em `Total do pedido: {formatMoeda(totalDoPedido)}</div></div>` por:

```jsx
              <ItensPedidoForm itens={form.itens} onChange={itens => setForm({ ...form, itens })} />
```

- [ ] **Step 4: Build e conferência visual**

Run: `npm run build`
Expected: `✓ built`, sem erro de import.

Abrir o harness de preview (o mesmo desta sessão: `.preview/` com `apiMock.js`, `authMock.jsx`, `layoutMock.jsx`, `vite.config.js` com aliases `^\.\.\/services\/api$` etc., servido por `npx vite --config .preview/vite.config.js --port 5177`), clicar "+ Novo pedido", adicionar 2 produtos, preencher e conferir que "Total do pedido" soma e que ✕ fica desabilitado com 1 linha. Remover `.preview/` antes do commit (não está no `.gitignore`).

- [ ] **Step 5: Commit**

```bash
git add src/components/ItensPedidoForm.jsx src/pages/Fornecedores.jsx
git commit -m "refactor: tabela de itens do pedido vira componente compartilhado

Sem mudança de comportamento; prepara o upload do pedido de compra.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11 (frontend): Componente `UploadPedidoCompra`

**Files:**
- Create: `src/components/UploadPedidoCompra.jsx`

**Interfaces:**
- Consumes: `api` (axios), `ItensPedidoForm`, `ITEM_VAZIO`, `totalDosItens`; endpoints das Tasks 5–8.
- Produces: `UploadPedidoCompra({ fornecedores, fornecedorSel, onSalvo })`. `onSalvo(fornecedorIdEscolhido)` é chamado depois de salvar tudo; a página recarrega e, se o fornecedor escolhido for outro, seleciona-o.
- Estados: `ocioso | lendoPedido | conferindo | lendoComprovante | salvando`.

- [ ] **Step 1: Escrever o componente**

```jsx
// src/components/UploadPedidoCompra.jsx
// Sobe um pedido de compra (PDF/foto) → a IA lê → ela confere → "já foi pago?"
// → sobe o comprovante → salva pedido (+ pagamento) com os anexos.
// A IA só lê; gravar é sempre no botão Salvar.
import { useRef, useState } from 'react'
import api from '../services/api'
import ItensPedidoForm, { ITEM_VAZIO, totalDosItens } from './ItensPedidoForm'

const TIPOS = 'application/pdf,image/jpeg,image/png'
const TAMANHO_MAX = 10 * 1024 * 1024

const inputStyle = { display: 'block', width: '100%', padding: 8, marginTop: 4, borderRadius: 'var(--radius-sm)', border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', boxSizing: 'border-box' }
const botaoPrimario = { padding: '8px 20px', background: 'var(--color-accent-solid)', color: 'var(--color-on-accent)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }
const botaoSecundario = { padding: '8px 20px', background: 'transparent', color: 'var(--color-text)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }

function formatMoeda(valor) {
  return Number(valor || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}
function formatData(data) {
  return data ? new Date(data).toLocaleDateString('pt-BR', { timeZone: 'UTC' }) : '—'
}

function Faixa({ tipo = 'aviso', children }) {
  const cor = tipo === 'erro' ? 'var(--color-danger)' : 'var(--color-warning, #a16e1a)'
  return (
    <div style={{ borderLeft: `4px solid ${cor}`, background: 'var(--color-bg)', padding: '8px 12px', borderRadius: 'var(--radius-sm)', fontSize: 13, marginBottom: 10 }}>
      {children}
    </div>
  )
}

function validarArquivo(arquivo) {
  if (!arquivo) return 'Escolha um arquivo.'
  if (!TIPOS.split(',').includes(arquivo.type)) return 'Só PDF, JPG ou PNG.'
  if (arquivo.size > TAMANHO_MAX) return 'Arquivo maior que 10 MB.'
  return null
}

function mensagemDe(err, padrao) {
  return err?.response?.data?.error || padrao
}

export default function UploadPedidoCompra({ fornecedores, fornecedorSel, onSalvo }) {
  const [etapa, setEtapa] = useState('ocioso')
  const [erro, setErro] = useState(null)
  const inputPedido = useRef(null)
  const inputComprovante = useRef(null)

  // rascunho do pedido, preenchido pela leitura e editado por ela
  const [fornecedorId, setFornecedorId] = useState(fornecedorSel.id)
  const [numeroPedido, setNumeroPedido] = useState('')
  const [dataPedido, setDataPedido] = useState('')
  const [itens, setItens] = useState([{ ...ITEM_VAZIO }])
  const [leitura, setLeitura] = useState(null)   // resposta crua do /pedidos/ler
  const [previewUrl, setPreviewUrl] = useState(null)

  // pagamento
  const [pago, setPago] = useState(null)         // null | false | true
  const [comprovante, setComprovante] = useState(null) // resposta do /pagamentos/ler
  const [valorPix, setValorPix] = useState('')
  const [dataPix, setDataPix] = useState('')

  const totalItens = totalDosItens(itens)
  const somaDifere = leitura?.total_documento != null && Math.abs(totalItens - leitura.total_documento) > 0.05
  const fornecedorEscolhido = fornecedores.find(f => f.id === fornecedorId)
  const pixParaOutro = comprovante && !comprovante.leitura_falhou
    && comprovante.fornecedor_sugerido_id && comprovante.fornecedor_sugerido_id !== fornecedorId

  function reiniciar() {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setEtapa('ocioso'); setErro(null)
    setFornecedorId(fornecedorSel.id); setNumeroPedido(''); setDataPedido('')
    setItens([{ ...ITEM_VAZIO }]); setLeitura(null); setPreviewUrl(null)
    setPago(null); setComprovante(null); setValorPix(''); setDataPix('')
  }

  async function lerPedido(arquivo) {
    const invalido = validarArquivo(arquivo)
    if (invalido) { setErro(invalido); return }
    setErro(null); setEtapa('lendoPedido')
    const form = new FormData()
    form.append('arquivo', arquivo)
    try {
      const r = await api.post(`/api/fornecedores/${fornecedorSel.id}/pedidos/ler`, form)
      const lido = r.data
      setLeitura(lido)
      setPreviewUrl(URL.createObjectURL(arquivo))
      setFornecedorId(lido.fornecedor_sugerido_id || fornecedorSel.id)
      setNumeroPedido(lido.numero_pedido || '')
      setDataPedido(lido.data_pedido || '')
      setItens(lido.itens.length ? lido.itens : [{ ...ITEM_VAZIO }])
      setEtapa('conferindo')
    } catch (err) {
      setErro(mensagemDe(err, 'Não consegui ler o arquivo.'))
      setEtapa('ocioso')
    }
  }

  async function lerComprovante(arquivo) {
    const invalido = validarArquivo(arquivo)
    if (invalido) { setErro(invalido); return }
    setErro(null); setEtapa('lendoComprovante')
    const form = new FormData()
    form.append('arquivo', arquivo)
    try {
      const r = await api.post(`/api/fornecedores/${fornecedorId}/pagamentos/ler`, form)
      setComprovante(r.data)
      setValorPix(r.data.valor != null ? String(r.data.valor) : '')
      setDataPix(r.data.data_pagamento || '')
      setEtapa('conferindo')
    } catch (err) {
      setErro(mensagemDe(err, 'Não consegui ler o comprovante.'))
      setEtapa('conferindo')
    }
  }

  async function salvar(e) {
    e.preventDefault()
    setErro(null)
    if (!dataPedido) { setErro('Informe a data do pedido.'); return }
    if (pago === null) { setErro('Diga se o pedido já foi pago.'); return }
    if (pago && !comprovante) { setErro('Suba o comprovante do Pix.'); return }
    setEtapa('salvando')
    try {
      await api.post(`/api/fornecedores/${fornecedorId}/pedidos`, {
        data_pedido: dataPedido,
        numero_pedido: numeroPedido || null,
        itens: itens.map(i => ({ produto: i.produto, quantidade: parseFloat(i.quantidade), valor_unitario: parseFloat(i.valor_unitario) })),
        arquivo_token: leitura?.arquivo_token || null,
        alias_vendedor: leitura?.texto_vendedor || null,
      })
    } catch (err) {
      setErro(mensagemDe(err, 'Erro ao salvar o pedido.'))
      setEtapa('conferindo')
      return
    }
    if (pago) {
      try {
        await api.post(`/api/fornecedores/${fornecedorId}/pagamentos`, {
          valor: parseFloat(valorPix),
          data_pagamento: dataPix,
          id_transacao: comprovante.id_transacao || null,
          arquivo_token: comprovante.arquivo_token || null,
          alias_destinatario: comprovante.destinatario || null,
        })
      } catch (err) {
        // o pedido já foi salvo: não deixar parecer que tudo falhou
        setErro(`Pedido salvo, mas o pagamento não: ${mensagemDe(err, 'erro ao registrar')}. Registre o pagamento à mão no pé da página.`)
        setEtapa('conferindo')
        onSalvo(fornecedorId)
        return
      }
    }
    reiniciar()
    onSalvo(fornecedorId)
  }

  if (etapa === 'ocioso' || etapa === 'lendoPedido') {
    return (
      <>
        <input ref={inputPedido} type="file" accept={TIPOS} style={{ display: 'none' }}
          onChange={e => { const f = e.target.files[0]; e.target.value = ''; if (f) lerPedido(f) }} />
        <button onClick={() => inputPedido.current.click()} disabled={etapa === 'lendoPedido'} style={botaoSecundario}>
          {etapa === 'lendoPedido' ? 'Lendo o pedido…' : '📎 Subir pedido de compra'}
        </button>
        {erro && <p style={{ color: 'var(--color-danger)', fontSize: 13, margin: '6px 0 0' }}>{erro}</p>}
      </>
    )
  }

  return (
    <form onSubmit={salvar} style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: 24, marginBottom: 24, display: 'grid', gridTemplateColumns: previewUrl ? '1fr 320px' : '1fr', gap: 24 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {leitura?.leitura_falhou && (
          <Faixa>Não consegui ler esse arquivo. Preencha à mão — o arquivo fica anexado mesmo assim.</Faixa>
        )}

        <label style={{ fontSize: 13 }}>Esse pedido é de<br />
          <select value={fornecedorId} onChange={e => setFornecedorId(e.target.value)} style={{ ...inputStyle, width: 260 }}>
            {fornecedores.map(f => <option key={f.id} value={f.id}>{f.apelido || f.nome}</option>)}
          </select>
        </label>

        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <label style={{ fontSize: 12 }}>Nº do pedido<br />
            <input value={numeroPedido} onChange={e => setNumeroPedido(e.target.value)} style={{ ...inputStyle, width: 160 }} />
          </label>
          <label style={{ fontSize: 12 }}>Data do pedido<br />
            <input required type="date" value={dataPedido} onChange={e => setDataPedido(e.target.value)} style={{ ...inputStyle, width: 170 }} />
          </label>
        </div>

        {leitura?.pedido_existente && (
          <Faixa>Esse pedido (nº {numeroPedido}) já está lançado em {formatData(leitura.pedido_existente.data_pedido)}. Lançar de novo?</Faixa>
        )}

        <ItensPedidoForm itens={itens} onChange={setItens} />

        {somaDifere && (
          <Faixa>A soma dos itens ({formatMoeda(totalItens)}) não bate com o total do documento ({formatMoeda(leitura.total_documento)}). Confira.</Faixa>
        )}

        <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
          <span style={{ fontWeight: 600, fontSize: 14 }}>Já foi pago?</span>
          <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 14 }}>
            <label><input type="radio" name="pago" checked={pago === false} onChange={() => { setPago(false); setComprovante(null) }} /> Não</label>
            <label><input type="radio" name="pago" checked={pago === true} onChange={() => setPago(true)} /> Sim</label>
          </div>

          {pago && !comprovante && (
            <div style={{ marginTop: 12 }}>
              <input ref={inputComprovante} type="file" accept={TIPOS} style={{ display: 'none' }}
                onChange={e => { const f = e.target.files[0]; e.target.value = ''; if (f) lerComprovante(f) }} />
              <button type="button" onClick={() => inputComprovante.current.click()} disabled={etapa === 'lendoComprovante'} style={botaoSecundario}>
                {etapa === 'lendoComprovante' ? 'Lendo o comprovante…' : '📎 Subir comprovante do Pix'}
              </button>
            </div>
          )}

          {pago && comprovante && (
            <div style={{ marginTop: 12, background: 'var(--color-bg)', borderRadius: 'var(--radius-sm)', padding: 12 }}>
              {comprovante.leitura_falhou
                ? <Faixa>Não consegui ler o comprovante. Preencha valor e data.</Faixa>
                : <p style={{ margin: '0 0 8px', fontSize: 14 }}>
                    Pix de <strong>{formatMoeda(comprovante.valor)}</strong> em <strong>{formatData(comprovante.data_pagamento)}</strong>
                    {comprovante.destinatario && <> para <strong>{comprovante.destinatario}</strong></>}
                    <br /><span style={{ color: 'var(--color-text-muted)' }}>→ cobre {formatMoeda(Math.min(parseFloat(valorPix) || 0, totalItens))} de {formatMoeda(totalItens)} deste pedido</span>
                  </p>}
              {pixParaOutro && (
                <Faixa>Esse Pix foi para {comprovante.destinatario}, que não está associado a {fornecedorEscolhido?.apelido || fornecedorEscolhido?.nome}. É isso mesmo?</Faixa>
              )}
              {comprovante.pagamento_existente && (
                <Faixa tipo="erro">Esse comprovante já foi lançado em {formatData(comprovante.pagamento_existente.data_pagamento)} ({formatMoeda(comprovante.pagamento_existente.valor)}).</Faixa>
              )}
              <div style={{ display: 'flex', gap: 12 }}>
                <label style={{ fontSize: 12 }}>Valor (R$)<br />
                  <input required type="number" step="0.01" min="0.01" value={valorPix} onChange={e => setValorPix(e.target.value)} style={{ ...inputStyle, width: 140 }} />
                </label>
                <label style={{ fontSize: 12 }}>Data<br />
                  <input required type="date" value={dataPix} onChange={e => setDataPix(e.target.value)} style={{ ...inputStyle, width: 160 }} />
                </label>
                <button type="button" onClick={() => setComprovante(null)} style={{ ...botaoSecundario, alignSelf: 'flex-end', padding: '8px 12px', fontSize: 12 }}>Trocar comprovante</button>
              </div>
            </div>
          )}
        </div>

        {erro && <p style={{ color: 'var(--color-danger)', margin: 0, fontSize: 13 }}>{erro}</p>}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" onClick={reiniciar} style={botaoSecundario}>Cancelar</button>
          <button type="submit" disabled={etapa === 'salvando'} style={botaoPrimario}>
            {etapa === 'salvando' ? 'Salvando…'
              : pago && comprovante?.pagamento_existente ? 'Salvar mesmo assim'
              : pago ? 'Salvar pedido e pagamento' : 'Salvar pedido'}
          </button>
        </div>
      </div>

      {previewUrl && (
        <div style={{ position: 'sticky', top: 16, alignSelf: 'start' }}>
          {leitura && previewUrl.startsWith('blob:') && (
            <object data={previewUrl} type="application/pdf" style={{ width: '100%', height: 420, border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)' }}>
              <img src={previewUrl} alt="Pedido enviado" style={{ maxWidth: '100%', borderRadius: 'var(--radius-sm)' }} />
            </object>
          )}
        </div>
      )}
    </form>
  )
}
```

Observações para quem implementa:
- `api.post(url, formData)` — o axios detecta `FormData` e põe o `Content-Type: multipart/form-data` com boundary sozinho; não setar à mão.
- `<object type="application/pdf">` com fallback `<img>`: para PDF o navegador embute; para foto o `object` falha e cai no `img`. Se algum navegador mostrar em branco para foto, trocar por `arquivo.type.startsWith('image/') ? <img> : <object>` guardando o `type` no estado.
- `var(--color-warning, #a16e1a)`: conferir em `src/design-tokens.css` se existe token de aviso; se existir com outro nome, usar o do projeto.

- [ ] **Step 2: Build**

Run: `npm run build`
Expected: `✓ built`

- [ ] **Step 3: Commit**

```bash
git add src/components/UploadPedidoCompra.jsx
git commit -m "feat: componente do upload de pedido de compra (ler → conferir → pago? → salvar)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12 (frontend): Ligar na página e mostrar o 📎

**Files:**
- Modify: `src/pages/Fornecedores.jsx` — cabeçalho "Pedidos — …" (botões), célula da data do pedido, `LinhaPagamento`, `selecionarFornecedor`/`recarregarDados`.

**Interfaces:**
- Consumes: `UploadPedidoCompra`, endpoints `/anexo`.
- Produces: botão "📎 Subir pedido de compra" ao lado de "+ Novo pedido" (só `fin_admin`); clipe 📎 na linha do pedido e na linha do pagamento quando `arquivo_path` existe; clique → `GET .../anexo` → `window.open(url, '_blank')`.

- [ ] **Step 1: Botão e componente**

No `Fornecedores.jsx`:
1. `import UploadPedidoCompra from '../components/UploadPedidoCompra'`.
2. No `<div style={{ display: 'flex', gap: 8 }}>` do cabeçalho "Pedidos — …", **antes** do botão "+ Novo pedido", dentro de `{finRole === 'fin_admin' && (...)}`, renderizar:

```jsx
                <UploadPedidoCompra
                  fornecedores={fornecedores}
                  fornecedorSel={fornecedorSel}
                  onSalvo={async (idEscolhido) => {
                    if (idEscolhido !== fornecedorSel.id) {
                      const outro = fornecedores.find(f => f.id === idEscolhido)
                      if (outro) { await selecionarFornecedor(outro); await carregarFornecedores(); return }
                    }
                    await recarregarDados()
                  }}
                />
```

O componente, no estado `ocioso`, é só o botão; nos outros estados renderiza o cartão. Como o cartão é um `<form>` grande, ele não pode ficar dentro do `div` de botões: renderizar o componente **fora** do cabeçalho — logo abaixo dele, antes de `{showForm && ...}` — e deixar no cabeçalho só um botão que chama uma ref. Forma mais simples: mover o `UploadPedidoCompra` inteiro para logo abaixo do cabeçalho (ele já desenha o próprio botão no estado ocioso), e no cabeçalho não pôr nada. Visualmente o botão fica na linha de baixo, à esquerda, acima da tabela — aceitável; se ela preferir no cabeçalho, ajustar depois.

- [ ] **Step 2: Clipe no pedido**

Na célula da data (`<td rowSpan={itens.length} ...>` que contém `<DataEditavel …/>`), depois do botão de excluir:

```jsx
                          {p.arquivo_path && (
                            <button onClick={() => abrirAnexo(`/api/fornecedores/${fornecedorSel.id}/pedidos/${p.id}/anexo`)} title="Ver pedido de compra"
                              style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 12, opacity: 0.7, padding: 2 }}>
                              📎
                            </button>
                          )}
```

E, entre as funções do componente `Fornecedores`:

```jsx
  async function abrirAnexo(caminho) {
    try {
      const r = await api.get(caminho)
      window.open(r.data.url, '_blank', 'noopener')
    } catch (err) {
      alert(err.response?.data?.error || 'Não consegui abrir o anexo.')
    }
  }
```

- [ ] **Step 3: Clipe no pagamento**

`LinhaPagamento` recebe uma prop nova `onAbrirAnexo` (função ou `null`). Na linha, depois do valor e antes dos botões ✏️/🗑️:

```jsx
      {pagamento.arquivo_path && onAbrirAnexo && (
        <button onClick={onAbrirAnexo} title="Ver comprovante"
          style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 12, opacity: 0.7, padding: 2 }}>
          📎
        </button>
      )}
```

`PainelPagamentosFornecedor` recebe `onAbrirAnexo(pagamento)` e passa `onAbrirAnexo={() => onAbrirAnexo(pg)}` para cada `LinhaPagamento`. Na página:

```jsx
                onAbrirAnexo={pg => abrirAnexo(`/api/fornecedores/${fornecedorSel.id}/pagamentos/${pg.id}/anexo`)}
```

- [ ] **Step 4: Build e conferência no harness**

Run: `npm run build` → `✓ built`.

No harness (`.preview/apiMock.js`), fazer o mock responder:
- `POST …/pedidos/ler` → `{ leitura_falhou: false, arquivo_token: 'pendentes/x.pdf', fornecedor_sugerido_id: <id do 2º fornecedor>, texto_vendedor: 'Flavia', numero_pedido: '2026/9001', data_pedido: '2026-09-01', itens: [2 itens], total_documento: 99999, pedido_existente: { id: 'p', data_pedido: '2026-09-01' } }` — assim as duas faixas amarelas aparecem;
- `POST …/pagamentos/ler` → `{ leitura_falhou: false, arquivo_token: 'pendentes/y.png', valor: 100, data_pagamento: '2026-09-02', destinatario: 'MIAO', id_transacao: 'E1', fornecedor_sugerido_id: null, pagamento_existente: null }`;
- `POST …/pedidos` e `POST …/pagamentos` → `{ data: {} }`;
- um pedido e um pagamento da lista com `arquivo_path` preenchido; `GET …/anexo` → `{ url: 'https://example.com' }`.

Conferir na tela: botão aparece só para admin; ao escolher um arquivo o cartão abre com dropdown já no fornecedor sugerido, nº, data, itens e as duas faixas; "Sim" mostra o botão do comprovante; após subir, mostra o bloco do Pix com "cobre X de Y"; "Salvar pedido e pagamento" chama os dois POSTs (ver no console do harness) e o cartão fecha; 📎 aparece nas linhas e o clique abre nova aba. Remover `.preview/` antes do commit.

- [ ] **Step 5: Commit**

```bash
git add src/pages/Fornecedores.jsx
git commit -m "feat: botão de upload do pedido de compra e clipe de anexo nas linhas

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Subir, testar no ar com documento real e fechar

**Files:** nenhum (operação + smoke test).

- [ ] **Step 1: Backend — merge e deploy**

```bash
cd /Users/macbookpro/Desktop/Claude/financeiro-backend
venv/bin/python -m pytest tests -q          # tudo verde
git checkout main && git merge --ff-only feat/upload-pedido-compra && git push origin main
```
(Se o push der 403 por conta do `gh`, `gh auth switch --user cibellycarvalho` e repetir.) Esperar ~40 s (deploy automático) e conferir:
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://financeiro.cravelli.com.br/api/fornecedores
```
Expected: `401`.

- [ ] **Step 2: Frontend — merge e deploy**

```bash
cd /Users/macbookpro/Desktop/Claude/financeiro-frontend
npm run build && git checkout main && git merge --ff-only feat/upload-pedido-compra && git push origin main
```
Conferir que o bundle novo está no ar:
```bash
js=$(curl -s https://financeiro.cravelli.com.br/ | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -1); curl -s "https://financeiro.cravelli.com.br/$js" | grep -c "Subir pedido de compra"
```
Expected: `1` (repetir após 20 s se der 0).

- [ ] **Step 3: Smoke test com documento real** (no Chrome dela, logada, via Claude in Chrome)

1. Fornecedores → FL → "📎 Subir pedido de compra" → escolher `~/Downloads/<pedido da Flavia em PDF>` (o 2026/5999 de 24/08 serve: já está lançado, então a faixa "já está lançado" **tem** que aparecer).
2. Conferir: dropdown em "FL"; nº `2026/5999`; data `24/08/2026`; 6 itens com os valores da nota; total R$ 30.150,00; faixa amarela do pedido repetido.
3. Marcar "Sim" → subir `~/Downloads/sicredi_1787532061.pdf` (Pix de 30.000 em 24/08 para MIAO — **já lançado**) → tem que aparecer a faixa vermelha "já foi lançado em 24/08/2026 (R$ 30.000,00)" e o botão virar "Salvar mesmo assim".
4. **Não salvar.** Clicar Cancelar. (O objetivo é ver a leitura e as faixas com documento real; gravar de novo duplicaria.)
5. Testar uma **foto**: tirar print do mesmo PDF (PNG) e subir — conferir que lê igual.
6. Clicar um 📎 de pedido lançado por upload (se houver) e ver abrir em nova aba. Se ainda não houver nenhum, criar um pedido de teste num fornecedor de teste, salvar com anexo, abrir o 📎 e depois excluir o pedido.

Se o passo 2 ler algo errado (item faltando, valor trocado), anotar o caso, ajustar `INSTRUCAO_PEDIDO` em `leitura_documento.py` e repetir — sem mexer no resto.

- [ ] **Step 4: Registrar o resultado**

Anexar ao fim do spec uma seção `## Conferido no ar (data)` com: modelo usado, tempo de leitura observado, o que leu certo/errado no PDF e na foto. Commit `docs:` na `main` do backend.

- [ ] **Step 5: Memória**

Atualizar `project_fornecedor_flavia_conciliacao.md` (memória do Claude) com uma linha: "Upload de pedido de compra no ar desde DD/MM/2026 — subir PDF/foto no fornecedor; aliases Flavia semeados".

---

## Self-review (feito ao escrever)

**Cobertura do spec:** fluxo (T11–T12); endpoints `/ler` (T5–T6); campos novos e anexos no salvar (T7–T8); `arquivo_token` + `pendentes/` + limpeza (T2, T5); aliases com aprendizado e semente (T1, T4, T7–T8); Storage privado + URL assinada no clique (T2, T8, T12); migração completa (T1); config/503 sem chave (T1, T3, T5); tabela "quando dá errado": tamanho/tipo (T5), leitura falhou → cartão vazio (T5–T6, T11), soma ≠ total (T11), nº repetido (T5, T11), E2E repetido (T6, T8, T11), destinatário de outro fornecedor (T11 + aprende em T8), API fora (T3, T5–T6), Storage falhou (T5, T7, T8); testes com fixtures gravadas e sem arquivo real (T3); smoke test real (T13).

**Placeholders:** nenhum "TBD"; a versão do `anthropic` em T1 pede conferir a última 1.x — é instrução, não lacuna.

**Consistência de nomes:** `arquivo_token` (tela/API) vs `arquivo_path` (banco) usados como no spec; `_destino_anexo` definido em T7 e usado em T8; `_ler_arquivo_enviado`/`_subir_pendente`/`MSG_LEITURA_INDISPONIVEL` definidos em T5 e usados em T6; `totalDosItens`/`ITEM_VAZIO` exportados em T10 e importados em T11; `onAbrirAnexo` (T12) coerente entre `LinhaPagamento` e `PainelPagamentosFornecedor`.
