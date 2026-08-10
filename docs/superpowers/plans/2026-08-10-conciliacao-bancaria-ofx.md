# Conciliação Bancária via OFX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the non-functional Pluggy bank-connection integration and replace it with OFX statement upload + assisted reconciliation (auto-suggested matches, human review, then apply).

**Architecture:** Flask blueprint `routes/conciliacao.py` backed by a new staging table `fin_extrato_transacoes`; a pure-function utility module `ofx_utils.py` handles OFX parsing and match-suggestion so both are unit-testable without mocking the database. React page `ConciliacaoBancaria.jsx` drives upload → review → confirm against the three new endpoints.

**Tech Stack:** Flask, psycopg2, `ofxparse` (new dependency), pytest, React, axios.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-10-conciliacao-bancaria-ofx-design.md`
- Matching window: exact `valor`, `data` within ±3 days (`JANELA_DIAS = 3`)
- Every new/modified `fin_` table follows the existing RLS pattern: SELECT for any `fin_user_roles` row, write for `fin_admin` only
- Backend code style: Flask blueprints under `routes/`, `db.query`/`db.execute`/`db.transaction()` from `db.py`, `@require_auth`/`@require_admin` from `auth.py` (see `routes/fornecedores.py` for the established pattern)
- Frontend style: inline `style={{...}}` objects, no CSS framework, pages live in `src/pages/`, shared chrome in `src/components/Layout.jsx`
- No frontend test framework exists in `financeiro-frontend` — frontend tasks are verified with `npm run build` plus manual review, not automated tests

---

### Task 1: Remove Pluggy integration — backend

**Files:**
- Delete: `routes/pluggy.py`
- Modify: `app.py`
- Modify: `config.py`

**Interfaces:**
- Consumes: nothing
- Produces: nothing (pure removal) — confirms `routes/repasses.py`'s unrelated `origem = 'pluggy'` string literal (Mercado Pago sync) is untouched

- [ ] **Step 1: Delete the Pluggy route file**

```bash
rm routes/pluggy.py
```

- [ ] **Step 2: Remove the Pluggy blueprint from app.py**

In `app.py`, remove this line from the imports block:

```python
    from routes.pluggy import bp as pluggy_bp
```

And remove this line from the registration block:

```python
    app.register_blueprint(pluggy_bp, url_prefix="/api/pluggy")
```

- [ ] **Step 3: Remove Pluggy config vars**

In `config.py`, remove:

```python
PLUGGY_CLIENT_ID = os.environ.get("PLUGGY_CLIENT_ID", "")
PLUGGY_CLIENT_SECRET = os.environ.get("PLUGGY_CLIENT_SECRET", "")
PLUGGY_REDIRECT_URL = os.environ.get(
    "PLUGGY_REDIRECT_URL",
    "https://financeiro.sellerml.com.br/api/pluggy/callback",
)
```

- [ ] **Step 4: Verify nothing else references the removed module**

```bash
grep -rn "routes.pluggy\|pluggy_bp\|PLUGGY_CLIENT\|PLUGGY_REDIRECT" . --include="*.py" | grep -v node_modules
```

Expected: no output.

- [ ] **Step 5: Run the existing test suite**

```bash
pytest -q
```

Expected: all tests pass (no test file references Pluggy today).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
remove: integração Pluggy do backend (trial expirado, nunca saiu de sandbox)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Remove Pluggy integration — frontend

**Files:**
- Modify: `../financeiro-frontend/src/pages/ContasPagar.jsx`

**Interfaces:**
- Consumes: nothing
- Produces: nothing (pure removal)

- [ ] **Step 1: Remove Pluggy state**

Remove these four lines from the top of `ContasPagar()` (`syncMsg` is only ever set by the
two Pluggy handlers removed in Step 2, and only read by the banner removed in Step 3 — it
has no other use in this file):

```jsx
  const [pluggyStatus, setPluggyStatus] = useState(null)
  const [syncLoading, setSyncLoading] = useState(false)
  const [syncMsg, setSyncMsg] = useState(null)
  const [connectLoading, setConnectLoading] = useState(false)
```

- [ ] **Step 2: Remove the Pluggy handlers**

Remove these three functions entirely:

```jsx
  async function carregarPluggyStatus() {
    try {
      const r = await api.get('/api/pluggy/status')
      setPluggyStatus(r.data)
    } catch {
      setPluggyStatus({ conectado: false, items: [] })
    }
  }
```

```jsx
  async function conectarSicredi() {
    setConnectLoading(true)
    setSyncMsg(null)
    try {
      const r = await api.post('/api/pluggy/connect-token')
      window.location.href = r.data.url
    } catch (err) {
      const msg = err.response?.data?.error || err.response?.data?.message || 'Erro ao gerar link. Verifique as configurações do Pluggy no servidor.'
      setSyncMsg({ tipo: 'erro', texto: msg })
      setConnectLoading(false)
    }
  }
```

```jsx
  async function sincronizarDDA() {
    setSyncLoading(true)
    setSyncMsg(null)
    try {
      const r = await api.post('/api/pluggy/sync')
      setSyncMsg({ tipo: 'ok', texto: `${r.data.sincronizados} lançamentos importados do Sicredi (${r.data.periodo}).` })
      await carregar()
    } catch (err) {
      setSyncMsg({ tipo: 'erro', texto: err.response?.data?.error || 'Erro ao sincronizar DDA.' })
    } finally {
      setSyncLoading(false)
    }
  }
```

Also remove the now-orphaned effect call:

```jsx
  useEffect(() => { carregarPluggyStatus() }, [])
