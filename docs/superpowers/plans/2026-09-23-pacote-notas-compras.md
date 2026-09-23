# Pacote de notas e comprovantes da compra — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anexar nota fiscal às compras, amarrar cada Pix à compra que ele pagou, e baixar o mês em um .zip organizado por compra com um `resumo.xlsx`.

**Architecture:** Duas colunas novas de anexo (`nf_path` em pedidos; `nf_path` e `comprovante_path` em contas a pagar) seguindo o caminho de anexo que já existe (`pendentes/` no Supabase Storage → `storage.mover` ao salvar). A amarração pagamento↔compra sai da coluna `pedido_id` (uma compra por Pix) para a tabela de ligação `fin_pagamento_pedido` (várias, com valor). O download é uma rota nova que monta o zip em streaming lendo o Storage.

**Tech Stack:** Flask 3 + psycopg2 (backend), pytest; React + Vite + vitest (frontend); Supabase Postgres e Storage; openpyxl (novo) para o resumo.

**Spec:** `docs/superpowers/specs/2026-09-23-pacote-notas-compras-design.md`

## Global Constraints

- Repos: `financeiro-backend` e `financeiro-frontend` (ambos da conta `cibellycarvalho`). Push na `main` publica sozinho.
- Push nos repos do Painel exige o comando com credencial explícita:
  `git -c credential.helper= -c 'credential.helper=!f() { test "$1" = get || exit 0; echo username=cibellycarvalho; echo "password=$(gh auth token --user cibellycarvalho)"; }; f' push origin main`
- Migrações ficam em `financeiro-backend/supabase/AAAAMMDD_nome.sql` e são aplicadas à mão no Supabase (projeto YUSO, ref `tywirfmaosfztcmalbno`).
- **Backend vai antes do frontend**: tela que chama rota inexistente abre em "Não consegui carregar".
- Testes do frontend precisam de `NODE_OPTIONS=--no-experimental-webstorage` (Node 26; sem isso `localStorage` vem `undefined`).
- Anexos: só `application/pdf`, `image/jpeg`, `image/png`; máximo 10 MB (`anexos._TAMANHO_MAX`). Bucket `fornecedores`, privado; a tela nunca recebe caminho, só URL assinada.
- **Nada de nota, comprovante ou amarração é obrigatório.** Regra da Cibelly: *"às vezes não vou ter eles em mãos"*. A falta aparece no `resumo.xlsx`, nunca bloqueia salvar.
- Rotas de escrita usam `@require_auth` + `@require_admin`; leitura usa `@require_auth`.
- Dinheiro compara com tolerância de meio centavo (`+ 0.005`), como em `marcar_pedido_pago`.

---

### Task 1: Migração — colunas de nota e tabela de ligação

**Files:**
- Create: `supabase/20260923_notas_e_amarracao.sql`
- Test: `tests/test_migracao_notas.py`

**Interfaces:**
- Produces: colunas `fin_pedidos_fornecedor.nf_path`, `fin_contas_pagar.nf_path`, `fin_contas_pagar.comprovante_path`; tabela `fin_pagamento_pedido (pagamento_id uuid, pedido_id uuid, valor numeric(12,2))` com PK composta.

- [ ] **Step 1: Escrever a migração**

```sql
-- supabase/20260923_notas_e_amarracao.sql
-- Nota fiscal da compra e amarração de um Pix a várias compras (23/09/2026).

ALTER TABLE fin_pedidos_fornecedor ADD COLUMN IF NOT EXISTS nf_path text;
ALTER TABLE fin_contas_pagar ADD COLUMN IF NOT EXISTS nf_path text;
ALTER TABLE fin_contas_pagar ADD COLUMN IF NOT EXISTS comprovante_path text;

-- Um Pix pode pagar mais de uma compra: o de R$ 49.310 de 14/09 pagou os
-- pedidos de 10/08 e 11/08. A coluna pedido_id só aceitava uma.
CREATE TABLE IF NOT EXISTS fin_pagamento_pedido (
  pagamento_id uuid NOT NULL REFERENCES fin_pagamentos_fornecedor(id) ON DELETE CASCADE,
  pedido_id    uuid NOT NULL REFERENCES fin_pedidos_fornecedor(id) ON DELETE CASCADE,
  valor        numeric(12,2) NOT NULL CHECK (valor > 0),
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (pagamento_id, pedido_id)
);

CREATE INDEX IF NOT EXISTS idx_pagamento_pedido_pedido ON fin_pagamento_pedido(pedido_id);

-- As amarrações que já existem na coluna antiga passam para a tabela.
INSERT INTO fin_pagamento_pedido (pagamento_id, pedido_id, valor)
SELECT pg.id, pg.pedido_id, pg.valor
FROM fin_pagamentos_fornecedor pg
WHERE pg.pedido_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- A coluna pedido_id FICA, sem ser lida, até o código novo estar no ar uma
-- semana. Remover junto com o deploy deixaria a versão antiga da tela quebrada
-- no navegador de quem não recarregou.

ALTER TABLE fin_pagamento_pedido ENABLE ROW LEVEL SECURITY;
```

- [ ] **Step 2: Escrever o teste da migração**

O teste não roda SQL: confere que o arquivo existe e cobre o que o resto do plano depende (mesmo estilo de `tests/test_storage.py`, que lê constantes).

```python
# tests/test_migracao_notas.py
from pathlib import Path

SQL = Path(__file__).resolve().parent.parent / "supabase" / "20260923_notas_e_amarracao.sql"


def test_migracao_cria_colunas_e_tabela():
    texto = SQL.read_text()
    assert "fin_pedidos_fornecedor ADD COLUMN IF NOT EXISTS nf_path" in texto
    assert "fin_contas_pagar ADD COLUMN IF NOT EXISTS nf_path" in texto
    assert "fin_contas_pagar ADD COLUMN IF NOT EXISTS comprovante_path" in texto
    assert "CREATE TABLE IF NOT EXISTS fin_pagamento_pedido" in texto


def test_migracao_leva_as_amarracoes_antigas():
    texto = SQL.read_text()
    assert "INSERT INTO fin_pagamento_pedido" in texto
    assert "WHERE pg.pedido_id IS NOT NULL" in texto
```

- [ ] **Step 3: Rodar o teste**

Run: `cd financeiro-backend && python -m pytest tests/test_migracao_notas.py -v`
Expected: PASS (o arquivo já foi escrito no Step 1).

- [ ] **Step 4: Aplicar a migração no Supabase**

Aplicar `supabase/20260923_notas_e_amarracao.sql` no projeto YUSO (`tywirfmaosfztcmalbno`), via MCP `apply_migration` ou SQL Editor. Depois conferir que as 4 amarrações antigas viraram linhas:

```sql
SELECT count(*) FROM fin_pagamento_pedido;                       -- espera 4
SELECT count(*) FROM fin_pagamentos_fornecedor WHERE pedido_id IS NOT NULL;  -- espera o mesmo 4
```

- [ ] **Step 5: Commit**

```bash
git add supabase/20260923_notas_e_amarracao.sql tests/test_migracao_notas.py
git commit -m "feat: colunas de nota fiscal e tabela de amarração pagamento-pedido"
```

---

### Task 2: Backend — anexar a nota fiscal da compra

**Files:**
- Modify: `routes/fornecedores.py` (depois de `anexo_pedido`, por volta da linha 784)
- Test: `tests/test_fornecedores_upload.py`