```

(keep `useEffect(() => { carregar() }, [periodo])`)

- [ ] **Step 3: Remove the Pluggy button block and the sync message banner**

Replace:

```jsx
        {finRole === 'fin_admin' && (
          <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
            {pluggyStatus?.conectado ? (
              <button onClick={sincronizarDDA} disabled={syncLoading}
                style={{ padding:'8px 20px', background:'#7c3aed', color:'white', border:'none', borderRadius:8, cursor:'pointer', opacity: syncLoading ? 0.6 : 1 }}>
                {syncLoading ? 'Sincronizando...' : '↻ Sync DDA Sicredi'}
              </button>
            ) : (
              <button onClick={conectarSicredi} disabled={connectLoading}
                style={{ padding:'8px 20px', background:'#0ea5e9', color:'white', border:'none', borderRadius:8, cursor:'pointer', opacity: connectLoading ? 0.6 : 1 }}>
                {connectLoading ? 'Gerando link...' : '🔗 Conectar Sicredi'}
              </button>
            )}
            <button onClick={() => setShowForm(!showForm)}
              style={{ padding:'8px 20px', background:'#1a1a1a', color:'white', border:'none', borderRadius:8, cursor:'pointer' }}>
              + Nova conta
            </button>
          </div>
        )}
      </div>

      {syncMsg && (
        <div style={{ marginBottom:16, padding:'10px 16px', borderRadius:8,
          background: syncMsg.tipo === 'ok' ? '#22c55e22' : syncMsg.tipo === 'info' ? '#0ea5e922' : '#ef444422',
          color: syncMsg.tipo === 'ok' ? '#15803d' : syncMsg.tipo === 'info' ? '#0369a1' : '#b91c1c', fontSize:14 }}>
          {syncMsg.texto}
        </div>
      )}
```

with:

```jsx
        {finRole === 'fin_admin' && (
          <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
            <button onClick={() => setShowForm(!showForm)}
              style={{ padding:'8px 20px', background:'#1a1a1a', color:'white', border:'none', borderRadius:8, cursor:'pointer' }}>
              + Nova conta
            </button>
          </div>
        )}
      </div>
```

- [ ] **Step 4: Keep the DDA badge on existing rows, no change needed there**

The row rendering (`c.origem === 'dda'` badge) stays as-is — historical DDA-origin rows imported by the old Pluggy sync still exist in the table and should keep showing their badge. No code change in this step; just don't touch that block.

- [ ] **Step 5: Verify the build**

```bash
cd ../financeiro-frontend && npm run build
```

Expected: build succeeds with no errors (in particular no "unused variable" / "undefined reference" errors for the removed identifiers).

- [ ] **Step 6: Commit**

```bash
git add src/pages/ContasPagar.jsx
git commit -m "$(cat <<'EOF'
remove: UI de conexão Pluggy da tela de Contas a Pagar

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

(run from `financeiro-frontend`)

---

### Task 3: Migration — drop unused Pluggy tables

**Files:**
- Delete: `supabase/migrations/005_fin_pluggy_items.sql` (untracked leftover from an earlier debugging session — the table it creates already exists in production outside of any versioned migration, and is being dropped in this task instead)
- Create: `supabase/migrations/005_drop_fin_pluggy_tables.sql`

**Interfaces:**
- Consumes: nothing
- Produces: nothing (schema cleanup only)

- [ ] **Step 1: Remove the orphaned migration file**

```bash
rm supabase/migrations/005_fin_pluggy_items.sql
```

- [ ] **Step 2: Write the drop migration**

```sql
-- Task: Remoção da integração Pluggy (trial expirado, nunca saiu de sandbox)
-- Criado em: 2026-08-10

DROP TABLE IF EXISTS fin_pluggy_items;
DROP TABLE IF EXISTS fin_pluggy_connections;
```

Save as `supabase/migrations/005_drop_fin_pluggy_tables.sql`.

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/
git commit -m "$(cat <<'EOF'
feat: migração para remover tabelas fin_pluggy_items e fin_pluggy_connections

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

**Note for the human operator:** this migration needs to be run manually in the Supabase SQL Editor (project `tywirfmaosfztcmalbno`) — this repo's migrations are not auto-applied on deploy.

---

### Task 4: OFX parsing utility

**Files:**
- Create: `ofx_utils.py`
- Create: `tests/fixtures/extrato_exemplo.ofx`
- Test: `tests/test_ofx_utils.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: `ofxparse.OfxParser` (new dependency)
- Produces: `parse_ofx(file_stream) -> list[dict]`, each dict shaped
  `{"fitid": str, "tipo": "DEBIT"|"CREDIT", "valor": float, "data": "YYYY-MM-DD", "descricao": str}`.
  Used by Task 7.

- [ ] **Step 1: Add the OFX parsing dependency**

In `requirements.txt`, add:

```
ofxparse==0.21
```

Install it locally:

```bash
pip install ofxparse==0.21
```

- [ ] **Step 2: Write the OFX fixture file**

Create `tests/fixtures/extrato_exemplo.ofx`:

```
OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<DTSERVER>20260809120000
<LANGUAGE>POR
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>748
<ACCTID>12345-6
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260701
<DTEND>20260809
<STMTTRN>
<TRNTYPE>DEBIT
<DTPOSTED>20260805
<TRNAMT>-450.00
<FITID>2026080500001
<MEMO>Pagamento Fornecedor Flavia
</STMTTRN>
<STMTTRN>
<TRNTYPE>CREDIT
<DTPOSTED>20260806
<TRNAMT>1200.50
<FITID>2026080600002
<MEMO>Repasse Mercado Livre
</STMTTRN>
</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>5000.00
<DTASOF>20260809
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_ofx_utils.py`:

```python
import os
from ofx_utils import parse_ofx

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "extrato_exemplo.ofx")