**Interfaces:**
- Consumes: `anexos.ler_arquivo_enviado()`, `anexos.subir_pendente(dados, mime)`, `anexos.destino_anexo(prefixo, pasta, registro_id, token)`, `anexos.url_anexo(tabela, coluna_dono, dono_id, registro_id, coluna_arquivo)`, `storage.mover(origem, destino)`.
- Produces:
  - `POST /api/fornecedores/<fornecedor_id>/pedidos/<pedido_id>/nf` — multipart com campo `arquivo`; responde `{"nf_path": "<caminho>"}` 200.
  - `GET /api/fornecedores/<fornecedor_id>/pedidos/<pedido_id>/nf` — responde `{"url": "<assinada 1h>"}` 200 ou 404 "Sem anexo".

- [ ] **Step 1: Escrever os testes que falham**

```python
# no fim de tests/test_fornecedores_upload.py
import io
from unittest.mock import patch


def _arquivo(nome="nota.pdf", mime="application/pdf"):
    return {"arquivo": (io.BytesIO(b"%PDF-1.4 conteudo"), nome, mime)}


def test_sobe_nota_fiscal_do_pedido(client, admin_headers):
    with patch("db.query", return_value=[{"id": "ped-1"}]), \
         patch("anexos.subir_pendente", return_value="pendentes/" + "a" * 32 + ".pdf"), \
         patch("storage.mover") as mover, \
         patch("db.execute", return_value={"id": "ped-1", "nf_path": "forn-1/notas/ped-1.pdf"}):
        resp = client.post(
            "/api/fornecedores/forn-1/pedidos/ped-1/nf",
            data=_arquivo(), content_type="multipart/form-data", headers=admin_headers,
        )
    assert resp.status_code == 200
    assert resp.get_json()["nf_path"] == "forn-1/notas/ped-1.pdf"
    mover.assert_called_once()


def test_nota_de_pedido_de_outro_fornecedor_da_404(client, admin_headers):
    with patch("db.query", return_value=[]):
        resp = client.post(
            "/api/fornecedores/forn-1/pedidos/ped-9/nf",
            data=_arquivo(), content_type="multipart/form-data", headers=admin_headers,
        )
    assert resp.status_code == 404


def test_nota_recusa_tipo_de_arquivo_errado(client, admin_headers):
    with patch("db.query", return_value=[{"id": "ped-1"}]):
        resp = client.post(
            "/api/fornecedores/forn-1/pedidos/ped-1/nf",
            data=_arquivo("nota.docx", "application/msword"),
            content_type="multipart/form-data", headers=admin_headers,
        )
    assert resp.status_code == 400
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_fornecedores_upload.py -k nota -v`
Expected: FAIL com 404/405 (a rota ainda não existe).

- [ ] **Step 3: Implementar as duas rotas**

```python
# routes/fornecedores.py, logo depois de anexo_pedido
@bp.post("/<fornecedor_id>/pedidos/<pedido_id>/nf")
@require_auth
@require_admin
def subir_nf_pedido(fornecedor_id, pedido_id):
    """Nota fiscal da compra. Sem leitura por IA: é arquivo para a contabilidade,
    não dado que a tela precise entender."""
    rows = db.query(
        "SELECT id FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id),
    )
    if not rows:
        return jsonify({"error": "Pedido não encontrado"}), 404

    dados, mime, erro = anexos.ler_arquivo_enviado()
    if erro:
        return erro

    try:
        token = anexos.subir_pendente(dados, mime)
        destino = anexos.destino_anexo(fornecedor_id, "notas", pedido_id, token)
        storage.mover(token, destino)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao guardar a nota do pedido: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": "Não consegui guardar a nota. Tente de novo."}), 500

    row = db.execute(
        "UPDATE fin_pedidos_fornecedor SET nf_path = %s WHERE id = %s RETURNING nf_path",
        (destino, pedido_id),
    )
    return jsonify({"nf_path": row["nf_path"]})


@bp.get("/<fornecedor_id>/pedidos/<pedido_id>/nf")
@require_auth
def anexo_nf_pedido(fornecedor_id, pedido_id):
    return anexos.url_anexo("fin_pedidos_fornecedor", "fornecedor_id", fornecedor_id,
                            pedido_id, coluna_arquivo="nf_path")
```

Conferir que `listar_pedidos` devolve `nf_path` — ele faz `SELECT p.*`, então já vem.

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_fornecedores_upload.py -v`
Expected: PASS (todos, inclusive os que já existiam).

- [ ] **Step 5: Commit**

```bash
git add routes/fornecedores.py tests/test_fornecedores_upload.py
git commit -m "feat: anexar nota fiscal na compra do fornecedor"
```

---

### Task 3: Backend — nota e comprovante em Contas a Pagar

**Files:**
- Modify: `routes/contas.py`
- Test: `tests/test_contas.py`

**Interfaces:**
- Consumes: as mesmas funções de `anexos` e `storage` da Task 2.
- Produces:
  - `POST /api/contas/<conta_id>/anexo/<tipo>` com `tipo` em `{"nf", "comprovante"}` — multipart `arquivo`; responde `{"nf_path": ...}` ou `{"comprovante_path": ...}`.
  - `GET /api/contas/<conta_id>/anexo/<tipo>` — `{"url": ...}` ou 404.
  - `GET /api/contas` passa a devolver `nf_path` e `comprovante_path` (já devolve, por causa do `SELECT *`).

- [ ] **Step 1: Escrever os testes que falham**

```python
# no fim de tests/test_contas.py
import io
from unittest.mock import patch

TOKEN = "pendentes/" + "b" * 32 + ".pdf"


def _pdf():
    return {"arquivo": (io.BytesIO(b"%PDF-1.4 x"), "doc.pdf", "application/pdf")}


def test_sobe_nota_da_conta(client, admin_headers):
    with patch("db.query", return_value=[{"id": "c1"}]), \
         patch("anexos.subir_pendente", return_value=TOKEN), \
         patch("storage.mover"), \
         patch("db.execute", return_value={"nf_path": "contas/c1-nf.pdf"}):
        resp = client.post("/api/contas/c1/anexo/nf", data=_pdf(),
                           content_type="multipart/form-data", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["nf_path"] == "contas/c1-nf.pdf"


def test_sobe_comprovante_da_conta(client, admin_headers):
    with patch("db.query", return_value=[{"id": "c1"}]), \
         patch("anexos.subir_pendente", return_value=TOKEN), \
         patch("storage.mover"), \
         patch("db.execute", return_value={"comprovante_path": "contas/c1-comprovante.pdf"}):
        resp = client.post("/api/contas/c1/anexo/comprovante", data=_pdf(),
                           content_type="multipart/form-data", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["comprovante_path"] == "contas/c1-comprovante.pdf"


def test_tipo_de_anexo_invalido_da_400(client, admin_headers):
    resp = client.post("/api/contas/c1/anexo/foto", data=_pdf(),
                       content_type="multipart/form-data", headers=admin_headers)
    assert resp.status_code == 400


def test_url_do_anexo_da_conta_sem_arquivo_da_404(client, admin_headers):
    with patch("db.query", return_value=[{"nf_path": None}]):
        resp = client.get("/api/contas/c1/anexo/nf", headers=admin_headers)
    assert resp.status_code == 404
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_contas.py -k anexo -v`
Expected: FAIL (404/405).

- [ ] **Step 3: Implementar**

```python
# topo de routes/contas.py, junto dos outros imports
import sys

import anexos
import storage

COLUNA_ANEXO = {"nf": "nf_path", "comprovante": "comprovante_path"}


# no fim do arquivo
@bp.post("/<conta_id>/anexo/<tipo>")
@require_auth
@require_admin
def subir_anexo_conta(conta_id, tipo):
    coluna = COLUNA_ANEXO.get(tipo)
    if not coluna:
        return jsonify({"error": "tipo deve ser nf ou comprovante"}), 400

    if not db.query("SELECT id FROM fin_contas_pagar WHERE id = %s", (conta_id,)):
        return jsonify({"error": "Conta não encontrada"}), 404

    dados, mime, erro = anexos.ler_arquivo_enviado()
    if erro:
        return erro

    try:
        token = anexos.subir_pendente(dados, mime)
        destino = anexos.destino_anexo("contas", tipo, conta_id, token)
        storage.mover(token, destino)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao guardar {tipo} da conta: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": "Não consegui guardar o arquivo. Tente de novo."}), 500

    row = db.execute(
        f"UPDATE fin_contas_pagar SET {coluna} = %s WHERE id = %s RETURNING {coluna}",
        (destino, conta_id),
    )
    return jsonify({coluna: row[coluna]})


@bp.get("/<conta_id>/anexo/<tipo>")
@require_auth
def url_anexo_conta(conta_id, tipo):
    coluna = COLUNA_ANEXO.get(tipo)
    if not coluna:
        return jsonify({"error": "tipo deve ser nf ou comprovante"}), 400
    rows = db.query(f"SELECT {coluna} FROM fin_contas_pagar WHERE id = %s", (conta_id,))
    if not rows or not rows[0][coluna]:
        return jsonify({"error": "Sem anexo"}), 404
    try:
        return jsonify({"url": storage.url_assinada(rows[0][coluna])})
    except storage.StorageErro as e:
        print(f"[storage] falhou ao assinar URL da conta: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": "Não consegui abrir o anexo agora."}), 502
```

`coluna` nunca vem da request crua: sai do dicionário `COLUNA_ANEXO`, por isso pode entrar na f-string.

- [ ] **Step 4: Rodar os testes**

Run: `python -m pytest tests/test_contas.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/contas.py tests/test_contas.py
git commit -m "feat: nota fiscal e comprovante anexados na conta a pagar"
```

---

### Task 4: Backend — amarrar um Pix a várias compras

**Files:**
- Create: `amarracao.py`
- Modify: `routes/fornecedores.py` (`marcar_pedido_pago`, `desmarcar_pedido_pago`, `registrar_pagamento`)
- Test: `tests/test_amarracao.py`

**Interfaces:**
- Produces:
  - `amarracao.validar(cur, pagamento_id, itens)` — `itens` é lista de `{"pedido_id": str, "valor": float}`; devolve `None` ou uma string de erro.
  - `GET /api/fornecedores/<fornecedor_id>/pagamentos/soltos` — pagamentos daquele fornecedor sem nenhuma linha em `fin_pagamento_pedido`, com `{"id", "valor", "data_pagamento", "arquivo_path"}`.
  - `POST /api/fornecedores/<fornecedor_id>/pagamentos/<pagamento_id>/pedidos` — corpo `{"itens": [{"pedido_id": ..., "valor": ...}]}`; 200 com a lista gravada.
  - `DELETE /api/fornecedores/<fornecedor_id>/pagamentos/<pagamento_id>/pedidos` — apaga as amarrações daquele pagamento; 204.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_amarracao.py
from unittest.mock import patch, MagicMock

import amarracao


def test_soma_amarrada_nao_passa_do_pagamento():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 100.0},                       # valor do pagamento
        {"valor_total": 60.0, "amarrado": 0.0},  # pedido A
        {"valor_total": 60.0, "amarrado": 0.0},  # pedido B
    ]
    erro = amarracao.validar(cur, "pg-1", [
        {"pedido_id": "a", "valor": 60.0},
        {"pedido_id": "b", "valor": 60.0},
    ])
    assert erro is not None
    assert "pagamento" in erro


def test_soma_amarrada_nao_passa_do_valor_da_compra():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 100.0},
        {"valor_total": 50.0, "amarrado": 20.0},   # já tem 20 amarrados
    ]
    erro = amarracao.validar(cur, "pg-1", [{"pedido_id": "a", "valor": 40.0}])
    assert erro is not None
    assert "compra" in erro


def test_amarracao_parcial_e_valida():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 100.0},
        {"valor_total": 500.0, "amarrado": 0.0},
    ]
    assert amarracao.validar(cur, "pg-1", [{"pedido_id": "a", "valor": 100.0}]) is None


def test_valor_zero_ou_negativo_e_recusado():
    cur = MagicMock()
    cur.fetchone.side_effect = [{"valor": 100.0}]
    assert amarracao.validar(cur, "pg-1", [{"pedido_id": "a", "valor": 0}]) is not None


def test_lista_pagamentos_soltos(client, admin_headers):
    soltos = [{"id": "pg-1", "valor": 2970.0, "data_pagamento": "2026-09-23", "arquivo_path": None}]
    with patch("db.query", return_value=soltos):
        resp = client.get("/api/fornecedores/forn-1/pagamentos/soltos", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()[0]["id"] == "pg-1"


def test_amarrar_grava_uma_linha_por_compra(client, admin_headers):
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"valor": 49310.0},
        {"valor_total": 30000.0, "amarrado": 0.0},
        {"valor_total": 19310.0, "amarrado": 0.0},
    ]
    transacao = MagicMock()
    transacao.__enter__.return_value = cur
    with patch("db.query", return_value=[{"id": "pg-1"}]), patch("db.transaction", return_value=transacao):
        resp = client.post(
            "/api/fornecedores/forn-1/pagamentos/pg-1/pedidos",
            json={"itens": [{"pedido_id": "a", "valor": 30000.0},
                            {"pedido_id": "b", "valor": 19310.0}]},
            headers=admin_headers,
        )
    assert resp.status_code == 200
    inserts = [c for c in cur.execute.call_args_list if "INSERT INTO fin_pagamento_pedido" in c[0][0]]
    assert len(inserts) == 2
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_amarracao.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'amarracao'`.

- [ ] **Step 3: Implementar o módulo**

```python
# amarracao.py
"""Amarra um pagamento às compras que ele pagou.

Saiu da coluna fin_pagamentos_fornecedor.pedido_id, que só aceitava uma compra
por Pix. O Pix de R$ 49.310 de 14/09/2026 pagou os pedidos de 10/08 e 11/08.
"""
TOLERANCIA = 0.005   # meio centavo, como no resto do painel


def validar(cur, pagamento_id, itens):
    """Devolve None se pode gravar, ou a frase de erro que a tela mostra."""
    if not itens:
        return "Escolha pelo menos uma compra."

    for item in itens:
        try:
            valor = float(item["valor"])
        except (KeyError, TypeError, ValueError):
            return "valor inválido."
        if valor <= 0:
            return "O valor de cada compra tem que ser maior que zero."

    cur.execute("SELECT valor FROM fin_pagamentos_fornecedor WHERE id = %s", (pagamento_id,))
    linha = cur.fetchone()
    if not linha:
        return "Pagamento não encontrado."
    total_pagamento = float(linha["valor"])
    total_itens = sum(float(i["valor"]) for i in itens)
    if total_itens > total_pagamento + TOLERANCIA:
        return (f"A soma das compras (R$ {total_itens:.2f}) passa do valor do "
                f"pagamento (R$ {total_pagamento:.2f}).")

    for item in itens:
        cur.execute(
            """SELECT p.valor_total,
                      COALESCE((SELECT SUM(valor) FROM fin_pagamento_pedido
                                WHERE pedido_id = p.id AND pagamento_id <> %s), 0) AS amarrado
               FROM fin_pedidos_fornecedor p WHERE p.id = %s""",
            (pagamento_id, item["pedido_id"]),
        )
        pedido = cur.fetchone()
        if not pedido:
            return "Compra não encontrada."
        livre = float(pedido["valor_total"]) - float(pedido["amarrado"])
        if float(item["valor"]) > livre + TOLERANCIA:
            return (f"Essa compra só tem R$ {max(livre, 0):.2f} em aberto — "
                    "o valor amarrado não pode passar disso.")
    return None
```

- [ ] **Step 4: Implementar as rotas**

```python
# routes/fornecedores.py, junto das rotas de pagamento
import amarracao


@bp.get("/<fornecedor_id>/pagamentos/soltos")
@require_auth
def pagamentos_soltos(fornecedor_id):
    """Pix daquele fornecedor que ainda não dizem qual compra pagaram."""
    rows = db.query(
        """SELECT pg.id, pg.valor, pg.data_pagamento, pg.arquivo_path
           FROM fin_pagamentos_fornecedor pg
           WHERE pg.fornecedor_id = %s
             AND NOT EXISTS (SELECT 1 FROM fin_pagamento_pedido lig WHERE lig.pagamento_id = pg.id)
           ORDER BY pg.data_pagamento DESC""",
        (fornecedor_id,),
    )
    return jsonify(rows)


@bp.post("/<fornecedor_id>/pagamentos/<pagamento_id>/pedidos")
@require_auth
@require_admin
def amarrar_pagamento(fornecedor_id, pagamento_id):
    if not db.query(
        "SELECT id FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pagamento_id, fornecedor_id),
    ):
        return jsonify({"error": "Pagamento não encontrado"}), 404

    itens = (request.get_json() or {}).get("itens")
    if not isinstance(itens, list):
        return jsonify({"error": "itens obrigatório (lista)"}), 400

    with db.transaction() as cur:
        erro = amarracao.validar(cur, pagamento_id, itens)
        if erro:
            return jsonify({"error": erro}), 400
        cur.execute("DELETE FROM fin_pagamento_pedido WHERE pagamento_id = %s", (pagamento_id,))
        for item in itens:
            cur.execute(
                """INSERT INTO fin_pagamento_pedido (pagamento_id, pedido_id, valor)
                   VALUES (%s, %s, %s)""",
                (pagamento_id, item["pedido_id"], float(item["valor"])),
            )
    return jsonify({"itens": itens})


@bp.delete("/<fornecedor_id>/pagamentos/<pagamento_id>/pedidos")
@require_auth
@require_admin
def desamarrar_pagamento(fornecedor_id, pagamento_id):
    if not db.query(
        "SELECT id FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pagamento_id, fornecedor_id),
    ):
        return jsonify({"error": "Pagamento não encontrado"}), 404
    db.execute("DELETE FROM fin_pagamento_pedido WHERE pagamento_id = %s", (pagamento_id,))
    return "", 204
```

- [ ] **Step 5: Fazer a caixinha "Pago" gravar na tabela nova**

Em `marcar_pedido_pago`, modo `lancar`, depois do `INSERT ... RETURNING *` que cria o pagamento, gravar também a ligação (a coluna `pedido_id` continua sendo preenchida enquanto existir):

```python
            cur.execute(
                """INSERT INTO fin_pagamento_pedido (pagamento_id, pedido_id, valor)
                   VALUES (%s, %s, %s)""",
                (pagamento["id"], pedido_id, valor),
            )
```

Em `registrar_pagamento`, no bloco `if pedido_id:` que marca `pago_em`, acrescentar:

```python
        db.execute(
            """INSERT INTO fin_pagamento_pedido (pagamento_id, pedido_id, valor)
               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
            (row["id"], pedido_id, valor),
        )
```

`desmarcar_pedido_pago` já apaga o pagamento, e a FK tem `ON DELETE CASCADE` — a ligação vai junto. Acrescentar, antes do DELETE do pagamento, a limpeza da ligação de pagamentos que ficam:

```python
        cur.execute("DELETE FROM fin_pagamento_pedido WHERE pedido_id = %s", (pedido_id,))
```

- [ ] **Step 6: Rodar tudo**

Run: `python -m pytest -v`
Expected: PASS, inclusive `tests/test_fornecedores.py` (a caixinha "Pago" continua igual vista de fora).

- [ ] **Step 7: Commit**

```bash
git add amarracao.py routes/fornecedores.py tests/test_amarracao.py
git commit -m "feat: um pagamento pode ser amarrado a várias compras"
```

---

### Task 5: Backend — baixar o mês em .zip

**Files:**
- Create: `routes/pacote.py`, `pacote_zip.py`
- Modify: `app.py` (registrar o blueprint), `requirements.txt` (openpyxl)
- Test: `tests/test_pacote_zip.py`

**Interfaces:**
- Consumes: `storage.baixar(caminho) -> bytes` (criar em `storage.py` se não existir — ver Step 3), `amarracao` (só leitura via SQL).
- Produces:
  - `pacote_zip.montar(compras) -> bytes` — recebe a lista de dicionários descrita no Step 1 e devolve o zip pronto.
  - `GET /api/pacote/compras/<mes>` com `mes` no formato `AAAA-MM` — devolve `application/zip` com `Content-Disposition: attachment; filename="compras-<mes>.zip"`; 404 com `{"error": "Nenhuma compra em <mes>."}` se o mês estiver vazio.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_pacote_zip.py
import io
import zipfile
from unittest.mock import patch

import pacote_zip

COMPRA = {
    "fornecedor": "FLAVIA",
    "data_compra": "2026-08-17",
    "numero_pedido": "1234",
    "valor": 30000.0,
    "nf_path": "forn/notas/ped-1.pdf",
    "pedido_path": "forn/pedidos/ped-1.pdf",
    "comprovantes": [
        {"path": "forn/pagamentos/pg-1.pdf", "data": "2026-09-22", "valor": 30000.0},
    ],
}


def _nomes(zbytes):
    return zipfile.ZipFile(io.BytesIO(zbytes)).namelist()


def test_pasta_e_da_compra_mesmo_com_pix_do_mes_seguinte():
    with patch("storage.baixar", return_value=b"%PDF"):
        nomes = _nomes(pacote_zip.montar([COMPRA]))
    assert "FLAVIA/17-08 pedido 1234/nota-fiscal.pdf" in nomes
    assert "FLAVIA/17-08 pedido 1234/pedido.pdf" in nomes
    assert "FLAVIA/17-08 pedido 1234/comprovante 22-09 R$ 30.000,00.pdf" in nomes


def test_mesmo_comprovante_aparece_nas_duas_compras():
    a = dict(COMPRA, numero_pedido="10", valor=30000.0)
    b = dict(COMPRA, numero_pedido="11", valor=19310.0, nf_path=None, pedido_path=None,
             comprovantes=[{"path": "forn/pagamentos/pg-1.pdf", "data": "2026-09-22", "valor": 19310.0}])
    with patch("storage.baixar", return_value=b"%PDF"):
        nomes = _nomes(pacote_zip.montar([a, b]))
    assert "FLAVIA/17-08 pedido 10/comprovante 22-09 R$ 30.000,00.pdf" in nomes
    assert "FLAVIA/17-08 pedido 11/comprovante 22-09 R$ 19.310,00.pdf" in nomes


def test_arquivo_que_falha_vira_bilhete_em_vez_de_derrubar_o_zip():
    import storage as st
    with patch("storage.baixar", side_effect=st.StorageErro("sumiu")):
        conteudo = pacote_zip.montar([COMPRA])
    nomes = _nomes(conteudo)
    assert any(n.startswith("FLAVIA/17-08 pedido 1234/FALTOU") for n in nomes)


def test_compra_sem_arquivo_nenhum_ainda_tem_pasta_e_linha_no_resumo():
    vazia = dict(COMPRA, nf_path=None, pedido_path=None, comprovantes=[])
    conteudo = pacote_zip.montar([vazia])
    nomes = _nomes(conteudo)
    assert any(n.startswith("FLAVIA/17-08 pedido 1234/") for n in nomes)
    assert "resumo.xlsx" in nomes


def test_resumo_marca_o_que_falta():
    vazia = dict(COMPRA, nf_path=None, comprovantes=[])
    import openpyxl
    conteudo = pacote_zip.montar([vazia])
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        planilha = openpyxl.load_workbook(io.BytesIO(z.read("resumo.xlsx")))
    linhas = list(planilha.active.values)
    assert linhas[0][0] == "Fornecedor"
    assert "não" in linhas[1]    # tem nota = não
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_pacote_zip.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'pacote_zip'`.

- [ ] **Step 3: Acrescentar `storage.baixar` e a dependência**

```python
# storage.py, junto das outras chamadas
def baixar(caminho: str) -> bytes:
    """Conteúdo do arquivo. Usado para montar o pacote do mês."""
    resp = requests.get(
        f"{_base()}/object/{BUCKET}/{caminho}",
        headers=_headers(),
        timeout=60,
    )
    _checar(resp, "baixar arquivo")
    return resp.content
```

```
# requirements.txt, no fim
openpyxl==3.1.5
```

Run: `pip install -r requirements.txt`

- [ ] **Step 4: Implementar o montador do zip**

```python
# pacote_zip.py
"""Monta o .zip do mês: uma pasta por compra, com nota, pedido e comprovantes.

A pasta é da COMPRA, não do Pix: a Flávia tem 30 dias de prazo, então o
comprovante de setembro mora na pasta da compra de agosto. Um Pix que pagou duas
compras aparece nas duas pastas — repetir o arquivo custa menos que mandar a
contabilidade procurar.
"""
import io
import zipfile
from datetime import date

import openpyxl

import storage

CABECALHO = ["Fornecedor", "Data da compra", "Nº do pedido", "Valor", "Pago",
             "Pagamentos", "Em aberto", "Tem nota", "Tem comprovante"]


def _dia_mes(iso_data):
    d = date.fromisoformat(str(iso_data)[:10])
    return f"{d.day:02d}-{d.month:02d}"


def _brl(valor):
    inteiro = f"{float(valor):,.2f}"
    return "R$ " + inteiro.replace(",", "·").replace(".", ",").replace("·", ".")


def _pasta(compra):
    numero = compra.get("numero_pedido") or "sem número"
    return f"{compra['fornecedor']}/{_dia_mes(compra['data_compra'])} pedido {numero}"


def _escrever(zf, caminho_no_zip, path_no_storage):
    """Baixa do Storage e escreve. Falha vira bilhete, não exceção."""
    try:
        zf.writestr(caminho_no_zip, storage.baixar(path_no_storage))
    except storage.StorageErro as e:
        nome = caminho_no_zip.rsplit("/", 1)[-1]
        pasta = caminho_no_zip.rsplit("/", 1)[0]
        zf.writestr(f"{pasta}/FALTOU {nome}.txt",
                    f"Não consegui baixar este arquivo do Storage.\nMotivo: {e}\n")


def montar(compras):
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf:
        planilha = openpyxl.Workbook()
        aba = planilha.active
        aba.title = "Compras"
        aba.append(CABECALHO)

        for compra in compras:
            pasta = _pasta(compra)
            # A pasta existe mesmo vazia: a linha do resumo precisa ter um lugar
            # correspondente no zip.
            zf.writestr(f"{pasta}/", b"")

            if compra.get("nf_path"):
                ext = compra["nf_path"].rsplit(".", 1)[-1]
                _escrever(zf, f"{pasta}/nota-fiscal.{ext}", compra["nf_path"])
            if compra.get("pedido_path"):
                ext = compra["pedido_path"].rsplit(".", 1)[-1]
                _escrever(zf, f"{pasta}/pedido.{ext}", compra["pedido_path"])

            pago = 0.0
            datas = []
            for comp in compra.get("comprovantes", []):
                pago += float(comp["valor"])
                datas.append(_dia_mes(comp["data"]))
                if comp.get("path"):
                    ext = comp["path"].rsplit(".", 1)[-1]
                    nome = f"comprovante {_dia_mes(comp['data'])} {_brl(comp['valor'])}.{ext}"
                    _escrever(zf, f"{pasta}/{nome}", comp["path"])

            tem_comprovante = any(c.get("path") for c in compra.get("comprovantes", []))
            aba.append([
                compra["fornecedor"],
                str(compra["data_compra"])[:10],
                compra.get("numero_pedido") or "",
                float(compra["valor"]),
                pago,
                ", ".join(datas),
                float(compra["valor"]) - pago,
                "sim" if compra.get("nf_path") else "não",
                "sim" if tem_comprovante else "não",
            ])

        planilha_bytes = io.BytesIO()
        planilha.save(planilha_bytes)
        zf.writestr("resumo.xlsx", planilha_bytes.getvalue())

    return saida.getvalue()
```

- [ ] **Step 5: Rodar os testes do montador**

Run: `python -m pytest tests/test_pacote_zip.py -v`
Expected: PASS.

- [ ] **Step 6: Escrever o teste da rota**

```python
# no fim de tests/test_pacote_zip.py
from unittest.mock import patch


def test_rota_devolve_zip(client, admin_headers):
    linhas = [{
        "fornecedor": "FLAVIA", "data_compra": "2026-08-17", "numero_pedido": "1234",
        "valor": 30000.0, "nf_path": None, "pedido_path": None, "comprovantes": [],
    }]
    with patch("routes.pacote._compras_do_mes", return_value=linhas):
        resp = client.get("/api/pacote/compras/2026-08", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.mimetype == "application/zip"
    assert "compras-2026-08.zip" in resp.headers["Content-Disposition"]


def test_mes_sem_compra_avisa_em_vez_de_zip_vazio(client, admin_headers):
    with patch("routes.pacote._compras_do_mes", return_value=[]):
        resp = client.get("/api/pacote/compras/2026-08", headers=admin_headers)
    assert resp.status_code == 404
    assert "Nenhuma compra" in resp.get_json()["error"]


def test_mes_em_formato_errado_da_400(client, admin_headers):
    resp = client.get("/api/pacote/compras/agosto", headers=admin_headers)
    assert resp.status_code == 400
```

Run: `python -m pytest tests/test_pacote_zip.py -k rota -v` → FAIL (404, blueprint não existe).

- [ ] **Step 7: Implementar a rota**

```python
# routes/pacote.py
"""Baixar o mês: um .zip por mês de COMPRA, com nota, pedido e comprovantes."""
import calendar
import re
from datetime import date

from flask import Blueprint, jsonify, Response

import db
import pacote_zip
from auth import require_auth

bp = Blueprint("pacote", __name__)


def _compras_do_mes(inicio, fim):
    """Compras de fornecedor do mês + as contas a pagar de categoria FORNECEDOR."""
    pedidos = db.query(
        """SELECT COALESCE(f.apelido, f.nome) AS fornecedor,
                  p.data_pedido AS data_compra, p.numero_pedido,
                  p.valor_total AS valor, p.nf_path, p.arquivo_path AS pedido_path,
                  COALESCE((
                    SELECT json_agg(json_build_object(
                             'path', pg.arquivo_path, 'data', pg.data_pagamento, 'valor', lig.valor)
                           ORDER BY pg.data_pagamento)
                    FROM fin_pagamento_pedido lig
                    JOIN fin_pagamentos_fornecedor pg ON pg.id = lig.pagamento_id
                    WHERE lig.pedido_id = p.id
                  ), '[]') AS comprovantes
           FROM fin_pedidos_fornecedor p
           JOIN fin_fornecedores f ON f.id = p.fornecedor_id
           WHERE p.data_pedido BETWEEN %s AND %s
           ORDER BY f.nome, p.data_pedido""",
        (inicio, fim),
    )
    contas = db.query(
        """SELECT 'CONTAS A PAGAR' AS fornecedor, c.vencimento AS data_compra,
                  c.descricao AS numero_pedido, c.valor, c.nf_path,
                  NULL AS pedido_path,
                  CASE WHEN c.status = 'pago' AND c.comprovante_path IS NOT NULL
                       THEN json_build_array(json_build_object(
                              'path', c.comprovante_path,
                              'data', COALESCE(c.data_pagamento, c.vencimento),
                              'valor', c.valor))
                       ELSE '[]' END AS comprovantes
           FROM fin_contas_pagar c
           WHERE c.categoria = 'FORNECEDOR' AND c.vencimento BETWEEN %s AND %s
           ORDER BY c.vencimento""",
        (inicio, fim),
    )
    return list(pedidos) + list(contas)


@bp.get("/compras/<mes>")
@require_auth
def baixar_compras(mes):
    if not re.fullmatch(r"\d{4}-\d{2}", mes):
        return jsonify({"error": "mês no formato AAAA-MM"}), 400
    ano, m = int(mes[:4]), int(mes[5:])
    if not 1 <= m <= 12:
        return jsonify({"error": "mês no formato AAAA-MM"}), 400
    inicio = date(ano, m, 1)
    fim = date(ano, m, calendar.monthrange(ano, m)[1])

    compras = _compras_do_mes(inicio.isoformat(), fim.isoformat())
    if not compras:
        return jsonify({"error": f"Nenhuma compra em {mes}."}), 404

    conteudo = pacote_zip.montar(compras)
    return Response(
        conteudo,
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="compras-{mes}.zip"'},
    )
```

```python
# app.py, junto dos outros registros de blueprint
from routes.pacote import bp as pacote_bp
app.register_blueprint(pacote_bp, url_prefix="/api/pacote")
```

- [ ] **Step 8: Rodar tudo e medir agosto**

Run: `python -m pytest -v`
Expected: PASS.

Depois do deploy, baixar agosto/2026 uma vez e anotar o tamanho do zip. Se passar de ~200 MB, abrir uma tarefa para escrever em arquivo temporário em vez de memória (está escrito na spec como decisão adiada).

- [ ] **Step 9: Commit e publicar o backend**

```bash
git add routes/pacote.py pacote_zip.py storage.py app.py requirements.txt tests/test_pacote_zip.py
git commit -m "feat: baixar o mês em zip, uma pasta por compra, com resumo"
git -c credential.helper= -c 'credential.helper=!f() { test "$1" = get || exit 0; echo username=cibellycarvalho; echo "password=$(gh auth token --user cibellycarvalho)"; }; f' push origin main
```

---

### Task 6: Frontend — clipe da nota fiscal na compra

**Files:**
- Modify: `src/pages/Fornecedores.jsx`, `src/services/api.js` (se precisar de helper de upload)
- Test: `src/pages/Fornecedores.nf.test.jsx` (criar)

**Interfaces:**
- Consumes: `POST /api/fornecedores/<f>/pedidos/<p>/nf` (multipart, campo `arquivo`), `GET .../nf` → `{url}`.
- Produces: nada que outra tarefa consuma.

- [ ] **Step 1: Escrever o teste que falha**

```jsx
// src/pages/Fornecedores.nf.test.jsx
import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import Fornecedores from './Fornecedores'

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
vi.mock('../components/Layout', () => ({ default: ({ children }) => <div>{children}</div> }))
import api from '../services/api'

const PEDIDO = { id: 'ped-1', data_pedido: '2026-08-17', valor_total: 30000, numero_pedido: '1234', itens: [], nf_path: null }

beforeEach(() => {
  api.get.mockReset(); api.post.mockReset()
  api.get.mockImplementation(url => {
    if (url === '/api/fornecedores') return Promise.resolve({ data: [{ id: 'f1', nome: 'Flávia', apelido: 'FL' }] })
    if (url.includes('/pedidos')) return Promise.resolve({ data: [PEDIDO] })
    return Promise.resolve({ data: [] })
  })
})

describe('Nota fiscal da compra', () => {
  it('mostra o clipe de nota fiscal na compra', async () => {
    render(<MemoryRouter><Fornecedores /></MemoryRouter>)
    expect(await screen.findByText(/Nota fiscal/)).toBeInTheDocument()
  })

  it('subir a nota manda o arquivo para a rota da compra', async () => {
    api.post.mockResolvedValue({ data: { nf_path: 'f1/notas/ped-1.pdf' } })
    render(<MemoryRouter><Fornecedores /></MemoryRouter>)
    const entrada = await screen.findByTestId('nf-ped-1')
    fireEvent.change(entrada, { target: { files: [new File(['x'], 'nota.pdf', { type: 'application/pdf' })] } })
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/fornecedores/f1/pedidos/ped-1/nf', expect.any(FormData), expect.anything(),
    ))
  })
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd financeiro-frontend && NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/Fornecedores.nf.test.jsx`
Expected: FAIL — não acha "Nota fiscal".

- [ ] **Step 3: Implementar o clipe**

Na linha de cada pedido em `src/pages/Fornecedores.jsx`, ao lado do clipe do pedido que já existe:

```jsx
<label style={{ cursor: 'pointer', fontSize: 12.5 }}>
  📎 {pedido.nf_path ? 'Nota fiscal' : 'Nota fiscal (sem)'}
  <input
    type="file"
    data-testid={`nf-${pedido.id}`}
    accept="application/pdf,image/jpeg,image/png"
    style={{ display: 'none' }}
    onChange={e => subirNota(pedido, e.target.files[0])}
  />
</label>
```

```jsx
async function subirNota(pedido, arquivo) {
  if (!arquivo) return
  if (pedido.nf_path && !confirm('Já tem nota nesta compra. Substituir?')) return
  const corpo = new FormData()
  corpo.append('arquivo', arquivo)
  try {
    const { data } = await api.post(
      `/api/fornecedores/${fornecedorSelecionado.id}/pedidos/${pedido.id}/nf`,
      corpo,
      { headers: { 'Content-Type': 'multipart/form-data' } },
    )
    atualizarPedido(pedido.id, { nf_path: data.nf_path })
  } catch (e) {
    setErro(e.response?.data?.error || 'Não consegui guardar a nota.')
  }
}
```

Abrir a nota: link que chama `GET .../nf` e abre `data.url` em nova aba, igual ao clipe do pedido que já existe no arquivo.

- [ ] **Step 4: Rodar os testes**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add src/pages/Fornecedores.jsx src/pages/Fornecedores.nf.test.jsx
git commit -m "feat: clipe de nota fiscal na compra do fornecedor"
```

---

### Task 7: Frontend — clipes na tela Contas a Pagar

**Files:**
- Modify: `src/pages/ContasPagar.jsx`
- Test: `src/pages/ContasPagar.test.jsx`

**Interfaces:**
- Consumes: `POST /api/contas/<id>/anexo/nf`, `POST /api/contas/<id>/anexo/comprovante`, `GET /api/contas/<id>/anexo/<tipo>`.

- [ ] **Step 1: Escrever os testes que falham**

```jsx
// no fim de src/pages/ContasPagar.test.jsx
it('mostra os dois clipes em cada conta', async () => {
  render(<MemoryRouter><ContasPagar /></MemoryRouter>)
  expect(await screen.findByTestId('nf-c1')).toBeInTheDocument()
  expect(screen.getByTestId('comprovante-c1')).toBeInTheDocument()
})

it('subir comprovante manda para a rota da conta', async () => {
  api.post.mockResolvedValue({ data: { comprovante_path: 'contas/comprovante/c1.pdf' } })
  render(<MemoryRouter><ContasPagar /></MemoryRouter>)
  const entrada = await screen.findByTestId('comprovante-c1')
  fireEvent.change(entrada, { target: { files: [new File(['x'], 'pix.pdf', { type: 'application/pdf' })] } })
  await waitFor(() => expect(api.post).toHaveBeenCalledWith(
    '/api/contas/c1/anexo/comprovante', expect.any(FormData), expect.anything(),
  ))
})
```

Ajustar o mock de `/api/contas` do arquivo para devolver uma conta com `id: 'c1'`, se ainda não devolver.

- [ ] **Step 2: Rodar e ver falhar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/ContasPagar.test.jsx`
Expected: FAIL — não acha `nf-c1`.

- [ ] **Step 3: Implementar**

Um helper só, com o tipo como parâmetro (o mesmo padrão dos dois clipes do DAS em `BlocoLancamentoFuncionario.jsx`):

```jsx
async function subirAnexoConta(conta, tipo, arquivo) {
  if (!arquivo) return
  const jaTem = tipo === 'nf' ? conta.nf_path : conta.comprovante_path
  if (jaTem && !confirm('Já tem arquivo aqui. Substituir?')) return
  const corpo = new FormData()
  corpo.append('arquivo', arquivo)
  try {
    const { data } = await api.post(`/api/contas/${conta.id}/anexo/${tipo}`, corpo,
      { headers: { 'Content-Type': 'multipart/form-data' } })
    atualizarConta(conta.id, data)
  } catch (e) {
    setErro(e.response?.data?.error || 'Não consegui guardar o arquivo.')
  }
}
```

E, na linha da conta, dois `<label>` com `data-testid={`nf-${conta.id}`}` e `data-testid={`comprovante-${conta.id}`}`, no mesmo formato do clipe da Task 6.

- [ ] **Step 4: Rodar os testes**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pages/ContasPagar.jsx src/pages/ContasPagar.test.jsx
git commit -m "feat: nota e comprovante anexados na conta a pagar"
```

---

### Task 8: Frontend — tela "Pix sem compra"

**Files:**
- Create: `src/components/PixSemCompra.jsx`, `src/components/PixSemCompra.test.jsx`
- Modify: `src/pages/Fornecedores.jsx` (mostrar a seção quando houver Pix solto)

**Interfaces:**
- Consumes: `GET /api/fornecedores/<f>/pagamentos/soltos`, `POST /api/fornecedores/<f>/pagamentos/<pg>/pedidos` com `{itens: [{pedido_id, valor}]}`, `DELETE` na mesma rota, e a lista de pedidos que a página já carrega.

- [ ] **Step 1: Escrever os testes que falham**

```jsx
// src/components/PixSemCompra.test.jsx
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import PixSemCompra from './PixSemCompra'

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() } }))
import api from '../services/api'

const SOLTOS = [{ id: 'pg-1', valor: 49310, data_pagamento: '2026-09-14', arquivo_path: null }]
const PEDIDOS = [
  { id: 'a', data_pedido: '2026-08-10', valor_total: 30000, numero_pedido: '10', pago_em: null },
  { id: 'b', data_pedido: '2026-08-11', valor_total: 19310, numero_pedido: '11', pago_em: null },
]

beforeEach(() => {
  api.get.mockReset(); api.post.mockReset()
  api.get.mockResolvedValue({ data: SOLTOS })
})

describe('Pix sem compra', () => {
  it('lista os Pix soltos do fornecedor', async () => {
    render(<PixSemCompra fornecedorId="f1" pedidos={PEDIDOS} aoMudar={() => {}} />)
    expect(await screen.findByText(/49.310,00/)).toBeInTheDocument()
  })

  it('divide o valor da mais antiga para a mais nova ao marcar duas compras', async () => {
    render(<PixSemCompra fornecedorId="f1" pedidos={PEDIDOS} aoMudar={() => {}} />)
    fireEvent.click(await screen.findByLabelText(/pedido 10/))
    fireEvent.click(screen.getByLabelText(/pedido 11/))
    fireEvent.click(screen.getByRole('button', { name: /Amarrar/ }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      '/api/fornecedores/f1/pagamentos/pg-1/pedidos',
      { itens: [{ pedido_id: 'a', valor: 30000 }, { pedido_id: 'b', valor: 19310 }] },
    ))
  })

  it('mostra o erro que o backend devolve, sem inventar texto', async () => {
    api.post.mockRejectedValue({ response: { data: { error: 'Essa compra só tem R$ 10,00 em aberto — o valor amarrado não pode passar disso.' } } })
    render(<PixSemCompra fornecedorId="f1" pedidos={PEDIDOS} aoMudar={() => {}} />)
    fireEvent.click(await screen.findByLabelText(/pedido 10/))
    fireEvent.click(screen.getByRole('button', { name: /Amarrar/ }))
    expect(await screen.findByText(/só tem R\$ 10,00 em aberto/)).toBeInTheDocument()
  })

  it('não aparece quando não há Pix solto', async () => {
    api.get.mockResolvedValue({ data: [] })
    const { container } = render(<PixSemCompra fornecedorId="f1" pedidos={PEDIDOS} aoMudar={() => {}} />)
    await waitFor(() => expect(container.textContent).not.toMatch(/Amarrar/))
  })
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/components/PixSemCompra.test.jsx`
Expected: FAIL — o arquivo não existe.

- [ ] **Step 3: Implementar o componente**

```jsx
// src/components/PixSemCompra.jsx
/**
 * Amarra um Pix às compras que ele pagou.
 *
 * Existe porque, em 23/09/2026, só 4 dos ~30 pagamentos lançados desde agosto
 * diziam qual compra pagaram — sem isso o comprovante não vai junto da nota no
 * pacote do mês. Um Pix pode cobrir mais de uma compra (o de R$ 49.310 pagou
 * 10/08 e 11/08), então a distribuição é da mais antiga para a mais nova e cada
 * valor pode ser editado à mão.
 */
import { useEffect, useState } from 'react'
import api from '../services/api'

const brl = v => Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

export default function PixSemCompra({ fornecedorId, pedidos, aoMudar }) {
  const [soltos, setSoltos] = useState([])
  const [escolhas, setEscolhas] = useState({})   // { [pagamentoId]: { [pedidoId]: valor } }
  const [erro, setErro] = useState(null)

  useEffect(() => {
    let vivo = true
    api.get(`/api/fornecedores/${fornecedorId}/pagamentos/soltos`)
      .then(r => vivo && setSoltos(r.data))
      .catch(() => vivo && setSoltos([]))
    return () => { vivo = false }
  }, [fornecedorId])

  if (!soltos.length) return null

  const emAberto = pedidos
    .filter(p => !p.pago_em)
    .sort((a, b) => String(a.data_pedido).localeCompare(String(b.data_pedido)))

  function alternar(pagamento, pedido) {
    setEscolhas(atual => {
      const desta = { ...(atual[pagamento.id] || {}) }
      if (desta[pedido.id] !== undefined) delete desta[pedido.id]
      else desta[pedido.id] = null
      // Distribui o valor do Pix da compra mais antiga para a mais nova.
      let restante = Number(pagamento.valor)
      const marcados = emAberto.filter(p => desta[p.id] !== undefined)
      marcados.forEach(p => {
        const cabe = Math.min(restante, Number(p.valor_total))
        desta[p.id] = Number(cabe.toFixed(2))
        restante -= cabe
      })
      return { ...atual, [pagamento.id]: desta }
    })
  }

  async function amarrar(pagamento) {
    const desta = escolhas[pagamento.id] || {}
    const itens = emAberto
      .filter(p => desta[p.id] !== undefined)
      .map(p => ({ pedido_id: p.id, valor: Number(desta[p.id]) }))
    setErro(null)
    try {
      await api.post(`/api/fornecedores/${fornecedorId}/pagamentos/${pagamento.id}/pedidos`, { itens })
      setSoltos(s => s.filter(x => x.id !== pagamento.id))
      aoMudar?.()
    } catch (e) {
      setErro(e.response?.data?.error || 'Não consegui amarrar. Tente de novo.')
    }
  }

  return (
    <section>
      <h3>Pix sem compra</h3>
      <p>Estes pagamentos ainda não dizem qual compra pagaram. Amarrar é opcional — serve para o comprovante ir junto da nota quando você baixar o mês.</p>
      {erro && <p role="alert">{erro}</p>}
      {soltos.map(pg => (
        <div key={pg.id}>
          <strong>{brl(pg.valor)}</strong> · {String(pg.data_pagamento).slice(0, 10).split('-').reverse().join('/')}
          {emAberto.map(p => (
            <label key={p.id}>
              <input
                type="checkbox"
                aria-label={`pedido ${p.numero_pedido || 'sem número'}`}
                checked={(escolhas[pg.id] || {})[p.id] !== undefined}
                onChange={() => alternar(pg, p)}
              />
              {`pedido ${p.numero_pedido || 'sem número'} · ${String(p.data_pedido).slice(0, 10)} · ${brl(p.valor_total)}`}
              {(escolhas[pg.id] || {})[p.id] !== undefined && (
                <input
                  type="number"
                  aria-label={`valor amarrado ao pedido ${p.numero_pedido || 'sem número'}`}
                  value={(escolhas[pg.id] || {})[p.id] ?? ''}
                  onChange={e => setEscolhas(a => ({
                    ...a, [pg.id]: { ...(a[pg.id] || {}), [p.id]: Number(e.target.value) },
                  }))}
                />
              )}
            </label>
          ))}
          <button onClick={() => amarrar(pg)}>Amarrar</button>
        </div>
      ))}
    </section>
  )
}
```

- [ ] **Step 4: Ligar na página**

Em `src/pages/Fornecedores.jsx`, dentro do fornecedor selecionado:

```jsx
<PixSemCompra
  fornecedorId={fornecedorSelecionado.id}
  pedidos={pedidos}
  aoMudar={() => recarregar()}
/>
```

- [ ] **Step 5: Rodar os testes**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/components/PixSemCompra.jsx src/components/PixSemCompra.test.jsx src/pages/Fornecedores.jsx
git commit -m "feat: tela para amarrar Pix solto às compras que ele pagou"
```

---

### Task 9: Frontend — botão "Baixar mês"

**Files:**
- Create: `src/components/BaixarMes.jsx`, `src/components/BaixarMes.test.jsx`
- Modify: `src/pages/Fornecedores.jsx`

**Interfaces:**
- Consumes: `GET /api/pacote/compras/<AAAA-MM>` com `responseType: 'blob'`.

- [ ] **Step 1: Escrever o teste que falha**

```jsx
// src/components/BaixarMes.test.jsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import BaixarMes from './BaixarMes'

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }))
import api from '../services/api'