def test_parse_ofx_extrai_debito_e_credito():
    with open(FIXTURE_PATH, "rb") as f:
        transacoes = parse_ofx(f)

    assert len(transacoes) == 2

    debito = next(t for t in transacoes if t["tipo"] == "DEBIT")
    assert debito["valor"] == 450.00
    assert debito["data"] == "2026-08-05"
    assert debito["fitid"] == "2026080500001"
    assert "Flavia" in debito["descricao"]

    credito = next(t for t in transacoes if t["tipo"] == "CREDIT")
    assert credito["valor"] == 1200.50
    assert credito["data"] == "2026-08-06"
    assert credito["fitid"] == "2026080600002"
```

- [ ] **Step 4: Run test to verify it fails**

```bash
pytest tests/test_ofx_utils.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ofx_utils'`.

- [ ] **Step 5: Implement `parse_ofx`**

Create `ofx_utils.py`:

```python
from datetime import timedelta
from ofxparse import OfxParser

JANELA_DIAS = 3


def parse_ofx(file_stream):
    ofx = OfxParser.parse(file_stream)
    account = ofx.accounts[0]
    transacoes = []
    for txn in account.statement.transactions:
        valor = float(txn.amount)
        transacoes.append({
            "fitid": txn.id,
            "tipo": "CREDIT" if valor > 0 else "DEBIT",
            "valor": round(abs(valor), 2),
            "data": txn.date.date().isoformat(),
            "descricao": (txn.memo or txn.payee or "")[:200],
        })
    return transacoes
```

- [ ] **Step 6: Run test to verify it passes**

```bash
pytest tests/test_ofx_utils.py -v
```

Expected: PASS. If `ofxparse`'s actual attribute names differ from what's used above (library version drift), adjust `parse_ofx` to match what `OfxParser.parse()` really returns — inspect with `python -c "from ofxparse import OfxParser; print(vars(OfxParser.parse(open('tests/fixtures/extrato_exemplo.ofx','rb')).accounts[0].statement.transactions[0]))"` and fix field names accordingly, keeping the function's return shape (`fitid`/`tipo`/`valor`/`data`/`descricao`) unchanged since Task 7 depends on it.

- [ ] **Step 7: Commit**

```bash
git add ofx_utils.py tests/test_ofx_utils.py tests/fixtures/extrato_exemplo.ofx requirements.txt
git commit -m "$(cat <<'EOF'
feat: utilitário de parse de extrato OFX

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Transaction-matching utility

**Files:**
- Modify: `ofx_utils.py`
- Test: `tests/test_ofx_utils.py`

**Interfaces:**
- Consumes: `JANELA_DIAS` (defined in Task 4, same file)
- Produces: `melhor_candidato(data_transacao: date, candidatos: list[dict], usados: set[tuple[str,str]]) -> dict | None`.
  Each candidato dict has at least `{"id": str, "data": date, "tabela": str}`. Used by Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ofx_utils.py`:

```python
from datetime import date
from ofx_utils import melhor_candidato


def test_melhor_candidato_escolhe_mais_proximo_na_janela():
    candidatos = [
        {"id": "a1", "data": date(2026, 8, 2), "tabela": "fin_contas_pagar"},
        {"id": "a2", "data": date(2026, 8, 5), "tabela": "fin_contas_pagar"},
    ]
    resultado = melhor_candidato(date(2026, 8, 5), candidatos, usados=set())
    assert resultado["id"] == "a2"


def test_melhor_candidato_ignora_fora_da_janela():
    candidatos = [{"id": "a1", "data": date(2026, 7, 1), "tabela": "fin_contas_pagar"}]
    resultado = melhor_candidato(date(2026, 8, 5), candidatos, usados=set())
    assert resultado is None


def test_melhor_candidato_ignora_ids_ja_usados():
    candidatos = [{"id": "a1", "data": date(2026, 8, 5), "tabela": "fin_contas_pagar"}]
    resultado = melhor_candidato(date(2026, 8, 5), candidatos, usados={("fin_contas_pagar", "a1")})
    assert resultado is None


def test_melhor_candidato_retorna_none_sem_candidatos():
    assert melhor_candidato(date(2026, 8, 5), [], usados=set()) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_ofx_utils.py -v -k melhor_candidato
```

Expected: FAIL with `ImportError: cannot import name 'melhor_candidato'`.

- [ ] **Step 3: Implement `melhor_candidato`**

Append to `ofx_utils.py`:

```python
def melhor_candidato(data_transacao, candidatos, usados):
    melhor = None
    menor_diff = None
    for c in candidatos:
        chave = (c["tabela"], c["id"])
        if chave in usados:
            continue
        diff = abs((c["data"] - data_transacao).days)
        if diff > JANELA_DIAS:
            continue
        if menor_diff is None or diff < menor_diff:
            menor_diff = diff
            melhor = c
    return melhor
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_ofx_utils.py -v
```

Expected: all PASS (6 tests total between this and Task 4).

- [ ] **Step 5: Commit**

```bash
git add ofx_utils.py tests/test_ofx_utils.py
git commit -m "$(cat <<'EOF'
feat: utilitário de casamento de transações por valor+data

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Migration — fin_extrato_transacoes + link columns

**Files:**
- Create: `supabase/migrations/006_fin_extrato_transacoes.sql`

**Interfaces:**
- Consumes: nothing
- Produces: table `fin_extrato_transacoes` and `ofx_transacao_id` columns on
  `fin_contas_pagar`, `fin_pedido_pagamentos`, `fin_repasses_ml`, and `'ofx'` as a valid
  `fin_contas_pagar.origem` value. Used by Tasks 7-9.

- [ ] **Step 1: Write the migration**

```sql
-- Task: Conciliação bancária via importação de OFX
-- Criado em: 2026-08-10

-- ============================================================================
-- Tabela: fin_extrato_transacoes
-- ============================================================================
CREATE TABLE fin_extrato_transacoes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lote_id UUID NOT NULL,
  fitid TEXT NOT NULL UNIQUE,
  tipo TEXT NOT NULL CHECK (tipo IN ('DEBIT','CREDIT')),
  valor NUMERIC(12,2) NOT NULL,
  data DATE NOT NULL,
  descricao TEXT,
  status TEXT NOT NULL DEFAULT 'pendente'
    CHECK (status IN ('pendente','conciliado','ignorado','nova_conta')),
  match_tabela TEXT CHECK (match_tabela IN ('fin_contas_pagar','fin_pedido_pagamentos','fin_repasses_ml')),
  match_id UUID,
  criado_por UUID REFERENCES auth.users(id),
  criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_extrato_lote ON fin_extrato_transacoes(lote_id);

-- ============================================================================
-- Colunas de link nas tabelas existentes
-- ============================================================================
ALTER TABLE fin_contas_pagar ADD COLUMN ofx_transacao_id UUID REFERENCES fin_extrato_transacoes(id);
ALTER TABLE fin_pedido_pagamentos ADD COLUMN ofx_transacao_id UUID REFERENCES fin_extrato_transacoes(id);
ALTER TABLE fin_repasses_ml ADD COLUMN ofx_transacao_id UUID REFERENCES fin_extrato_transacoes(id);

-- Permite origem = 'ofx' em fin_contas_pagar (contas criadas a partir da conciliação)
ALTER TABLE fin_contas_pagar DROP CONSTRAINT fin_contas_pagar_origem_check;
ALTER TABLE fin_contas_pagar ADD CONSTRAINT fin_contas_pagar_origem_check
  CHECK (origem IN ('manual','pluggy','dda','ofx'));

-- ============================================================================
-- Row Level Security (RLS) — mesmo padrão das demais tabelas fin_
-- ============================================================================
ALTER TABLE fin_extrato_transacoes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "fin_select" ON fin_extrato_transacoes FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
CREATE POLICY "fin_write" ON fin_extrato_transacoes FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
```

Save as `supabase/migrations/006_fin_extrato_transacoes.sql`.

- [ ] **Step 2: Commit**

```bash
git add supabase/migrations/006_fin_extrato_transacoes.sql
git commit -m "$(cat <<'EOF'
feat: migração para tabela de staging da conciliação bancária (OFX)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

**Note for the human operator:** run this migration in the Supabase SQL Editor (project
`tywirfmaosfztcmalbno`) — required before Task 7's endpoint works against production.
If `fin_contas_pagar_origem_check` isn't the actual constraint name in production, find it
with `SELECT conname FROM pg_constraint WHERE conrelid = 'fin_contas_pagar'::regclass AND contype = 'c'`
before running the `DROP CONSTRAINT` line.

---

### Task 7: Endpoint — importar extrato

**Files:**
- Create: `routes/conciliacao.py`
- Modify: `app.py`
- Test: `tests/test_conciliacao.py`

**Interfaces:**
- Consumes: `parse_ofx`, `melhor_candidato`, `JANELA_DIAS` from `ofx_utils` (Tasks 4-5);
  tables from Task 6
- Produces: `POST /api/conciliacao/importar` — multipart field `arquivo` (.ofx), admin only.
  Response `{"lote_id": str|None, "total": int, "duplicadas": int, "casadas": int,
  "sem_match": int, "novas": int}`, status 201. `lote_id` is `None` when every transaction
  in the file was already imported before. Used by Task 10.

- [ ] **Step 1: Write the failing test**

Create `tests/test_conciliacao.py`:

```python
import io
import os
from datetime import date
from unittest.mock import patch, MagicMock

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "extrato_exemplo.ofx")


def _mock_transaction_cursor(fetchone_results, fetchall_results):
    mock_cur = MagicMock()
    mock_cur.fetchone.side_effect = fetchone_results
    mock_cur.fetchall.side_effect = fetchall_results
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value = mock_cur
    mock_ctx.__exit__.return_value = False
    mock_transaction = MagicMock(return_value=mock_ctx)
    return mock_transaction, mock_cur


def test_importar_casa_credito_e_cria_pendencia_para_debito(client, admin_headers):
    fixture_bytes = open(FIXTURE_PATH, "rb").read()
    match_repasse = {"id": "r1", "data": date(2026, 8, 6), "descricao": "Repasse ML Agosto"}

    mock_transaction, mock_cur = _mock_transaction_cursor(
        fetchone_results=[None, None],
        fetchall_results=[[], [], [match_repasse]],
    )

    with patch("routes.conciliacao.db.transaction", mock_transaction):
        resp = client.post(
            "/api/conciliacao/importar",
            data={"arquivo": (io.BytesIO(fixture_bytes), "extrato.ofx")},
            content_type="multipart/form-data",
            headers=admin_headers,
        )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["total"] == 2
    assert body["duplicadas"] == 0
    assert body["casadas"] == 1
    assert body["novas"] == 1
    assert body["sem_match"] == 0
    assert body["lote_id"] is not None


def test_importar_todas_duplicadas_retorna_lote_id_none(client, admin_headers):
    fixture_bytes = open(FIXTURE_PATH, "rb").read()
    mock_transaction, mock_cur = _mock_transaction_cursor(
        fetchone_results=[{"id": "existing1"}, {"id": "existing2"}],
        fetchall_results=[],
    )

    with patch("routes.conciliacao.db.transaction", mock_transaction):
        resp = client.post(
            "/api/conciliacao/importar",
            data={"arquivo": (io.BytesIO(fixture_bytes), "extrato.ofx")},
            content_type="multipart/form-data",
            headers=admin_headers,
        )

    assert resp.status_code == 201
    body = resp.get_json()
    assert body["lote_id"] is None
    assert body["duplicadas"] == 2


def test_importar_sem_arquivo_retorna_400(client, admin_headers):
    resp = client.post("/api/conciliacao/importar", headers=admin_headers)
    assert resp.status_code == 400


def test_importar_negado_para_viewer(client, viewer_headers):
    fixture_bytes = open(FIXTURE_PATH, "rb").read()
    resp = client.post(
        "/api/conciliacao/importar",
        data={"arquivo": (io.BytesIO(fixture_bytes), "extrato.ofx")},
        content_type="multipart/form-data",
        headers=viewer_headers,
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_conciliacao.py -v
```