beforeEach(() => {
  api.get.mockReset()
  global.URL.createObjectURL = vi.fn(() => 'blob:x')
  global.URL.revokeObjectURL = vi.fn()
})

describe('Baixar mês', () => {
  it('pede o zip do mês escolhido', async () => {
    api.get.mockResolvedValue({ data: new Blob(['zip']) })
    render(<BaixarMes />)
    fireEvent.change(screen.getByLabelText(/Mês/), { target: { value: '2026-08' } })
    fireEvent.click(screen.getByRole('button', { name: /Baixar mês/ }))
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(
      '/api/pacote/compras/2026-08', { responseType: 'blob' },
    ))
  })

  it('mês sem compra mostra o aviso do backend', async () => {
    api.get.mockRejectedValue({ response: { data: { error: 'Nenhuma compra em 2026-08.' } } })
    render(<BaixarMes />)
    fireEvent.change(screen.getByLabelText(/Mês/), { target: { value: '2026-08' } })
    fireEvent.click(screen.getByRole('button', { name: /Baixar mês/ }))
    expect(await screen.findByText(/Nenhuma compra em 2026-08/)).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/components/BaixarMes.test.jsx`
Expected: FAIL — o arquivo não existe.

- [ ] **Step 3: Implementar**

```jsx
// src/components/BaixarMes.jsx
/** Baixa o pacote do mês: uma pasta por compra, com nota, pedido e comprovantes. */
import { useState } from 'react'
import api from '../services/api'

function mesAtual() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

export default function BaixarMes() {
  const [mes, setMes] = useState(mesAtual())
  const [erro, setErro] = useState(null)
  const [baixando, setBaixando] = useState(false)

  async function baixar() {
    setErro(null)
    setBaixando(true)
    try {
      const { data } = await api.get(`/api/pacote/compras/${mes}`, { responseType: 'blob' })
      const url = URL.createObjectURL(data)
      const link = document.createElement('a')
      link.href = url
      link.download = `compras-${mes}.zip`
      link.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      // O erro do backend vem como blob quando responseType é blob.
      let msg = e.response?.data?.error
      if (!msg && e.response?.data instanceof Blob) {
        try { msg = JSON.parse(await e.response.data.text()).error } catch { /* fica o genérico */ }
      }
      setErro(msg || 'Não consegui montar o arquivo. Tente de novo.')
    } finally {
      setBaixando(false)
    }
  }

  return (
    <div>
      <label>
        Mês
        <input type="month" value={mes} onChange={e => setMes(e.target.value)} />
      </label>
      <button onClick={baixar} disabled={baixando}>
        {baixando ? 'Montando…' : 'Baixar mês'}
      </button>
      {erro && <p role="alert">{erro}</p>}
    </div>
  )
}
```

Colocar `<BaixarMes />` no topo de `src/pages/Fornecedores.jsx`, ao lado do título.

- [ ] **Step 4: Rodar tudo**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run`
Expected: PASS.

- [ ] **Step 5: Commit e publicar**

```bash
git add src/components/BaixarMes.jsx src/components/BaixarMes.test.jsx src/pages/Fornecedores.jsx
git commit -m "feat: botão para baixar o pacote do mês"
git -c credential.helper= -c 'credential.helper=!f() { test "$1" = get || exit 0; echo username=cibellycarvalho; echo "password=$(gh auth token --user cibellycarvalho)"; }; f' push origin main
```

---

### Task 10: Conferir no ar e escrever a regra

**Files:**
- Modify: `financeiro-frontend/docs/regras-caixa-semana.md` (uma seção nova sobre a amarração)

- [ ] **Step 1: Conferir no ar**

Depois do deploy automático (~40 s), com recarga forçada (Cmd+Shift+R):
1. Subir uma nota fiscal numa compra e abrir pelo clipe.
2. Subir nota e comprovante numa conta a pagar.
3. Amarrar um Pix solto a uma compra e desfazer.
4. Baixar agosto/2026 e abrir o zip: conferir que a compra de 17/08 da Flávia tem o comprovante do Pix de setembro dentro, e que o `resumo.xlsx` marca o que falta.

- [ ] **Step 2: Escrever a regra**

Acrescentar em `docs/regras-caixa-semana.md` uma seção curta: o pacote é do **mês da compra**, não do Pix; a amarração é opcional; nota e comprovante nunca são obrigatórios.

- [ ] **Step 3: Commit**

```bash
git add docs/regras-caixa-semana.md
git commit -m "docs: o pacote do mês é do mês da compra, não do Pix"
```