Expected: FAIL — `routes.conciliacao` doesn't exist yet (collection error) or 404s once the
blueprint is registered but before `/importar` exists.

- [ ] **Step 3: Add the dependency and register the blueprint**

`requirements.txt` already has `ofxparse` from Task 4 — no change needed here.

In `app.py`, add to the imports block:

```python
    from routes.conciliacao import bp as conciliacao_bp
```

And to the registration block:

```python
    app.register_blueprint(conciliacao_bp, url_prefix="/api/conciliacao")
```

- [ ] **Step 4: Implement the endpoint**

Create `routes/conciliacao.py`:

```python
import uuid
from datetime import date, timedelta
from flask import Blueprint, request, jsonify, g
import db
from auth import require_auth, require_admin
from ofx_utils import parse_ofx, melhor_candidato, JANELA_DIAS

bp = Blueprint("conciliacao", __name__)


@bp.post("/importar")
@require_auth
@require_admin
def importar():
    arquivo = request.files.get("arquivo")
    if not arquivo:
        return jsonify({"error": "arquivo .ofx obrigatório"}), 400

    try:
        transacoes = parse_ofx(arquivo.stream)
    except Exception:
        return jsonify({"error": "Arquivo OFX inválido"}), 400

    if not transacoes:
        return jsonify({"error": "Nenhuma transação encontrada no arquivo"}), 400

    lote_id = str(uuid.uuid4())
    usados = set()
    duplicadas = casadas = sem_match = novas = 0

    with db.transaction() as cur:
        for txn in transacoes:
            cur.execute("SELECT id FROM fin_extrato_transacoes WHERE fitid = %s", (txn["fitid"],))
            if cur.fetchone():
                duplicadas += 1
                continue

            data_txn = date.fromisoformat(txn["data"])
            data_min = data_txn - timedelta(days=JANELA_DIAS)
            data_max = data_txn + timedelta(days=JANELA_DIAS)
            candidatos = []

            if txn["tipo"] == "DEBIT":
                cur.execute(
                    """SELECT id, data_pagamento AS data, descricao FROM fin_contas_pagar
                       WHERE status = 'pago' AND ofx_transacao_id IS NULL
                         AND valor = %s AND data_pagamento BETWEEN %s AND %s""",
                    (txn["valor"], data_min, data_max),
                )
                candidatos += [{**dict(r), "tabela": "fin_contas_pagar"} for r in cur.fetchall()]

                cur.execute(
                    """SELECT pp.id, pp.data_pagamento AS data, pf.nome AS descricao
                       FROM fin_pedido_pagamentos pp
                       JOIN fin_pedidos_fornecedor pd ON pd.id = pp.pedido_id
                       JOIN fin_fornecedores pf ON pf.id = pd.fornecedor_id
                       WHERE pp.ofx_transacao_id IS NULL AND pp.valor = %s
                         AND pp.data_pagamento BETWEEN %s AND %s""",
                    (txn["valor"], data_min, data_max),
                )
                candidatos += [{**dict(r), "tabela": "fin_pedido_pagamentos"} for r in cur.fetchall()]
            else:
                cur.execute(
                    """SELECT id, data_referencia AS data, descricao FROM fin_repasses_ml
                       WHERE ofx_transacao_id IS NULL AND valor = %s
                         AND data_referencia BETWEEN %s AND %s""",
                    (txn["valor"], data_min, data_max),
                )
                candidatos += [{**dict(r), "tabela": "fin_repasses_ml"} for r in cur.fetchall()]

            match = melhor_candidato(data_txn, candidatos, usados)
            if match:
                usados.add((match["tabela"], match["id"]))
                casadas += 1
            elif txn["tipo"] == "DEBIT":
                novas += 1
            else:
                sem_match += 1

            cur.execute(
                """INSERT INTO fin_extrato_transacoes
                     (lote_id, fitid, tipo, valor, data, descricao, match_tabela, match_id, criado_por)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    lote_id, txn["fitid"], txn["tipo"], txn["valor"], data_txn, txn["descricao"],
                    match["tabela"] if match else None, match["id"] if match else None,
                    g.user["user_id"],
                ),
            )

    inseridas = casadas + sem_match + novas
    return jsonify({
        "lote_id": lote_id if inseridas > 0 else None,
        "total": len(transacoes),
        "duplicadas": duplicadas,
        "casadas": casadas,
        "sem_match": sem_match,
        "novas": novas,
    }), 201
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/test_conciliacao.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add routes/conciliacao.py app.py tests/test_conciliacao.py
git commit -m "$(cat <<'EOF'
feat: endpoint de importação de extrato OFX com casamento automático

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Endpoint — listar lote

**Files:**
- Modify: `routes/conciliacao.py`
- Test: `tests/test_conciliacao.py`

**Interfaces:**
- Consumes: `fin_extrato_transacoes` rows written by Task 7
- Produces: `GET /api/conciliacao/lotes/<lote_id>` — any authenticated `fin_role`.
  Response: list of transacao dicts (all `fin_extrato_transacoes` columns) plus
  `match_descricao` (str or None). 404 if the lote has no transactions. Used by Task 10.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_conciliacao.py`:

```python
def test_listar_lote(client, admin_headers):
    lote_id = "11111111-0000-0000-0000-000000000001"
    transacao = {
        "id": "22222222-0000-0000-0000-000000000001", "lote_id": lote_id,
        "fitid": "2026080500001", "tipo": "DEBIT", "valor": 450.00,
        "data": "2026-08-05", "descricao": "Pagamento Fornecedor Flavia",
        "status": "pendente", "match_tabela": "fin_contas_pagar",
        "match_id": "33333333-0000-0000-0000-000000000001",
        "criado_por": None, "criado_em": "2026-08-10T10:00:00+00:00",
    }
    match_row = {"descricao": "Conta de luz", "valor": 450.00}

    with patch("routes.conciliacao.db.query", side_effect=[[transacao], [match_row]]):
        resp = client.get(f"/api/conciliacao/lotes/{lote_id}", headers=admin_headers)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body[0]["match_descricao"] == "Conta de luz"


def test_listar_lote_nao_encontrado(client, admin_headers):
    with patch("routes.conciliacao.db.query", return_value=[]):
        resp = client.get("/api/conciliacao/lotes/inexistente", headers=admin_headers)
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_conciliacao.py -v -k listar_lote
```

Expected: FAIL with 404 for both (route doesn't exist yet).

- [ ] **Step 3: Implement the endpoint**

Append to `routes/conciliacao.py`:

```python
@bp.get("/lotes/<lote_id>")
@require_auth
def listar_lote(lote_id):
    transacoes = db.query(
        "SELECT * FROM fin_extrato_transacoes WHERE lote_id = %s ORDER BY data", (lote_id,)
    )
    if not transacoes:
        return jsonify({"error": "Lote não encontrado"}), 404

    resultado = []
    for t in transacoes:
        item = dict(t)
        row = []
        if t["match_tabela"] == "fin_contas_pagar":
            row = db.query("SELECT descricao, valor FROM fin_contas_pagar WHERE id = %s", (t["match_id"],))
        elif t["match_tabela"] == "fin_pedido_pagamentos":
            row = db.query(
                """SELECT pf.nome AS descricao, pp.valor FROM fin_pedido_pagamentos pp
                   JOIN fin_pedidos_fornecedor pd ON pd.id = pp.pedido_id
                   JOIN fin_fornecedores pf ON pf.id = pd.fornecedor_id
                   WHERE pp.id = %s""",
                (t["match_id"],),
            )
        elif t["match_tabela"] == "fin_repasses_ml":
            row = db.query("SELECT descricao, valor FROM fin_repasses_ml WHERE id = %s", (t["match_id"],))
        item["match_descricao"] = row[0]["descricao"] if row else None
        resultado.append(item)

    return jsonify(resultado)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_conciliacao.py -v
```

Expected: all PASS (6 tests total between Tasks 7-8).

- [ ] **Step 5: Commit**

```bash
git add routes/conciliacao.py tests/test_conciliacao.py
git commit -m "$(cat <<'EOF'
feat: endpoint de listagem de lote de conciliação para revisão

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Endpoint — confirmar lote

**Files:**
- Modify: `routes/conciliacao.py`
- Test: `tests/test_conciliacao.py`

**Interfaces:**
- Consumes: `fin_extrato_transacoes` rows (Task 7/8)
- Produces: `POST /api/conciliacao/lotes/<lote_id>/confirmar` — admin only.
  Request: `{"itens": [{"transacao_id": str, "acao": "confirmar_match"|"ignorar"|"criar_conta"}]}`.
  Response: `{"confirmados": int}`. Used by Task 10.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_conciliacao.py`:

```python
def test_confirmar_lote_aplica_acoes(client, admin_headers):
    lote_id = "11111111-0000-0000-0000-000000000001"
    transacao_match = {
        "id": "t1", "match_tabela": "fin_contas_pagar", "match_id": "c1",
        "tipo": "DEBIT", "valor": 450.00, "data": "2026-08-05", "descricao": "Pagamento X",
    }
    transacao_nova = {
        "id": "t2", "match_tabela": None, "match_id": None,
        "tipo": "DEBIT", "valor": 100.00, "data": "2026-08-06", "descricao": "Compra Y",
    }
    transacao_ignorar = {
        "id": "t3", "match_tabela": None, "match_id": None,
        "tipo": "CREDIT", "valor": 50.00, "data": "2026-08-07", "descricao": "Depósito Z",
    }
    mock_transaction, mock_cur = _mock_transaction_cursor(fetchone_results=[], fetchall_results=[])

    with patch("routes.conciliacao.db.query", return_value=[transacao_match, transacao_nova, transacao_ignorar]), \
         patch("routes.conciliacao.db.transaction", mock_transaction):
        resp = client.post(
            f"/api/conciliacao/lotes/{lote_id}/confirmar",
            json={"itens": [
                {"transacao_id": "t1", "acao": "confirmar_match"},
                {"transacao_id": "t2", "acao": "criar_conta"},
                {"transacao_id": "t3", "acao": "ignorar"},
            ]},
            headers=admin_headers,
        )

    assert resp.status_code == 200
    assert resp.get_json()["confirmados"] == 3


def test_confirmar_lote_acao_invalida(client, admin_headers):
    resp = client.post(
        "/api/conciliacao/lotes/lote1/confirmar",
        json={"itens": [{"transacao_id": "t1", "acao": "chutar"}]},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_confirmar_lote_sem_itens(client, admin_headers):
    resp = client.post(
        "/api/conciliacao/lotes/lote1/confirmar",
        json={"itens": []},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_confirmar_lote_negado_para_viewer(client, viewer_headers):
    resp = client.post(
        "/api/conciliacao/lotes/lote1/confirmar",
        json={"itens": [{"transacao_id": "t1", "acao": "ignorar"}]},
        headers=viewer_headers,
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_conciliacao.py -v -k confirmar_lote
```

Expected: FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3: Implement the endpoint**

Append to `routes/conciliacao.py`:

```python
ACOES_VALIDAS = {"confirmar_match", "ignorar", "criar_conta"}


@bp.post("/lotes/<lote_id>/confirmar")
@require_auth
@require_admin
def confirmar_lote(lote_id):
    data = request.get_json()
    itens = data.get("itens", [])
    if not itens:
        return jsonify({"error": "nenhum item para confirmar"}), 400
    for item in itens:
        if item.get("acao") not in ACOES_VALIDAS:
            return jsonify({"error": f"ação inválida: {item.get('acao')}"}), 400

    transacoes = db.query("SELECT * FROM fin_extrato_transacoes WHERE lote_id = %s", (lote_id,))
    transacoes_por_id = {str(t["id"]): t for t in transacoes}

    with db.transaction() as cur:
        for item in itens:
            transacao = transacoes_por_id.get(item["transacao_id"])
            if not transacao:
                continue

            if item["acao"] == "confirmar_match":
                tabela, alvo_id = transacao["match_tabela"], transacao["match_id"]
                if not tabela:
                    continue
                cur.execute(f"UPDATE {tabela} SET ofx_transacao_id = %s WHERE id = %s", (transacao["id"], alvo_id))
                if tabela == "fin_repasses_ml":
                    cur.execute("UPDATE fin_repasses_ml SET confirmado = true WHERE id = %s", (alvo_id,))
                cur.execute("UPDATE fin_extrato_transacoes SET status = 'conciliado' WHERE id = %s", (transacao["id"],))

            elif item["acao"] == "criar_conta":
                cur.execute(
                    """INSERT INTO fin_contas_pagar
                         (descricao, categoria, valor, vencimento, marca, status, origem, ofx_transacao_id)
                       VALUES (%s, 'OUTRO', %s, %s, 'GERAL', 'a_confirmar', 'ofx', %s)""",
                    (transacao["descricao"] or "Importado do extrato", transacao["valor"],
                     transacao["data"], transacao["id"]),
                )
                cur.execute("UPDATE fin_extrato_transacoes SET status = 'nova_conta' WHERE id = %s", (transacao["id"],))

            else:
                cur.execute("UPDATE fin_extrato_transacoes SET status = 'ignorado' WHERE id = %s", (transacao["id"],))

    return jsonify({"confirmados": len(itens)})
```

`tabela` in the f-string on the `UPDATE {tabela} SET ...` line is never client-controlled —
it comes from `fin_extrato_transacoes.match_tabela`, which Task 6's migration restricts via
`CHECK (match_tabela IN ('fin_contas_pagar','fin_pedido_pagamentos','fin_repasses_ml'))` and
which only Task 7's own `importar()` ever writes. Not a SQL-injection vector.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_conciliacao.py -v
```

Expected: all PASS (10 tests total across Tasks 7-9).

- [ ] **Step 5: Commit**

```bash
git add routes/conciliacao.py tests/test_conciliacao.py
git commit -m "$(cat <<'EOF'
feat: endpoint de confirmação de lote de conciliação bancária

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Frontend — página de Conciliação Bancária

**Files:**
- Create: `../financeiro-frontend/src/pages/ConciliacaoBancaria.jsx`
- Modify: `../financeiro-frontend/src/App.jsx`
- Modify: `../financeiro-frontend/src/components/Layout.jsx`

**Interfaces:**
- Consumes: `POST /api/conciliacao/importar`, `GET /api/conciliacao/lotes/:id`,
  `POST /api/conciliacao/lotes/:id/confirmar` (Tasks 7-9); `api` from `../services/api`;
  `Layout` from `../components/Layout`; `useAuth` from `../contexts/AuthContext`
- Produces: route `/conciliacao`, nav entry "Conciliação Bancária" (admin only)

- [ ] **Step 1: Add the route**

In `../financeiro-frontend/src/App.jsx`, add the import:

```jsx
import ConciliacaoBancaria from './pages/ConciliacaoBancaria'
```

And add the route inside `<Routes>`, next to the other `ProtectedRoute`-wrapped pages:

```jsx
          <Route path="/conciliacao" element={<ProtectedRoute><AdminRoute><ConciliacaoBancaria /></AdminRoute></ProtectedRoute>} />
```

- [ ] **Step 2: Add the nav link**

In `../financeiro-frontend/src/components/Layout.jsx`, after the existing admin-only Link
block, add a second conditional link (uploading/confirming is an admin-only action, so
non-admins shouldn't see the entry point):

```jsx
        {finRole === 'fin_admin' && (
          <Link to="/conciliacao" style={{
            padding:'10px 20px', color: pathname === '/conciliacao' ? '#fff' : '#aaa',
            background: pathname === '/conciliacao' ? '#333' : 'transparent',
            textDecoration:'none', fontSize:14
          }}>
            Conciliação Bancária
          </Link>
        )}
```

Place it right before the existing:

```jsx
        {finRole === 'fin_admin' && (
          <Link to="/admin" style={{ padding:'10px 20px', color:'#aaa', textDecoration:'none', fontSize:14, marginTop:'auto' }}>
            Admin
          </Link>
        )}
```

- [ ] **Step 3: Build the page**

Create `../financeiro-frontend/src/pages/ConciliacaoBancaria.jsx`:

```jsx
import { useState } from 'react'
import Layout from '../components/Layout'
import api from '../services/api'

const ACOES = [
  { valor: 'confirmar_match', label: 'Confirmar' },
  { valor: 'criar_conta', label: 'Criar conta nova' },
  { valor: 'ignorar', label: 'Ignorar' },
]

export default function ConciliacaoBancaria() {
  const [resumo, setResumo] = useState(null)
  const [transacoes, setTransacoes] = useState([])
  const [acoes, setAcoes] = useState({})
  const [enviando, setEnviando] = useState(false)
  const [msg, setMsg] = useState(null)

  async function handleUpload(e) {
    const arquivo = e.target.files[0]
    if (!arquivo) return
    setMsg(null)
    const formData = new FormData()
    formData.append('arquivo', arquivo)
    try {
      const r = await api.post('/api/conciliacao/importar', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setResumo(r.data)
      if (r.data.lote_id) {
        const lote = await api.get(`/api/conciliacao/lotes/${r.data.lote_id}`)
        setTransacoes(lote.data)
        const acoesIniciais = {}
        lote.data.forEach(t => {
          acoesIniciais[t.id] = t.match_tabela ? 'confirmar_match' : (t.tipo === 'DEBIT' ? 'criar_conta' : 'ignorar')
        })
        setAcoes(acoesIniciais)
      } else {
        setTransacoes([])
      }
    } catch (err) {
      setMsg({ tipo: 'erro', texto: err.response?.data?.error || 'Erro ao importar extrato.' })
    }
    e.target.value = ''
  }

  async function confirmar() {
    setEnviando(true)
    try {
      const itens = transacoes.map(t => ({ transacao_id: t.id, acao: acoes[t.id] }))
      await api.post(`/api/conciliacao/lotes/${resumo.lote_id}/confirmar`, { itens })
      setMsg({ tipo: 'ok', texto: 'Conciliação aplicada com sucesso.' })
      setTransacoes([])
      setResumo(null)
    } catch (err) {
      setMsg({ tipo: 'erro', texto: err.response?.data?.error || 'Erro ao confirmar conciliação.' })
    } finally {
      setEnviando(false)
    }
  }

  return (
    <Layout>
      <h1 style={{ marginTop:0 }}>Conciliação Bancária</h1>

      <div style={{ background:'white', borderRadius:12, padding:24, marginBottom:24 }}>
        <label style={{ display:'inline-block', padding:'10px 20px', background:'#1a1a1a', color:'white', borderRadius:8, cursor:'pointer' }}>
          Importar extrato (.ofx)
          <input type="file" accept=".ofx" onChange={handleUpload} style={{ display:'none' }} />
        </label>
      </div>

      {msg && (
        <div style={{ marginBottom:16, padding:'10px 16px', borderRadius:8,
          background: msg.tipo === 'ok' ? '#22c55e22' : '#ef444422',
          color: msg.tipo === 'ok' ? '#15803d' : '#b91c1c', fontSize:14 }}>
          {msg.texto}
        </div>
      )}

      {resumo && !resumo.lote_id && (
        <p style={{ color:'#666' }}>
          Nada de novo pra revisar — as {resumo.total} transações do arquivo já tinham sido importadas antes.
        </p>
      )}

      {resumo?.lote_id && (
        <>
          <p style={{ color:'#666', fontSize:14 }}>
            {resumo.total} transações no arquivo — {resumo.casadas} casadas automaticamente, {resumo.novas} sem match (débito), {resumo.sem_match} sem match (crédito).
          </p>
          <table style={{ width:'100%', borderCollapse:'collapse', background:'white', borderRadius:12, overflow:'hidden', marginBottom:16 }}>
            <thead>
              <tr style={{ background:'#f0f0f0', textAlign:'left' }}>
                {['Data','Descrição','Valor','Sugestão','Ação'].map(h => (
                  <th key={h} style={{ padding:'10px 16px', fontSize:13 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {transacoes.map(t => (
                <tr key={t.id} style={{ borderTop:'1px solid #eee' }}>
                  <td style={{ padding:'10px 16px' }}>{new Date(t.data + 'T00:00:00').toLocaleDateString('pt-BR')}</td>
                  <td style={{ padding:'10px 16px' }}>{t.descricao}</td>
                  <td style={{ padding:'10px 16px', fontWeight:600 }}>
                    {t.tipo === 'DEBIT' ? '-' : '+'} {Number(t.valor).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
                  </td>
                  <td style={{ padding:'10px 16px', fontSize:13, color:'#666' }}>
                    {t.match_tabela ? `Match: ${t.match_descricao}` : (t.tipo === 'DEBIT' ? 'Sem match — vira conta nova' : 'Não identificado')}
                  </td>
                  <td style={{ padding:'10px 16px' }}>
                    <select value={acoes[t.id]} onChange={e => setAcoes({ ...acoes, [t.id]: e.target.value })} style={{ padding:6 }}>
                      {ACOES.filter(a => a.valor !== 'confirmar_match' || t.match_tabela).map(a => (
                        <option key={a.valor} value={a.valor}>{a.label}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button onClick={confirmar} disabled={enviando}
            style={{ padding:'10px 24px', background:'#22c55e', color:'white', border:'none', borderRadius:8, cursor:'pointer', opacity: enviando ? 0.6 : 1 }}>
            {enviando ? 'Confirmando...' : 'Confirmar'}
          </button>
        </>
      )}
    </Layout>
  )
}
```

- [ ] **Step 4: Verify the build**

```bash
cd ../financeiro-frontend && npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 5: Manual smoke test**

```bash
npm run dev
```

Log in as `fin_admin`, go to "Conciliação Bancária", upload
`../financeiro-backend/tests/fixtures/extrato_exemplo.ofx` (the Task 4 fixture works fine
for this manual check too), confirm the review table renders with a suggestion per row and
the select defaults match expectations, click "Confirmar", and verify the success message
appears.

- [ ] **Step 6: Commit**

```bash
git add src/pages/ConciliacaoBancaria.jsx src/App.jsx src/components/Layout.jsx
git commit -m "$(cat <<'EOF'
feat: página de conciliação bancária — upload de OFX, revisão e confirmação

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```
