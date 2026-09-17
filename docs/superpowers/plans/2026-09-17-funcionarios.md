# Aba Funcionários — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aba "Funcionários" no Painel Financeiro: cada pessoa (MEI) tem, por mês de competência, o pagamento (Pix + comprovante), o DAS (boleto + comprovante) e a NF do mês — subidos por upload com leitura por IA ou lançados à mão — e o que foi pago a funcionário (pagamento e DAS) sai da sobra na Caixa da Semana.

**Architecture:** Backend ganha duas tabelas (`fin_funcionarios`, `fin_funcionario_lancamentos` — uma tabela para os três tipos, `tipo` + `competencia` dia 1), um módulo `anexos.py` com os helpers de upload que hoje estão presos em `routes/fornecedores.py`, dois leitores novos em `leitura_documento.py` (`ler_boleto_das`, `ler_nota_fiscal`) e um blueprint `routes/funcionarios.py` com CRUD, leitura (`/ler/pix|das|nf`, que só leem) e `/pagamentos?de&ate` para a Caixa. Frontend ganha a página `Funcionarios.jsx` montada de blocos pequenos (`BlocoLancamentoFuncionario`, `UploadDocumentoFuncionario`), o que é comum ao upload de pedido sai para `components/upload/comum.jsx`, e a Caixa da Semana ganha a linha "Pago a funcionários".

**Tech Stack:** Flask + psycopg2 (backend; testes com pytest e `db` mockado), `anthropic` (`client.messages.create` com `output_config.format` json_schema), Supabase Storage via REST (`storage.py`), React 18 + axios + react-router (frontend; testes com vitest + testing-library).

**Spec:** `docs/superpowers/specs/2026-09-17-funcionarios-design.md`

## Global Constraints

- A IA **nunca grava**: `/ler/*` só leem; só `POST/PUT /lancamentos` gravam, e só no Salvar dela.
- Tipos aceitos: `application/pdf`, `image/jpeg`, `image/png`; limite 10 MB; token de arquivo válido só se casar `^pendentes/[0-9a-f]{32}\.(pdf|jpg|png)$`.
- Mesmo bucket privado `fornecedores`; caminho dos funcionários `funcionarios/<funcionario_id>/<AAAA-MM>/<tipo>[-boleto|-comprovante]-<id>.<ext>`; a tela só recebe URL assinada de 1 h, no clique.
- `competencia` é `DATE` no dia 1; a API aceita `AAAA-MM` ou `AAAA-MM-DD` e grava dia 1; a API **devolve** `competencia`, `vencimento` e `pago_em` como texto `AAAA-MM-DD` (não RFC-1123).
- Regras por tipo: `pagamento` exige `valor > 0` e `pago_em`; `das` exige `valor > 0` (vencimento e pago_em opcionais), um por competência; `nf` exige `numero_nf` ou arquivo, um por competência. Segundo DAS/NF no mês → 409 com `existente_id`.
- Mesmo Pix (E2E) não entra duas vezes **nem entre tabelas**: checagem em `fin_funcionario_lancamentos` e `fin_pagamentos_fornecedor` → 409.
- Mover anexo dentro da transação do INSERT/UPDATE: falha no Storage → nada gravado, 500 com mensagem.
- Caixa da Semana: `sobra = totalRepasse − totalBoletos − totalPagoFornecedor − totalPagoFuncionarios`; DAS **pago** conta, DAS em aberto não.
- `fin_admin` grava; qualquer `fin_role` lê (`require_auth`); writes com viewer → 403.
- Nenhum documento real (DAS, NF, comprovante) no repositório — fixtures sintéticas.
- Commits em português (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`) terminando com `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Backend: branch `feat/funcionarios` (já existe, com o spec). Frontend: criar `feat/funcionarios` a partir de `main` atualizada (`git fetch origin && git checkout -b feat/funcionarios origin/main`).
- Testes backend: `venv/bin/python -m pytest tests -q` em `/Users/macbookpro/Desktop/Claude/financeiro-backend` (hoje 161 passando; ao final tudo verde). Frontend: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run` e `npm run build` em `/Users/macbookpro/Desktop/Claude/financeiro-frontend`.
- Outra sessão do Claude mexe nos mesmos repos: antes de `merge --ff-only`, `git fetch origin` e conferir que `origin/main` é o merge-base da branch.

---

## Mapa de arquivos

**financeiro-backend**
- Create `supabase/migrations/20260917_funcionarios.sql` — as duas tabelas, índices, RLS.
- Create `anexos.py` — `ler_arquivo_enviado`, `subir_pendente`, `arquivo_token_valido`, `destino_anexo(prefixo, pasta, registro_id, token)`, `url_anexo(...)`, `MSG_LEITURA_INDISPONIVEL`, `MSG_ANEXO_NAO_GUARDADO` (movidos de `routes/fornecedores.py`).
- Modify `routes/fornecedores.py` — passa a importar de `anexos`; comportamento igual.
- Modify `leitura_documento.py` — `ler_boleto_das`, `ler_nota_fiscal`, `_competencia_ou_none`, `_cnpj_ou_none`.
- Create `routes/funcionarios.py` — blueprint `/api/funcionarios`.
- Modify `app.py` — registra o blueprint.
- Create `tests/test_anexos.py`, `tests/test_funcionarios.py`; Modify `tests/test_leitura_documento.py`, `tests/test_fornecedores_upload.py` (só o teste de `_destino_anexo`, que muda de casa).
- Create `tests/fixtures/leitura_das.json`, `tests/fixtures/leitura_nf.json`.

**financeiro-frontend**
- Create `src/lib/meses.js` — `mesAtual`, `mesDe`, `rotuloMes`.
- Create `src/components/upload/comum.jsx` — `TIPOS`, estilos, `formatMoeda`, `formatData`, `Faixa`, `validarArquivo`, `mensagemDe`, `PreviewArquivo`, `BotaoSubirArquivo`, `abrirAnexo`.
- Modify `src/components/UploadPedidoCompra.jsx`, `src/pages/Fornecedores.jsx` — importam do `comum`.
- Create `src/components/UploadDocumentoFuncionario.jsx` — cartão de conferência por tipo.
- Create `src/components/BlocoLancamentoFuncionario.jsx` — um bloco (Pagamento / DAS / NF) com linhas, ✏️/🗑️ e botões.
- Create `src/pages/Funcionarios.jsx` — cartões, cadastro, seletor de competência, três blocos, lista de meses.
- Modify `src/components/Layout.jsx`, `src/App.jsx` — menu e rota.
- Modify `src/pages/CaixaSemana.jsx`, `src/pages/CaixaSemana.test.jsx`, `docs/regras-caixa-semana.md` — linha "Pago a funcionários".
- Create testes: `src/lib/meses.test.js`, `src/components/upload/comum.test.jsx`, `src/components/UploadDocumentoFuncionario.test.jsx`, `src/components/BlocoLancamentoFuncionario.test.jsx`, `src/pages/Funcionarios.test.jsx`.

---

### Task 1: Migração `20260917_funcionarios.sql`

**Files:**
- Create: `supabase/migrations/20260917_funcionarios.sql`

**Interfaces:**
- Produces: tabelas `fin_funcionarios(id, nome, cnpj, valor_combinado, ativo, created_at)` e `fin_funcionario_lancamentos(id, funcionario_id, tipo, competencia, valor, vencimento, pago_em, numero_nf, id_transacao, arquivo_path, boleto_path, comprovante_path, observacao, criado_por, created_at)`; índice único parcial em `id_transacao`; único `(funcionario_id, competencia, tipo)` para `das`/`nf`.

- [ ] **Step 1: Escrever a migração (idempotente, como as de 17/09)**

```sql
-- supabase/migrations/20260917_funcionarios.sql
-- Aba Funcionários: pagamento, DAS e NF por pessoa e por mês de competência.
-- Desenho em docs/superpowers/specs/2026-09-17-funcionarios-design.md.
-- Uma tabela para os três tipos: o mês de uma pessoa é "as linhas com aquela
-- competência", e "o que falta?" é um GROUP BY tipo.

CREATE TABLE IF NOT EXISTS fin_funcionarios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nome TEXT NOT NULL,
  cnpj TEXT,                              -- só dígitos; opcional
  valor_combinado NUMERIC(12,2),          -- pré-preenche o pagamento; opcional
  ativo BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fin_funcionario_lancamentos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  funcionario_id UUID NOT NULL REFERENCES fin_funcionarios(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL CHECK (tipo IN ('pagamento', 'das', 'nf')),
  competencia DATE NOT NULL,              -- sempre dia 1 do mês do serviço
  valor NUMERIC(12,2),                    -- NF pode vir sem valor lido; DAS/pagamento exigem (regra na rota)
  vencimento DATE,                        -- DAS
  pago_em DATE,                           -- pagamento e DAS; NULL = em aberto
  numero_nf TEXT,                         -- NF
  id_transacao TEXT,                      -- E2E do Pix (pagamento e comprovante do DAS)
  arquivo_path TEXT,                      -- Pix do pagamento / arquivo da NF
  boleto_path TEXT,                       -- DAS: o boleto
  comprovante_path TEXT,                  -- DAS: o comprovante
  observacao TEXT,
  criado_por UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_func_lanc_func_comp
  ON fin_funcionario_lancamentos(funcionario_id, competencia);
CREATE INDEX IF NOT EXISTS idx_func_lanc_pago_em
  ON fin_funcionario_lancamentos(pago_em) WHERE pago_em IS NOT NULL;
-- O mesmo Pix não entra duas vezes aqui. Entre esta tabela e a de fornecedores
-- a checagem é na rota (consulta as duas) — índice não atravessa tabela.
CREATE UNIQUE INDEX IF NOT EXISTS idx_func_lanc_id_transacao
  ON fin_funcionario_lancamentos(id_transacao) WHERE id_transacao IS NOT NULL;
-- Um DAS e uma NF por competência; pagamento pode repetir (adiantamento + saldo).
CREATE UNIQUE INDEX IF NOT EXISTS idx_func_lanc_um_por_mes
  ON fin_funcionario_lancamentos(funcionario_id, competencia, tipo) WHERE tipo IN ('das', 'nf');

ALTER TABLE fin_funcionarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_funcionario_lancamentos ENABLE ROW LEVEL SECURITY;

-- Mesmas policies das outras fin_* (005_fin_pagamentos_fornecedor.sql).
DROP POLICY IF EXISTS "fin_select" ON fin_funcionarios;
CREATE POLICY "fin_select" ON fin_funcionarios FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
DROP POLICY IF EXISTS "fin_write" ON fin_funcionarios;
CREATE POLICY "fin_write" ON fin_funcionarios FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));

DROP POLICY IF EXISTS "fin_select" ON fin_funcionario_lancamentos;
CREATE POLICY "fin_select" ON fin_funcionario_lancamentos FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
DROP POLICY IF EXISTS "fin_write" ON fin_funcionario_lancamentos;
CREATE POLICY "fin_write" ON fin_funcionario_lancamentos FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
```

- [ ] **Step 2: Conferir contra o spec**

Ler o arquivo de novo e conferir, coluna a coluna, com a seção "Migração" do spec: 15 colunas em `fin_funcionario_lancamentos`, `CHECK (tipo IN (...))`, quatro índices, quatro policies. Não há Postgres local: a validação real é na Task 7 (aplicar no Supabase).

- [ ] **Step 3: Commit**

```bash
git add supabase/migrations/20260917_funcionarios.sql
git commit -m "feat: tabelas de funcionários e lançamentos por competência

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `anexos.py` — helpers de upload saem de `routes/fornecedores.py`

**Files:**
- Create: `anexos.py`
- Modify: `routes/fornecedores.py` (linhas 150–203 e 821–833: remover os helpers e importar de `anexos`)
- Create: `tests/test_anexos.py`
- Modify: `tests/test_fornecedores_upload.py` (o teste `test_destino_anexo_rejeita_token_fora_de_pendentes`, linhas 310–316, muda para `tests/test_anexos.py`)

**Interfaces:**
- Produces (módulo `anexos`):
  - `MSG_LEITURA_INDISPONIVEL: str`, `MSG_ANEXO_NAO_GUARDADO: str`
  - `ler_arquivo_enviado() -> (dados: bytes, mime: str, None) | (None, None, (resposta, status))` — lê o multipart `arquivo` da request atual.
  - `subir_pendente(dados, mime) -> str` — token `pendentes/<hex>.<ext>`; levanta `storage.StorageErro`.
  - `arquivo_token_valido(token) -> bool`
  - `destino_anexo(prefixo, pasta, registro_id, token) -> str` — `f"{prefixo}/{pasta}/{registro_id}.{ext}"`; `ValueError` se o token for inválido.
  - `url_anexo(tabela, coluna_dono, dono_id, registro_id, coluna_arquivo="arquivo_path") -> (resposta, status)` — resposta Flask com `{"url": ...}`, 404 sem anexo, 500 se o Storage falhar. `tabela`/colunas são constantes do código, nunca entrada do usuário.
- Consumes: `storage.enviar_pendente`, `storage.limpar_pendentes`, `storage.url_assinada`, `storage.EXTENSOES`, `db.query`.

- [ ] **Step 1: Escrever os testes novos**

```python
# tests/test_anexos.py
import io

import pytest

import anexos

FORN = "11111111-1111-1111-1111-111111111111"
TOKEN = "pendentes/" + "a" * 32 + ".png"


def test_destino_anexo_rejeita_token_fora_de_pendentes():
    with pytest.raises(ValueError):
        anexos.destino_anexo(FORN, "pedidos", "p-9", "pendentes/../outro.pdf")
    with pytest.raises(ValueError):
        anexos.destino_anexo(FORN, "pedidos", "p-9", "pendentes/abc.pdf")  # hex curto demais
    assert anexos.destino_anexo(FORN, "pedidos", "p-9", TOKEN) == f"{FORN}/pedidos/p-9.png"


def test_destino_anexo_aceita_prefixo_composto_para_funcionarios():
    # funcionarios/<id>/<AAAA-MM>/<tipo>-<id>.<ext> — o prefixo é quem separa no mesmo bucket
    assert anexos.destino_anexo("funcionarios/f-1", "2026-09", "das-boleto-l-1", "pendentes/" + "0" * 32 + ".pdf") \
        == "funcionarios/f-1/2026-09/das-boleto-l-1.pdf"


def test_arquivo_token_valido():
    assert anexos.arquivo_token_valido(TOKEN)
    assert not anexos.arquivo_token_valido(None)
    assert not anexos.arquivo_token_valido("")
    assert not anexos.arquivo_token_valido("outro/" + "a" * 32 + ".png")
    assert not anexos.arquivo_token_valido("pendentes/" + "a" * 32 + ".gif")


def test_subir_pendente_ignora_falha_na_limpeza(mocker):
    mocker.patch("anexos.storage.limpar_pendentes", side_effect=RuntimeError("lista fora"))
    enviar = mocker.patch("anexos.storage.enviar_pendente", return_value="pendentes/x.pdf")
    assert anexos.subir_pendente(b"%PDF", "application/pdf") == "pendentes/x.pdf"
    enviar.assert_called_once_with(b"%PDF", "application/pdf")


def test_ler_arquivo_enviado_valida_tipo_e_tamanho(app):
    with app.test_request_context("/x", method="POST", data={"arquivo": (io.BytesIO(b"gif"), "a.gif", "image/gif")},
                                  content_type="multipart/form-data"):
        dados, mime, erro = anexos.ler_arquivo_enviado()
        assert dados is None and erro[1] == 400
        assert "PDF, JPG ou PNG" in erro[0].get_json()["error"]
    with app.test_request_context("/x", method="POST", data={}, content_type="multipart/form-data"):
        _, _, erro = anexos.ler_arquivo_enviado()
        assert erro[1] == 400 and "obrigatório" in erro[0].get_json()["error"]
    with app.test_request_context("/x", method="POST", data={"arquivo": (io.BytesIO(b"%PDF ok"), "a.pdf", "application/pdf")},
                                  content_type="multipart/form-data"):
        dados, mime, erro = anexos.ler_arquivo_enviado()
        assert erro is None and dados == b"%PDF ok" and mime == "application/pdf"


def test_url_anexo_filtra_pelo_dono_e_pela_coluna(mocker):
    query = mocker.patch("anexos.db.query", return_value=[{"boleto_path": "funcionarios/f-1/2026-09/das-boleto-l-1.pdf"}])
    mocker.patch("anexos.storage.url_assinada", return_value="https://x/assinada")
    resposta = anexos.url_anexo("fin_funcionario_lancamentos", "funcionario_id", "f-1", "l-1", "boleto_path")
    assert resposta.get_json() == {"url": "https://x/assinada"}
    sql, params = query.call_args.args
    assert "SELECT boleto_path FROM fin_funcionario_lancamentos" in sql
    assert "funcionario_id = %s" in sql
    assert params == ("l-1", "f-1")


def test_url_anexo_sem_arquivo_404(mocker):
    mocker.patch("anexos.db.query", return_value=[{"arquivo_path": None}])
    resposta, status = anexos.url_anexo("fin_pedidos_fornecedor", "fornecedor_id", FORN, "p-1")
    assert status == 404
```

`url_anexo` devolve ou `jsonify(...)` (200, uma `Response`) ou uma tupla `(resposta, status)` — o teste de 200 usa `.get_json()` direto e o de 404 desempacota, igual ao uso nas rotas.

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_anexos.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'anexos'`.

- [ ] **Step 3: Criar `anexos.py`**

```python
"""Helpers de anexo compartilhados pelas rotas de fornecedores e funcionários.

Viviam dentro de routes/fornecedores.py; saíram de lá em 17/09/2026 quando a
aba Funcionários passou a subir documento pelo mesmo caminho (pendentes/ no
bucket → leitura → salvar move). Nada aqui grava no banco: quem grava é a rota.
"""
import re
import sys

from flask import request, jsonify

import db
import storage

_TAMANHO_MAX = 10 * 1024 * 1024
MSG_LEITURA_INDISPONIVEL = "Leitura automática indisponível agora. Lance à mão."
MSG_ANEXO_NAO_GUARDADO = "Não consegui guardar o arquivo; dá para lançar assim mesmo, só sem o anexo."

# Tokens legítimos sempre vêm de storage.enviar_pendente (uuid4().hex + ext
# aceita). Qualquer outra forma é entrada forjada — sem isso, um token como
# "outro-fornecedor/pedidos/x.pdf" moveria o anexo de outro registro.
_RE_ARQUIVO_TOKEN = re.compile(r"^pendentes/[0-9a-f]{32}\.(pdf|jpg|png)$")


def ler_arquivo_enviado():
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


def subir_pendente(dados, mime):
    """Limpa pendentes velhos e sobe o arquivo. Falha de limpeza não impede a leitura."""
    try:
        storage.limpar_pendentes()
    except Exception as e:
        print(f"[storage] limpeza de pendentes falhou: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    return storage.enviar_pendente(dados, mime)


def arquivo_token_valido(token):
    return bool(token) and _RE_ARQUIVO_TOKEN.match(token) is not None


def destino_anexo(prefixo, pasta, registro_id, token):
    """Caminho definitivo do anexo: <prefixo>/<pasta>/<registro_id>.<ext>.

    Fornecedores: prefixo = id do fornecedor, pasta 'pedidos'/'pagamentos'.
    Funcionários: prefixo = 'funcionarios/<id>', pasta = competência 'AAAA-MM',
    registro_id = '<tipo>[-boleto|-comprovante]-<id>'.
    """
    if not arquivo_token_valido(token):
        raise ValueError("arquivo_token inválido")
    ext = token.rsplit(".", 1)[-1]
    return f"{prefixo}/{pasta}/{registro_id}.{ext}"


def url_anexo(tabela, coluna_dono, dono_id, registro_id, coluna_arquivo="arquivo_path"):
    """URL assinada (1 h) do anexo de um registro, conferindo o dono.

    `tabela`, `coluna_dono` e `coluna_arquivo` são constantes escritas no código
    das rotas — nunca vêm da request.
    """
    rows = db.query(
        f"SELECT {coluna_arquivo} FROM {tabela} WHERE id = %s AND {coluna_dono} = %s",
        (registro_id, dono_id)
    )
    if not rows or not rows[0][coluna_arquivo]:
        return jsonify({"error": "Sem anexo"}), 404
    try:
        return jsonify({"url": storage.url_assinada(rows[0][coluna_arquivo])})
    except storage.StorageErro as e:
        print(f"[storage] falhou ao assinar URL do anexo: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": "Não consegui abrir o anexo agora. Tente de novo."}), 500
```

- [ ] **Step 4: Trocar `routes/fornecedores.py` para usar o módulo**

Em `routes/fornecedores.py`:
1. Nos imports, acrescentar `import anexos` e `from anexos import MSG_LEITURA_INDISPONIVEL, MSG_ANEXO_NAO_GUARDADO` (as duas constantes continuam usadas pelo nome nas rotas `/ler`).
2. Apagar o bloco das linhas 150–203 (de `_TAMANHO_MAX = ...` até o fim de `_destino_anexo`), **mantendo** `_aprender_alias_silencioso` (linhas ~181–189), que não é de anexo.
3. Substituir as chamadas: `_ler_arquivo_enviado()` → `anexos.ler_arquivo_enviado()`; `_subir_pendente(dados, mime)` → `anexos.subir_pendente(dados, mime)`; `_arquivo_token_valido(x)` → `anexos.arquivo_token_valido(x)`; `_destino_anexo(fornecedor_id, "pedidos", pedido["id"], arquivo_token)` → `anexos.destino_anexo(fornecedor_id, "pedidos", pedido["id"], arquivo_token)`; idem `"pagamentos"`.
4. Apagar `_url_anexo` (linhas ~821–833) e trocar as duas rotas de anexo:

```python
@bp.get("/<fornecedor_id>/pedidos/<pedido_id>/anexo")
@require_auth
def anexo_pedido(fornecedor_id, pedido_id):
    return anexos.url_anexo("fin_pedidos_fornecedor", "fornecedor_id", fornecedor_id, pedido_id)


@bp.get("/<fornecedor_id>/pagamentos/<pagamento_id>/anexo")
@require_auth
def anexo_pagamento(fornecedor_id, pagamento_id):
    return anexos.url_anexo("fin_pagamentos_fornecedor", "fornecedor_id", fornecedor_id, pagamento_id)
```

5. Se `re` ficar sem uso no arquivo, conferir antes de remover: `pagamentos_do_periodo` usa `re.fullmatch` — **fica**.

Os mocks dos testes existentes (`mocker.patch("routes.fornecedores.storage.enviar_pendente")`, `...db.query`) continuam valendo: `routes.fornecedores.storage` **é** o módulo `storage`, e o patch troca o atributo no módulo, que `anexos` também enxerga.

- [ ] **Step 5: Mover o teste de `_destino_anexo`**

Em `tests/test_fornecedores_upload.py`, apagar `test_destino_anexo_rejeita_token_fora_de_pendentes` (linhas 310–316) — ele já está em `tests/test_anexos.py` com o nome novo.

- [ ] **Step 6: Rodar tudo**

Run: `venv/bin/python -m pytest tests -q`
Expected: tudo verde (161 − 1 movido + 7 novos = 167 passando).

- [ ] **Step 7: Commit**

```bash
git add anexos.py routes/fornecedores.py tests/test_anexos.py tests/test_fornecedores_upload.py
git commit -m "refactor: helpers de anexo saem de routes/fornecedores.py para anexos.py

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Leitores `ler_boleto_das` e `ler_nota_fiscal`

**Files:**
- Modify: `leitura_documento.py` (acrescentar esquemas, instruções, helpers e as duas funções ao fim)
- Create: `tests/fixtures/leitura_das.json`, `tests/fixtures/leitura_nf.json`
- Modify: `tests/test_leitura_documento.py` (acrescentar testes)

**Interfaces:**
- Produces:
  - `ler_boleto_das(dados, mime) -> {"valor": float, "vencimento": "AAAA-MM-DD"|None, "competencia": "AAAA-MM-01"|None, "cnpj": str(14 dígitos)|None, "nome": str|None}`; `LeituraFalhou` se o valor não for legível.
  - `ler_nota_fiscal(dados, mime) -> {"numero": str|None, "valor": float|None, "data_emissao": "AAAA-MM-DD"|None, "competencia": "AAAA-MM-01"|None, "competencia_inferida": bool, "cnpj_prestador": str|None, "nome_prestador": str|None}`; `LeituraFalhou` se não houver número nem valor.
  - `_competencia_ou_none(texto)`: `"2026-09"`, `"2026-09-15"`, `"09/2026"` → `"2026-09-01"`; resto → `None`.
  - `_cnpj_ou_none(texto)`: só dígitos, exige 14.
- Consumes: `_chamar`, `_data_ou_none`, `LeituraFalhou` (já existem).

- [ ] **Step 1: Fixtures sintéticas**

```json
// tests/fixtures/leitura_das.json  (o que a IA devolve de um DAS-MEI; inventado)
{
  "valor": 75.9,
  "vencimento": "2026-10-20",
  "competencia": "09/2026",
  "cnpj": "12.345.678/0001-95",
  "nome": "JOSIE DA SILVA 12345678000195"
}
```

```json
// tests/fixtures/leitura_nf.json  (NFS-e de MEI sem mês de serviço na discriminação; inventado)
{
  "numero": "000000123",
  "valor": 2500.0,
  "data_emissao": "2026-09-05",
  "competencia": null,
  "cnpj_prestador": "12345678000195",
  "nome_prestador": "JOSIE DA SILVA"
}
```

(Sem os comentários `//` nos arquivos — JSON puro.)

- [ ] **Step 2: Testes**

Acrescentar ao fim de `tests/test_leitura_documento.py`:

```python
# --- ler_boleto_das ---------------------------------------------------------

def test_ler_boleto_das_normaliza_competencia_e_cnpj(mocker):
    mocker.patch("leitura_documento._chamar", return_value=_fixture("leitura_das.json"))
    lido = ld.ler_boleto_das(b"%PDF", "application/pdf")
    assert lido == {
        "valor": 75.9,
        "vencimento": "2026-10-20",
        "competencia": "2026-09-01",
        "cnpj": "12345678000195",
        "nome": "JOSIE DA SILVA 12345678000195",
    }


def test_ler_boleto_das_valor_zero_levanta_leitura_falhou(mocker):
    dados = _fixture("leitura_das.json")
    dados["valor"] = 0
    mocker.patch("leitura_documento._chamar", return_value=dados)
    with pytest.raises(ld.LeituraFalhou):
        ld.ler_boleto_das(b"x", "image/png")


def test_ler_boleto_das_competencia_ilegivel_vira_none(mocker):
    dados = _fixture("leitura_das.json")
    dados["competencia"] = "setembro"
    dados["cnpj"] = "123"
    mocker.patch("leitura_documento._chamar", return_value=dados)
    lido = ld.ler_boleto_das(b"x", "image/png")
    assert lido["competencia"] is None
    assert lido["cnpj"] is None


def test_competencia_ou_none_aceita_os_tres_formatos():
    assert ld._competencia_ou_none("2026-09") == "2026-09-01"
    assert ld._competencia_ou_none("2026-09-15") == "2026-09-01"
    assert ld._competencia_ou_none("09/2026") == "2026-09-01"
    assert ld._competencia_ou_none("13/2026") is None
    assert ld._competencia_ou_none(None) is None


# --- ler_nota_fiscal --------------------------------------------------------

def test_ler_nota_fiscal_sem_competencia_usa_mes_da_emissao_e_marca(mocker):
    mocker.patch("leitura_documento._chamar", return_value=_fixture("leitura_nf.json"))
    lido = ld.ler_nota_fiscal(b"%PDF", "application/pdf")
    assert lido["numero"] == "000000123"
    assert lido["valor"] == 2500.0
    assert lido["data_emissao"] == "2026-09-05"
    assert lido["competencia"] == "2026-09-01"
    assert lido["competencia_inferida"] is True
    assert lido["cnpj_prestador"] == "12345678000195"


def test_ler_nota_fiscal_com_competencia_na_nota_nao_infere(mocker):
    dados = _fixture("leitura_nf.json")
    dados["competencia"] = "08/2026"   # a NF de agosto do Fabrício, emitida em setembro
    mocker.patch("leitura_documento._chamar", return_value=dados)
    lido = ld.ler_nota_fiscal(b"%PDF", "application/pdf")
    assert lido["competencia"] == "2026-08-01"
    assert lido["competencia_inferida"] is False


def test_ler_nota_fiscal_sem_numero_nem_valor_levanta_leitura_falhou(mocker):
    dados = _fixture("leitura_nf.json")
    dados["numero"] = None
    dados["valor"] = None
    mocker.patch("leitura_documento._chamar", return_value=dados)
    with pytest.raises(ld.LeituraFalhou):
        ld.ler_nota_fiscal(b"%PDF", "application/pdf")
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_leitura_documento.py -q`
Expected: 7 falhas com `AttributeError: module 'leitura_documento' has no attribute 'ler_boleto_das'` (e `_competencia_ou_none`, `ler_nota_fiscal`).

- [ ] **Step 4: Implementar em `leitura_documento.py`**

Acrescentar depois de `ESQUEMA_COMPROVANTE`/`INSTRUCAO_COMPROVANTE`:

```python
ESQUEMA_DAS = {
    "type": "object",
    "properties": {
        "valor": {"type": ["number", "null"], "description": "Valor total do documento, em reais"},
        "vencimento": {"type": ["string", "null"], "description": "Data de vencimento, AAAA-MM-DD"},
        "competencia": {"type": ["string", "null"],
                        "description": "Período de apuração, AAAA-MM (o mês a que o imposto se refere)"},
        "cnpj": {"type": ["string", "null"], "description": "CNPJ do contribuinte, só dígitos"},
        "nome": {"type": ["string", "null"], "description": "Nome ou razão social do contribuinte"},
    },
    "required": ["valor", "vencimento", "competencia", "cnpj", "nome"],
    "additionalProperties": False,
}

ESQUEMA_NF = {
    "type": "object",
    "properties": {
        "numero": {"type": ["string", "null"], "description": "Número da nota, como impresso"},
        "valor": {"type": ["number", "null"], "description": "Valor total dos serviços, em reais"},
        "data_emissao": {"type": ["string", "null"], "description": "AAAA-MM-DD"},
        "competencia": {"type": ["string", "null"],
                        "description": "Mês dos serviços prestados (AAAA-MM), só se a nota disser; senão null"},
        "cnpj_prestador": {"type": ["string", "null"], "description": "CNPJ de quem emitiu, só dígitos"},
        "nome_prestador": {"type": ["string", "null"], "description": "Nome de quem emitiu, como impresso"},
    },
    "required": ["numero", "valor", "data_emissao", "competencia", "cnpj_prestador", "nome_prestador"],
    "additionalProperties": False,
}

INSTRUCAO_DAS = (
    "Este é um DAS (Documento de Arrecadação do Simples Nacional) de um MEI. "
    "Transcreva: o valor total do documento em reais, a data de vencimento (AAAA-MM-DD), "
    "o período de apuração (AAAA-MM — o mês a que o imposto se refere, que não é o mês "
    "do vencimento), o CNPJ do contribuinte só com dígitos e o nome ou razão social. "
    "Números no padrão brasileiro (75,90 = setenta e cinco reais e noventa centavos)."
)

INSTRUCAO_NF = (
    "Esta é uma nota fiscal de serviço (NFS-e) emitida por um prestador MEI. Transcreva: "
    "o número da nota, o valor total dos serviços em reais, a data de emissão (AAAA-MM-DD), "
    "o CNPJ e o nome do PRESTADOR (quem emitiu, não o tomador), e o mês de competência dos "
    "serviços (AAAA-MM) somente se a discriminação ou algum campo da nota disser em que mês "
    "os serviços foram prestados — se não disser, deixe competencia nula. "
    "Números no padrão brasileiro."
)
```

Depois de `_RE_DATA`:

```python
_RE_COMPETENCIA = re.compile(r"^(\d{4})-(\d{2})(?:-\d{2})?$")
_RE_COMPETENCIA_BR = re.compile(r"^(\d{2})/(\d{4})$")
```

Depois de `_data_ou_none`:

```python
def _competencia_ou_none(texto):
    """'2026-09', '2026-09-15' ou '09/2026' → '2026-09-01'. O resto → None."""
    if not isinstance(texto, str):
        return None
    t = texto.strip()
    m = _RE_COMPETENCIA.match(t)
    if m:
        ano, mes = int(m.group(1)), int(m.group(2))
    else:
        m = _RE_COMPETENCIA_BR.match(t)
        if not m:
            return None
        mes, ano = int(m.group(1)), int(m.group(2))
    try:
        return date(ano, mes, 1).isoformat()
    except ValueError:
        return None


def _cnpj_ou_none(texto):
    digitos = re.sub(r"\D", "", texto or "")
    return digitos if len(digitos) == 14 else None


def _valor_positivo_ou_none(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None
```

Ao fim do arquivo:

```python
def ler_boleto_das(dados, mime):
    bruto = _chamar(dados, mime, INSTRUCAO_DAS, ESQUEMA_DAS)
    valor = _valor_positivo_ou_none(bruto.get("valor"))
    if valor is None:
        raise LeituraFalhou("valor do DAS não legível")
    return {
        "valor": valor,
        "vencimento": _data_ou_none(bruto.get("vencimento")),
        "competencia": _competencia_ou_none(bruto.get("competencia")),
        "cnpj": _cnpj_ou_none(bruto.get("cnpj")),
        "nome": (bruto.get("nome") or "").strip() or None,
    }


def ler_nota_fiscal(dados, mime):
    bruto = _chamar(dados, mime, INSTRUCAO_NF, ESQUEMA_NF)
    numero = (bruto.get("numero") or "").strip() or None
    valor = _valor_positivo_ou_none(bruto.get("valor"))
    if numero is None and valor is None:
        raise LeituraFalhou("nota sem número nem valor legíveis")
    data_emissao = _data_ou_none(bruto.get("data_emissao"))
    competencia = _competencia_ou_none(bruto.get("competencia"))
    # A nota não diz o mês do serviço: assume o da emissão, e a tela avisa
    # (é assim que a NF de agosto emitida em setembro pode ir para agosto).
    inferida = competencia is None
    if inferida and data_emissao:
        competencia = data_emissao[:7] + "-01"
    return {
        "numero": numero,
        "valor": valor,
        "data_emissao": data_emissao,
        "competencia": competencia,
        "competencia_inferida": inferida,
        "cnpj_prestador": _cnpj_ou_none(bruto.get("cnpj_prestador")),
        "nome_prestador": (bruto.get("nome_prestador") or "").strip() or None,
    }
```

Atualizar o docstring do módulo (primeira linha) para "Leitura de pedido de compra, comprovante Pix, boleto DAS e nota fiscal por IA (visão)."

- [ ] **Step 5: Rodar**

Run: `venv/bin/python -m pytest tests/test_leitura_documento.py -q`
Expected: tudo verde.

- [ ] **Step 6: Commit**

```bash
git add leitura_documento.py tests/test_leitura_documento.py tests/fixtures/leitura_das.json tests/fixtures/leitura_nf.json
git commit -m "feat: leitura por IA de boleto DAS e de nota fiscal de serviço

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: `routes/funcionarios.py` — cadastro, resumo do mês e `/pagamentos` para a Caixa

**Files:**
- Create: `routes/funcionarios.py`
- Modify: `app.py` (import + `register_blueprint(funcionarios_bp, url_prefix="/api/funcionarios")`)
- Create: `tests/test_funcionarios.py`

**Interfaces:**
- Produces (rotas): `GET /api/funcionarios` → lista de ativos, cada um com `mes_atual: {competencia, falta, das_em_aberto, das_vencimento, completo, total_pago, das_valor, nf_valor, nf_numero}`; `POST /api/funcionarios` (201); `PUT /api/funcionarios/<id>`; `DELETE /api/funcionarios/<id>` (204, `ativo=false`); `GET /api/funcionarios/pagamentos?de&ate` → `[{id, tipo, valor, data_pagamento, competencia, created_at, funcionario_nome}]`.
- Produces (helpers do módulo, usados nas Tasks 5 e 6): `_hoje() -> date`, `_competencia(texto) -> date|None`, `_iso(v)`, `_linha(row) -> dict` (datas em ISO), `_resumo(linhas) -> dict`, `_funcionario(fid) -> dict|None`, `_erro(msg, status)`.
- Consumes: `db.query`, `db.execute`, `auth.require_auth/require_admin`.

- [ ] **Step 1: Testes (cadastro, resumo, pagamentos do período, viewer)**

```python
# tests/test_funcionarios.py
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

FUNC = "33333333-3333-3333-3333-333333333333"
JOSIE = {"id": FUNC, "nome": "Josie", "cnpj": "12345678000195", "valor_combinado": 2500.0, "ativo": True}


def _db(mocker, respostas):
    """db.query devolve, a cada chamada, o valor da primeira chave de `respostas`
    contida no SQL. Valor pode ser lista ou função(params) → lista."""
    def _query(sql, params=()):
        for trecho, valor in respostas.items():
            if trecho in sql:
                return valor(params) if callable(valor) else valor
        raise AssertionError(f"consulta inesperada: {sql[:120]}")
    return mocker.patch("routes.funcionarios.db.query", side_effect=_query)


def _transacao_fake(mocker, retornos):
    """db.transaction() cujo cursor devolve `retornos` em sequência no fetchone()."""
    cur = MagicMock()
    cur.fetchone.side_effect = retornos

    @contextmanager
    def _tx():
        yield cur

    mocker.patch("routes.funcionarios.db.transaction", _tx)
    return cur


# --- cadastro ---------------------------------------------------------------

def test_listar_traz_resumo_do_mes_atual(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios f": [
        {**JOSIE, "lancamentos_mes": [
            {"tipo": "pagamento", "valor": 2500.0, "pago_em": "2026-09-05", "vencimento": None, "numero_nf": None},
            {"tipo": "das", "valor": 75.9, "pago_em": None, "vencimento": "2026-10-20", "numero_nf": None},
        ]},
        {"id": "f-2", "nome": "Renata", "cnpj": None, "valor_combinado": None, "ativo": True, "lancamentos_mes": []},
    ]})
    r = client.get("/api/funcionarios", headers=admin_headers)
    assert r.status_code == 200
    josie, renata = r.get_json()
    assert josie["mes_atual"]["falta"] == ["nf"]
    assert josie["mes_atual"]["das_em_aberto"] is True
    assert josie["mes_atual"]["das_vencimento"] == "2026-10-20"
    assert josie["mes_atual"]["completo"] is False
    assert josie["mes_atual"]["total_pago"] == 2500.0
    assert renata["mes_atual"]["falta"] == ["pagamento", "das", "nf"]
    assert "lancamentos_mes" not in josie


def test_criar_exige_nome_e_normaliza_cnpj(client, admin_headers, mocker):
    execute = mocker.patch("routes.funcionarios.db.execute", return_value={**JOSIE})
    r = client.post("/api/funcionarios", json={"nome": " Josie ", "cnpj": "12.345.678/0001-95", "valor_combinado": "2500"},
                    headers=admin_headers)
    assert r.status_code == 201
    params = execute.call_args.args[1]
    assert params[:3] == ("Josie", "12345678000195", 2500.0)

    r = client.post("/api/funcionarios", json={"nome": "  "}, headers=admin_headers)
    assert r.status_code == 400
    r = client.post("/api/funcionarios", json={"nome": "X", "cnpj": "123"}, headers=admin_headers)
    assert r.status_code == 400 and "CNPJ" in r.get_json()["error"]
    r = client.post("/api/funcionarios", json={"nome": "X", "valor_combinado": -1}, headers=admin_headers)
    assert r.status_code == 400


def test_editar_e_desativar(client, admin_headers, mocker):
    execute = mocker.patch("routes.funcionarios.db.execute", return_value={**JOSIE, "nome": "Josie R."})
    r = client.put(f"/api/funcionarios/{FUNC}", json={"nome": "Josie R.", "cnpj": "", "valor_combinado": None},
                   headers=admin_headers)
    assert r.status_code == 200 and r.get_json()["nome"] == "Josie R."
    assert execute.call_args.args[1] == ("Josie R.", None, None, FUNC)

    execute.return_value = {"id": FUNC}
    r = client.delete(f"/api/funcionarios/{FUNC}", headers=admin_headers)
    assert r.status_code == 204
    assert "ativo = false" in execute.call_args.args[0]

    execute.return_value = None
    assert client.delete(f"/api/funcionarios/{FUNC}", headers=admin_headers).status_code == 404
    assert client.put(f"/api/funcionarios/{FUNC}", json={"nome": "X"}, headers=admin_headers).status_code == 404


def test_viewer_le_mas_nao_grava(client, viewer_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios f": []})
    assert client.get("/api/funcionarios", headers=viewer_headers).status_code == 200
    assert client.post("/api/funcionarios", json={"nome": "X"}, headers=viewer_headers).status_code == 403
    assert client.put(f"/api/funcionarios/{FUNC}", json={"nome": "X"}, headers=viewer_headers).status_code == 403
    assert client.delete(f"/api/funcionarios/{FUNC}", headers=viewer_headers).status_code == 403


# --- /pagamentos para a Caixa da Semana ---------------------------------------

def test_pagamentos_do_periodo_filtra_por_pago_em_e_so_pagamento_e_das(client, admin_headers, mocker):
    query = _db(mocker, {"JOIN fin_funcionarios f": [
        {"id": "l-1", "tipo": "pagamento", "valor": 2500.0, "data_pagamento": "2026-09-15",
         "competencia": "2026-09-01", "created_at": "x", "funcionario_nome": "Josie"},
    ]})
    r = client.get("/api/funcionarios/pagamentos?de=2026-09-14&ate=2026-09-20", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()[0]["funcionario_nome"] == "Josie"
    sql, params = query.call_args.args
    assert "tipo IN ('pagamento', 'das')" in sql
    assert "pago_em IS NOT NULL" in sql
    assert "pago_em BETWEEN %s AND %s" in sql
    assert params == ("2026-09-14", "2026-09-20")


def test_pagamentos_do_periodo_exige_datas(client, admin_headers):
    assert client.get("/api/funcionarios/pagamentos?de=x&ate=2026-09-20", headers=admin_headers).status_code == 400
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_funcionarios.py -q`
Expected: 404 em todas (blueprint não existe).

- [ ] **Step 3: Criar `routes/funcionarios.py` (parte 1)**

```python
"""Funcionários (prestadores MEI): pagamento, DAS e NF por mês de competência.

Uma tabela para os três tipos (fin_funcionario_lancamentos, coluna `tipo`).
O mês de uma pessoa é o das linhas com aquela competência; "o que falta?" é
olhar quais tipos não têm linha. Os endpoints /ler só leem — nada grava sem o
Salvar dela. Desenho: docs/superpowers/specs/2026-09-17-funcionarios-design.md.
"""
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, request, jsonify, g

import anexos
import db
import leitura_documento
import storage
from auth import require_auth, require_admin

bp = Blueprint("funcionarios", __name__)

FUSO = ZoneInfo("America/Sao_Paulo")
TIPOS = ("pagamento", "das", "nf")
ROTULO_TIPO = {"pagamento": "pagamento", "das": "DAS", "nf": "NF"}
_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# (campo no JSON, coluna no banco, sufixo no nome do arquivo)
ANEXOS = (
    ("arquivo_token", "arquivo_path", ""),
    ("boleto_token", "boleto_path", "-boleto"),
    ("comprovante_token", "comprovante_path", "-comprovante"),
)
COLUNAS_ANEXO = {"arquivo": "arquivo_path", "boleto": "boleto_path", "comprovante": "comprovante_path"}


def _hoje():
    return datetime.now(FUSO).date()


def _erro(msg, status=400):
    return jsonify({"error": msg}), status


def _competencia(texto):
    """'2026-09' ou '2026-09-15' → date(2026, 9, 1); qualquer outra coisa → None."""
    if not isinstance(texto, str):
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", texto.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


def _linha(row):
    """Datas viram texto 'AAAA-MM-DD': a tela compara e mostra sem parsear RFC-1123."""
    if row is None:
        return None
    r = dict(row)
    for k in ("competencia", "vencimento", "pago_em"):
        if k in r:
            r[k] = _iso(r[k])
    if r.get("valor") is not None:
        r["valor"] = float(r["valor"])
    return r


def _resumo(linhas):
    """O que o mês tem e o que falta. Completo = ≥1 pagamento, DAS pago, NF lançada."""
    pagamentos = [l for l in linhas if l["tipo"] == "pagamento"]
    das = next((l for l in linhas if l["tipo"] == "das"), None)
    nf = next((l for l in linhas if l["tipo"] == "nf"), None)
    falta = [t for t, tem in (("pagamento", bool(pagamentos)), ("das", das is not None), ("nf", nf is not None)) if not tem]
    das_em_aberto = das is not None and not das.get("pago_em")
    return {
        "falta": falta,
        "das_em_aberto": das_em_aberto,
        "das_vencimento": _iso(das.get("vencimento")) if das else None,
        "completo": not falta and not das_em_aberto,
        "total_pago": sum(float(p["valor"] or 0) for p in pagamentos),
        "das_valor": float(das["valor"]) if das and das.get("valor") is not None else None,
        "nf_valor": float(nf["valor"]) if nf and nf.get("valor") is not None else None,
        "nf_numero": nf.get("numero_nf") if nf else None,
    }


def _funcionario(fid):
    rows = db.query("SELECT * FROM fin_funcionarios WHERE id = %s AND ativo = true", (fid,))
    return rows[0] if rows else None


def _campos_cadastro(data):
    """Devolve (nome, cnpj, valor_combinado, erro)."""
    nome = (data.get("nome") or "").strip()
    if not nome:
        return None, None, None, "nome obrigatório"
    cnpj = re.sub(r"\D", "", data.get("cnpj") or "") or None
    if cnpj and len(cnpj) != 14:
        return None, None, None, "CNPJ precisa ter 14 dígitos"
    valor = data.get("valor_combinado")
    if valor in (None, ""):
        valor = None
    else:
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return None, None, None, "valor_combinado inválido"
        if valor < 0:
            return None, None, None, "valor_combinado não pode ser negativo"
    return nome, cnpj, valor, None


# --- cadastro ---------------------------------------------------------------

@bp.get("")
@require_auth
def listar():
    mes = _hoje().replace(day=1)
    rows = db.query(
        """SELECT f.*,
                  COALESCE((SELECT json_agg(json_build_object(
                              'tipo', l.tipo, 'valor', l.valor, 'pago_em', l.pago_em,
                              'vencimento', l.vencimento, 'numero_nf', l.numero_nf))
                            FROM fin_funcionario_lancamentos l
                            WHERE l.funcionario_id = f.id AND l.competencia = %s), '[]'::json) AS lancamentos_mes
           FROM fin_funcionarios f
           WHERE f.ativo = true
           ORDER BY f.nome""",
        (mes.isoformat(),)
    )
    saida = []
    for r in rows:
        r = dict(r)
        linhas = r.pop("lancamentos_mes") or []
        r["mes_atual"] = {"competencia": mes.isoformat(), **_resumo(linhas)}
        saida.append(r)
    return jsonify(saida)


@bp.post("")
@require_auth
@require_admin
def criar():
    nome, cnpj, valor, erro = _campos_cadastro(request.get_json() or {})
    if erro:
        return _erro(erro)
    row = db.execute(
        "INSERT INTO fin_funcionarios (nome, cnpj, valor_combinado) VALUES (%s, %s, %s) RETURNING *",
        (nome, cnpj, valor)
    )
    return jsonify(row), 201


@bp.put("/<fid>")
@require_auth
@require_admin
def editar(fid):
    nome, cnpj, valor, erro = _campos_cadastro(request.get_json() or {})
    if erro:
        return _erro(erro)
    row = db.execute(
        """UPDATE fin_funcionarios SET nome = %s, cnpj = %s, valor_combinado = %s
           WHERE id = %s AND ativo = true RETURNING *""",
        (nome, cnpj, valor, fid)
    )
    if row is None:
        return _erro("Funcionário não encontrado", 404)
    return jsonify(row)


@bp.delete("/<fid>")
@require_auth
@require_admin
def desativar(fid):
    row = db.execute("UPDATE fin_funcionarios SET ativo = false WHERE id = %s AND ativo = true RETURNING id", (fid,))
    if row is None:
        return _erro("Funcionário não encontrado", 404)
    return "", 204


# --- para a Caixa da Semana -------------------------------------------------

@bp.get("/pagamentos")
@require_auth
def pagamentos_do_periodo():
    """Pagamentos e DAS **pagos** entre `de` e `ate` — o que sai da sobra.
    DAS em aberto não sai de lugar nenhum ainda."""
    de, ate = request.args.get("de", ""), request.args.get("ate", "")
    if not (_RE_DATA.match(de) and _RE_DATA.match(ate)):
        return _erro("de e ate obrigatórios, no formato AAAA-MM-DD")
    rows = db.query(
        """SELECT l.id, l.tipo, l.valor, l.pago_em AS data_pagamento, l.competencia, l.created_at,
                  f.nome AS funcionario_nome
           FROM fin_funcionario_lancamentos l
           JOIN fin_funcionarios f ON f.id = l.funcionario_id
           WHERE l.tipo IN ('pagamento', 'das') AND l.pago_em IS NOT NULL
             AND l.pago_em BETWEEN %s AND %s
           ORDER BY l.pago_em, l.created_at""",
        (de, ate)
    )
    saida = []
    for r in rows:
        r = dict(r)
        r["data_pagamento"] = _iso(r["data_pagamento"])
        r["competencia"] = _iso(r["competencia"])
        r["valor"] = float(r["valor"] or 0)
        saida.append(r)
    return jsonify(saida)
```

`/pagamentos` vem **antes** das rotas `/<fid>/...` da Task 5 no arquivo; como não há rota `GET /<fid>` sem sufixo, não há ambiguidade — mas manter a ordem evita surpresa.

- [ ] **Step 4: Registrar em `app.py`**

```python
    from routes.funcionarios import bp as funcionarios_bp
    ...
    app.register_blueprint(funcionarios_bp, url_prefix="/api/funcionarios")
```

(logo abaixo de `planejamento_bp`, nos dois blocos.)

- [ ] **Step 5: Rodar**

Run: `venv/bin/python -m pytest tests/test_funcionarios.py -q`
Expected: 6 passando.

- [ ] **Step 6: Commit**

```bash
git add routes/funcionarios.py app.py tests/test_funcionarios.py
git commit -m "feat: cadastro de funcionários com resumo do mês e pagamentos do período

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Lançamentos — listar por competência, meses, criar/editar/apagar com anexo, `/anexo`

**Files:**
- Modify: `routes/funcionarios.py` (acrescentar ao fim)
- Modify: `tests/test_funcionarios.py` (acrescentar)

**Interfaces:**
- Produces (rotas): `GET /<fid>/lancamentos?competencia=AAAA-MM` → `[linha]`; `GET /<fid>/meses?ate=AAAA-MM&n=12` → `[{competencia, ...resumo}]` do mais novo ao mais velho; `POST /<fid>/lancamentos` (201, linha); `PUT /<fid>/lancamentos/<lid>` (linha); `DELETE /<fid>/lancamentos/<lid>` (204); `GET /<fid>/lancamentos/<lid>/anexo?qual=arquivo|boleto|comprovante` → `{url}`.
- Produces (helpers, usados na Task 6): `_pix_ja_lancado(id_transacao, ignorar_id=None) -> {"id","data_pagamento","valor","onde"}|None`; `_um_por_mes(fid, competencia_iso, tipo, ignorar_id=None) -> linha|None`; `_mes_anterior(d, n) -> date`.
- Corpo aceito em POST/PUT: `tipo` (só POST), `competencia`, `valor`, `vencimento`, `pago_em`, `numero_nf`, `id_transacao`, `observacao`, `arquivo_token`, `boleto_token`, `comprovante_token`.
- Erros: 400 validação; 404 funcionário/lançamento; 409 `{"error", "existente_id"}` (DAS/NF repetido) ou `{"error"}` (Pix repetido); 500 Storage ao mover (nada gravado).

- [ ] **Step 1: Testes**

Acrescentar a `tests/test_funcionarios.py`:

```python
# --- lançamentos --------------------------------------------------------------

TOKEN = "pendentes/" + "0" * 32 + ".pdf"
LINHA_PAG = {"id": "l-1", "funcionario_id": FUNC, "tipo": "pagamento", "competencia": "2026-09-01", "valor": 2500.0,
             "vencimento": None, "pago_em": "2026-09-15", "numero_nf": None, "id_transacao": "E8109949120260915120000abc",
             "arquivo_path": None, "boleto_path": None, "comprovante_path": None, "observacao": None}
LINHA_DAS = {**LINHA_PAG, "id": "l-2", "tipo": "das", "valor": 75.9, "vencimento": "2026-10-20", "pago_em": None,
             "id_transacao": None}


def test_listar_lancamentos_da_competencia(client, admin_headers, mocker):
    query = _db(mocker, {"FROM fin_funcionario_lancamentos": [LINHA_PAG, LINHA_DAS]})
    r = client.get(f"/api/funcionarios/{FUNC}/lancamentos?competencia=2026-09", headers=admin_headers)
    assert r.status_code == 200
    assert [l["tipo"] for l in r.get_json()] == ["pagamento", "das"]
    assert query.call_args.args[1] == (FUNC, "2026-09-01")
    assert client.get(f"/api/funcionarios/{FUNC}/lancamentos?competencia=set", headers=admin_headers).status_code == 400


def test_meses_lista_n_meses_com_resumo_mesmo_vazios(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionario_lancamentos": [LINHA_PAG, LINHA_DAS]})
    r = client.get(f"/api/funcionarios/{FUNC}/meses?ate=2026-09&n=3", headers=admin_headers)
    assert r.status_code == 200
    meses = r.get_json()
    assert [m["competencia"] for m in meses] == ["2026-09-01", "2026-08-01", "2026-07-01"]
    assert meses[0]["falta"] == ["nf"] and meses[0]["das_em_aberto"] is True
    assert meses[1]["falta"] == ["pagamento", "das", "nf"]


def test_criar_pagamento_move_anexo_na_transacao(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "UNION ALL": []})
    cur = _transacao_fake(mocker, [{**LINHA_PAG, "arquivo_path": None}])
    mover = mocker.patch("routes.funcionarios.storage.mover")
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={
        "tipo": "pagamento", "competencia": "2026-09", "valor": 2500, "pago_em": "2026-09-15",
        "id_transacao": "E8109949120260915120000abc", "arquivo_token": TOKEN,
    }, headers=admin_headers)
    assert r.status_code == 201, r.get_json()
    insert_sql, insert_params = cur.execute.call_args_list[0].args
    assert "INSERT INTO fin_funcionario_lancamentos" in insert_sql
    assert insert_params[:3] == (FUNC, "pagamento", "2026-09-01")
    destino = f"funcionarios/{FUNC}/2026-09/pagamento-l-1.pdf"
    mover.assert_called_once_with(TOKEN, destino)
    update_sql, update_params = cur.execute.call_args_list[-1].args
    assert "SET arquivo_path = %s" in update_sql and update_params == (destino, "l-1")
    assert r.get_json()["arquivo_path"] == destino


def test_criar_pagamento_valida_valor_e_data(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE]})
    base = {"tipo": "pagamento", "competencia": "2026-09"}
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={**base, "valor": 0, "pago_em": "2026-09-15"},
                       headers=admin_headers).status_code == 400
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={**base, "valor": 10},
                       headers=admin_headers).status_code == 400
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={**base, "valor": 10, "pago_em": "15/09/2026"},
                       headers=admin_headers).status_code == 400
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={"tipo": "ferias", "competencia": "2026-09"},
                       headers=admin_headers).status_code == 400
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={**base, "valor": 10, "pago_em": "2026-09-15",
                       "arquivo_token": "pendentes/../x.pdf"}, headers=admin_headers).status_code == 400


def test_criar_das_em_aberto_com_boleto_e_recusa_o_segundo_do_mes(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "AND tipo = %s": []})
    cur = _transacao_fake(mocker, [{**LINHA_DAS, "boleto_path": None}])
    mover = mocker.patch("routes.funcionarios.storage.mover")
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={
        "tipo": "das", "competencia": "2026-09-01", "valor": 75.9, "vencimento": "2026-10-20", "boleto_token": TOKEN,
    }, headers=admin_headers)
    assert r.status_code == 201, r.get_json()
    mover.assert_called_once_with(TOKEN, f"funcionarios/{FUNC}/2026-09/das-boleto-l-2.pdf")
    assert "SET boleto_path = %s" in cur.execute.call_args_list[-1].args[0]

    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "AND tipo = %s": [LINHA_DAS]})
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={"tipo": "das", "competencia": "2026-09", "valor": 75.9},
                    headers=admin_headers)
    assert r.status_code == 409
    assert r.get_json()["existente_id"] == "l-2"


def test_criar_nf_exige_numero_ou_arquivo(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "AND tipo = %s": []})
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={"tipo": "nf", "competencia": "2026-08"},
                    headers=admin_headers)
    assert r.status_code == 400 and "número" in r.get_json()["error"]
    _transacao_fake(mocker, [{**LINHA_PAG, "id": "l-3", "tipo": "nf", "numero_nf": "123", "valor": None, "pago_em": None}])
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={"tipo": "nf", "competencia": "2026-08", "numero_nf": "123"},
                    headers=admin_headers)
    assert r.status_code == 201 and r.get_json()["valor"] is None


def test_pix_repetido_em_qualquer_tabela_da_409(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE],
                 "UNION ALL": [{"id": "pg-1", "data_pagamento": "2026-09-15", "valor": 2500.0, "onde": "fornecedor"}]})
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={
        "tipo": "pagamento", "competencia": "2026-09", "valor": 2500, "pago_em": "2026-09-15",
        "id_transacao": "E8109949120260915120000abc",
    }, headers=admin_headers)
    assert r.status_code == 409
    assert "15/09/2026" in r.get_json()["error"] and "fornecedor" in r.get_json()["error"]


def test_storage_falha_ao_mover_nada_gravado(client, admin_headers, mocker):
    import storage
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "UNION ALL": []})
    _transacao_fake(mocker, [{**LINHA_PAG}])
    mocker.patch("routes.funcionarios.storage.mover", side_effect=storage.StorageErro("fora"))
    r = client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={
        "tipo": "pagamento", "competencia": "2026-09", "valor": 2500, "pago_em": "2026-09-15", "arquivo_token": TOKEN,
    }, headers=admin_headers)
    assert r.status_code == 500
    assert "nada foi salvo" in r.get_json()["error"]


def test_editar_marca_das_pago_e_move_comprovante(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionario_lancamentos WHERE id = %s": [LINHA_DAS], "UNION ALL": [], "AND tipo = %s": []})
    cur = _transacao_fake(mocker, [{**LINHA_DAS, "pago_em": "2026-10-18", "id_transacao": "E81099491202610181200zz"}])
    mover = mocker.patch("routes.funcionarios.storage.mover")
    r = client.put(f"/api/funcionarios/{FUNC}/lancamentos/l-2", json={
        "pago_em": "2026-10-18", "id_transacao": "E81099491202610181200zz", "comprovante_token": TOKEN,
    }, headers=admin_headers)
    assert r.status_code == 200, r.get_json()
    update_sql, update_params = cur.execute.call_args_list[0].args
    assert "UPDATE fin_funcionario_lancamentos" in update_sql
    # mesclado com a linha atual: valor e vencimento continuam
    assert 75.9 in update_params and "2026-10-20" in update_params and "2026-10-18" in update_params
    mover.assert_called_once_with(TOKEN, f"funcionarios/{FUNC}/2026-09/das-comprovante-l-2.pdf")
    assert r.get_json()["pago_em"] == "2026-10-18"


def test_editar_competencia_de_nf_para_mes_que_ja_tem_nf_da_409(client, admin_headers, mocker):
    nf = {**LINHA_PAG, "id": "l-3", "tipo": "nf", "numero_nf": "123", "pago_em": None}
    _db(mocker, {"FROM fin_funcionario_lancamentos WHERE id = %s": [nf],
                 "AND tipo = %s": lambda params: [{**nf, "id": "l-9"}] if params[1] == "2026-08-01" else []})
    r = client.put(f"/api/funcionarios/{FUNC}/lancamentos/l-3", json={"competencia": "2026-08"}, headers=admin_headers)
    assert r.status_code == 409 and r.get_json()["existente_id"] == "l-9"


def test_editar_lancamento_inexistente_404(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionario_lancamentos WHERE id = %s": []})
    assert client.put(f"/api/funcionarios/{FUNC}/lancamentos/l-x", json={"valor": 1}, headers=admin_headers).status_code == 404


def test_apagar_lancamento(client, admin_headers, mocker):
    execute = mocker.patch("routes.funcionarios.db.execute", return_value={"id": "l-1"})
    assert client.delete(f"/api/funcionarios/{FUNC}/lancamentos/l-1", headers=admin_headers).status_code == 204
    assert execute.call_args.args[1] == ("l-1", FUNC)
    execute.return_value = None
    assert client.delete(f"/api/funcionarios/{FUNC}/lancamentos/l-1", headers=admin_headers).status_code == 404


def test_anexo_por_qual(client, admin_headers, mocker):
    url = mocker.patch("routes.funcionarios.anexos.url_anexo", return_value=jsonify_ok())
    r = client.get(f"/api/funcionarios/{FUNC}/lancamentos/l-2/anexo?qual=boleto", headers=admin_headers)
    assert r.status_code == 200
    url.assert_called_once_with("fin_funcionario_lancamentos", "funcionario_id", FUNC, "l-2", "boleto_path")
    assert client.get(f"/api/funcionarios/{FUNC}/lancamentos/l-2/anexo?qual=senha", headers=admin_headers).status_code == 400


def jsonify_ok():
    from flask import jsonify
    from app import create_app
    with create_app().app_context():
        return jsonify({"url": "https://x/assinada"})


def test_viewer_nao_grava_lancamento(client, viewer_headers):
    assert client.post(f"/api/funcionarios/{FUNC}/lancamentos", json={}, headers=viewer_headers).status_code == 403
    assert client.put(f"/api/funcionarios/{FUNC}/lancamentos/l-1", json={}, headers=viewer_headers).status_code == 403
    assert client.delete(f"/api/funcionarios/{FUNC}/lancamentos/l-1", headers=viewer_headers).status_code == 403
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_funcionarios.py -q`
Expected: os 14 novos falham com 404/405.

- [ ] **Step 3: Implementar (acrescentar ao fim de `routes/funcionarios.py`)**

```python
# --- lançamentos --------------------------------------------------------------

def _mes_anterior(d, n):
    ano, mes = d.year, d.month - n
    while mes <= 0:
        mes += 12
        ano -= 1
    return date(ano, mes, 1)


def _data_ou_erro(texto):
    """'AAAA-MM-DD' → o texto; vazio → None; inválido → ValueError."""
    if texto in (None, ""):
        return None
    if not isinstance(texto, str) or not _RE_DATA.match(texto):
        raise ValueError(texto)
    date.fromisoformat(texto)
    return texto


def _campos_lancamento(tipo, data, atual=None):
    """Mescla o corpo com a linha atual (PUT) e aplica as regras do tipo.
    Devolve (campos, erro). `campos['competencia']` é date."""
    base = {k: (atual or {}).get(k) for k in
            ("competencia", "valor", "vencimento", "pago_em", "numero_nf", "id_transacao", "observacao")}
    for k in base:
        if k in data:
            base[k] = data[k]

    comp = _competencia(base["competencia"])
    if comp is None:
        return None, "competencia inválida (use AAAA-MM)"
    if base["valor"] in (None, ""):
        valor = None
    else:
        try:
            valor = float(base["valor"])
        except (TypeError, ValueError):
            return None, "valor inválido"
    try:
        vencimento = _data_ou_erro(base["vencimento"])
        pago_em = _data_ou_erro(base["pago_em"])
    except ValueError:
        return None, "data inválida (use AAAA-MM-DD)"
    texto = lambda v: (v.strip() or None) if isinstance(v, str) else None

    if tipo in ("pagamento", "das") and (valor is None or valor <= 0):
        return None, "valor deve ser maior que zero"
    if tipo == "pagamento" and not pago_em:
        return None, "pago_em obrigatório"
    if tipo == "nf" and valor is not None and valor < 0:
        return None, "valor inválido"

    return {
        "competencia": comp, "valor": valor, "vencimento": vencimento, "pago_em": pago_em,
        "numero_nf": texto(base["numero_nf"]), "id_transacao": texto(base["id_transacao"]),
        "observacao": texto(base["observacao"]),
    }, None


def _tokens(data):
    """Devolve ({campo: token}, erro) só com os tokens presentes e válidos."""
    tokens = {}
    for campo, _, _ in ANEXOS:
        t = (data.get(campo) or "").strip() if isinstance(data.get(campo), str) else None
        if t:
            if not anexos.arquivo_token_valido(t):
                return None, f"{campo} inválido"
            tokens[campo] = t
    return tokens, None


def _pix_ja_lancado(id_transacao, ignorar_id=None):
    """O mesmo E2E em fornecedores OU funcionários. Índice não atravessa tabela."""
    sql = """SELECT id, data_pagamento, valor, 'fornecedor' AS onde
               FROM fin_pagamentos_fornecedor WHERE id_transacao = %s
             UNION ALL
             SELECT id, pago_em AS data_pagamento, valor, 'funcionário' AS onde
               FROM fin_funcionario_lancamentos WHERE id_transacao = %s"""
    params = [id_transacao, id_transacao]
    if ignorar_id:
        sql += " AND id <> %s"
        params.append(ignorar_id)
    rows = db.query(sql, tuple(params))
    if not rows:
        return None
    r = rows[0]
    return {"id": r["id"], "data_pagamento": _iso(r["data_pagamento"]), "valor": float(r["valor"] or 0), "onde": r["onde"]}


def _msg_pix_repetido(existente):
    quando = existente["data_pagamento"]
    try:
        quando = date.fromisoformat(quando).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        pass
    return f"Esse comprovante já foi lançado em {quando} (R$ {existente['valor']:.2f}) — em {existente['onde']}"


def _um_por_mes(fid, competencia_iso, tipo, ignorar_id=None):
    sql = """SELECT * FROM fin_funcionario_lancamentos
             WHERE funcionario_id = %s AND competencia = %s AND tipo = %s"""
    params = [fid, competencia_iso, tipo]
    if ignorar_id:
        sql += " AND id <> %s"
        params.append(ignorar_id)
    rows = db.query(sql + " LIMIT 1", tuple(params))
    return _linha(rows[0]) if rows else None


def _mover_anexos(cur, fid, tipo, row, tokens):
    """Dentro da transação: move cada token para o destino e grava a coluna."""
    pasta = row["competencia"].strftime("%Y-%m") if isinstance(row["competencia"], date) else str(row["competencia"])[:7]
    for campo, coluna, sufixo in ANEXOS:
        token = tokens.get(campo)
        if not token:
            continue
        destino = anexos.destino_anexo(f"funcionarios/{fid}", pasta, f"{tipo}{sufixo}-{row['id']}", token)
        storage.mover(token, destino)
        cur.execute(f"UPDATE fin_funcionario_lancamentos SET {coluna} = %s WHERE id = %s", (destino, row["id"]))
        row[coluna] = destino


@bp.get("/<fid>/lancamentos")
@require_auth
def listar_lancamentos(fid):
    comp = _competencia(request.args.get("competencia"))
    if comp is None:
        return _erro("competencia obrigatória, no formato AAAA-MM")
    rows = db.query(
        """SELECT * FROM fin_funcionario_lancamentos
           WHERE funcionario_id = %s AND competencia = %s
           ORDER BY CASE tipo WHEN 'pagamento' THEN 1 WHEN 'das' THEN 2 ELSE 3 END, pago_em, created_at""",
        (fid, comp.isoformat())
    )
    return jsonify([_linha(r) for r in rows])


@bp.get("/<fid>/meses")
@require_auth
def meses(fid):
    ate = _competencia(request.args.get("ate")) or _hoje().replace(day=1)
    try:
        n = max(1, min(36, int(request.args.get("n", 12))))
    except ValueError:
        n = 12
    lista = [_mes_anterior(ate, i) for i in range(n)]
    rows = db.query(
        """SELECT * FROM fin_funcionario_lancamentos
           WHERE funcionario_id = %s AND competencia BETWEEN %s AND %s""",
        (fid, lista[-1].isoformat(), ate.isoformat())
    )
    por_mes = {}
    for r in rows:
        por_mes.setdefault(_iso(r["competencia"]), []).append(dict(r))
    return jsonify([{"competencia": m.isoformat(), **_resumo(por_mes.get(m.isoformat(), []))} for m in lista])


@bp.post("/<fid>/lancamentos")
@require_auth
@require_admin
def criar_lancamento(fid):
    data = request.get_json() or {}
    tipo = data.get("tipo")
    if tipo not in TIPOS:
        return _erro("tipo deve ser pagamento, das ou nf")
    if _funcionario(fid) is None:
        return _erro("Funcionário não encontrado", 404)
    campos, erro = _campos_lancamento(tipo, data)
    if erro:
        return _erro(erro)
    tokens, erro = _tokens(data)
    if erro:
        return _erro(erro)
    if tipo == "nf" and not campos["numero_nf"] and "arquivo_token" not in tokens:
        return _erro("Informe o número da nota ou suba o arquivo")

    comp_iso = campos["competencia"].isoformat()
    if campos["id_transacao"]:
        existente = _pix_ja_lancado(campos["id_transacao"])
        if existente:
            return _erro(_msg_pix_repetido(existente), 409)
    if tipo in ("das", "nf"):
        existente = _um_por_mes(fid, comp_iso, tipo)
        if existente:
            return jsonify({"error": f"Já existe {ROTULO_TIPO[tipo]} em {campos['competencia'].strftime('%m/%Y')}",
                            "existente_id": existente["id"]}), 409

    try:
        with db.transaction() as cur:
            cur.execute(
                """INSERT INTO fin_funcionario_lancamentos
                   (funcionario_id, tipo, competencia, valor, vencimento, pago_em, numero_nf, id_transacao, observacao, criado_por)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (fid, tipo, comp_iso, campos["valor"], campos["vencimento"], campos["pago_em"],
                 campos["numero_nf"], campos["id_transacao"], campos["observacao"], g.user["user_id"])
            )
            row = dict(cur.fetchone())
            _mover_anexos(cur, fid, tipo, row, tokens)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao mover anexo de funcionário: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return _erro("Não consegui guardar o anexo; nada foi salvo. Tente de novo.", 500)
    return jsonify(_linha(row)), 201


@bp.put("/<fid>/lancamentos/<lid>")
@require_auth
@require_admin
def editar_lancamento(fid, lid):
    data = request.get_json() or {}
    rows = db.query("SELECT * FROM fin_funcionario_lancamentos WHERE id = %s AND funcionario_id = %s", (lid, fid))
    if not rows:
        return _erro("Lançamento não encontrado", 404)
    atual = _linha(rows[0])
    tipo = atual["tipo"]
    campos, erro = _campos_lancamento(tipo, data, atual)
    if erro:
        return _erro(erro)
    tokens, erro = _tokens(data)
    if erro:
        return _erro(erro)
    if tipo == "nf" and not campos["numero_nf"] and "arquivo_token" not in tokens and not atual.get("arquivo_path"):
        return _erro("Informe o número da nota ou suba o arquivo")

    comp_iso = campos["competencia"].isoformat()
    if campos["id_transacao"] and campos["id_transacao"] != atual.get("id_transacao"):
        existente = _pix_ja_lancado(campos["id_transacao"], ignorar_id=lid)
        if existente:
            return _erro(_msg_pix_repetido(existente), 409)
    if tipo in ("das", "nf") and comp_iso != atual["competencia"]:
        existente = _um_por_mes(fid, comp_iso, tipo, ignorar_id=lid)
        if existente:
            return jsonify({"error": f"Já existe {ROTULO_TIPO[tipo]} em {campos['competencia'].strftime('%m/%Y')}",
                            "existente_id": existente["id"]}), 409

    try:
        with db.transaction() as cur:
            cur.execute(
                """UPDATE fin_funcionario_lancamentos
                   SET competencia = %s, valor = %s, vencimento = %s, pago_em = %s,
                       numero_nf = %s, id_transacao = %s, observacao = %s
                   WHERE id = %s AND funcionario_id = %s
                   RETURNING *""",
                (comp_iso, campos["valor"], campos["vencimento"], campos["pago_em"],
                 campos["numero_nf"], campos["id_transacao"], campos["observacao"], lid, fid)
            )
            row = dict(cur.fetchone())
            _mover_anexos(cur, fid, tipo, row, tokens)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao mover anexo de funcionário: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return _erro("Não consegui guardar o anexo; nada foi alterado. Tente de novo.", 500)
    return jsonify(_linha(row))


@bp.delete("/<fid>/lancamentos/<lid>")
@require_auth
@require_admin
def apagar_lancamento(fid, lid):
    # Os arquivos ficam no bucket (limpeza é fora do escopo do desenho).
    row = db.execute("DELETE FROM fin_funcionario_lancamentos WHERE id = %s AND funcionario_id = %s RETURNING id", (lid, fid))
    if row is None:
        return _erro("Lançamento não encontrado", 404)
    return "", 204


@bp.get("/<fid>/lancamentos/<lid>/anexo")
@require_auth
def anexo_lancamento(fid, lid):
    coluna = COLUNAS_ANEXO.get(request.args.get("qual", "arquivo"))
    if coluna is None:
        return _erro("qual deve ser arquivo, boleto ou comprovante")
    return anexos.url_anexo("fin_funcionario_lancamentos", "funcionario_id", fid, lid, coluna)
```

Sobre `_mover_anexos` e a competência: no INSERT o `RETURNING *` devolve `competencia` como `date` (psycopg2) — no teste mockado vem texto `'2026-09-01'`, por isso o `[:7]`.

- [ ] **Step 4: Rodar tudo**

Run: `venv/bin/python -m pytest tests -q`
Expected: tudo verde.

- [ ] **Step 5: Commit**

```bash
git add routes/funcionarios.py tests/test_funcionarios.py
git commit -m "feat: lançamentos de funcionário por competência com anexos e regras por tipo

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Leitura — `POST /<fid>/ler/pix`, `/ler/das`, `/ler/nf`

**Files:**
- Modify: `routes/funcionarios.py` (acrescentar)
- Modify: `tests/test_funcionarios.py` (acrescentar)

**Interfaces:**
- Produces:
  - `POST /<fid>/ler/pix` → `{leitura_falhou, arquivo_token, aviso, valor, data_pagamento, destinatario, id_transacao, pagamento_existente}` (`pagamento_existente` = `_pix_ja_lancado(...)` ou `None`).
  - `POST /<fid>/ler/das` → `{leitura_falhou, arquivo_token, aviso, valor, vencimento, competencia, cnpj, nome, cnpj_confere, das_existente}`.
  - `POST /<fid>/ler/nf` → `{leitura_falhou, arquivo_token, aviso, numero, valor, data_emissao, competencia, competencia_inferida, cnpj_prestador, nome_prestador, cnpj_confere, nf_existente}`.
  - `cnpj_confere`: `None` se o cadastro ou o documento não tem CNPJ; senão `True/False`.
  - 503 `{"error": MSG_LEITURA_INDISPONIVEL}` se a IA está fora; 400 arquivo inválido; 404 funcionário.
- Consumes: `anexos.ler_arquivo_enviado`, `anexos.subir_pendente`, `leitura_documento.ler_comprovante/ler_boleto_das/ler_nota_fiscal`, `_pix_ja_lancado`, `_um_por_mes`, `_funcionario`.

- [ ] **Step 1: Testes**

Acrescentar a `tests/test_funcionarios.py`:

```python
# --- /ler ---------------------------------------------------------------------
import io


def _arquivo(nome="doc.pdf", mime="application/pdf", conteudo=b"%PDF-1.4 fake"):
    return {"arquivo": (io.BytesIO(conteudo), nome, mime)}


@pytest.fixture
def storage_ok(mocker):
    mocker.patch("routes.funcionarios.storage.limpar_pendentes", return_value=0)
    mocker.patch("routes.funcionarios.storage.enviar_pendente", return_value="pendentes/abc.pdf")


def test_ler_pix_devolve_leitura_token_e_pix_repetido(client, admin_headers, mocker, storage_ok):
    mocker.patch("routes.funcionarios.leitura_documento.ler_comprovante", return_value={
        "valor": 2500.0, "data_pagamento": "2026-09-15", "destinatario": "JOSIE DA SILVA", "id_transacao": "E81zz"})
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE],
                 "UNION ALL": [{"id": "l-1", "data_pagamento": "2026-09-15", "valor": 2500.0, "onde": "funcionário"}]})
    r = client.post(f"/api/funcionarios/{FUNC}/ler/pix", data=_arquivo(), headers=admin_headers,
                    content_type="multipart/form-data")
    assert r.status_code == 200
    lido = r.get_json()
    assert lido["leitura_falhou"] is False and lido["arquivo_token"] == "pendentes/abc.pdf"
    assert lido["valor"] == 2500.0 and lido["id_transacao"] == "E81zz"
    assert lido["pagamento_existente"]["onde"] == "funcionário"


def test_ler_das_confere_cnpj_e_acha_das_do_mes_lido(client, admin_headers, mocker, storage_ok):
    mocker.patch("routes.funcionarios.leitura_documento.ler_boleto_das", return_value={
        "valor": 75.9, "vencimento": "2026-10-20", "competencia": "2026-09-01", "cnpj": "99999999000199", "nome": "OUTRA"})
    query = _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "AND tipo = %s": [LINHA_DAS]})
    r = client.post(f"/api/funcionarios/{FUNC}/ler/das", data=_arquivo(), headers=admin_headers,
                    content_type="multipart/form-data")
    assert r.status_code == 200
    lido = r.get_json()
    assert lido["cnpj_confere"] is False
    assert lido["competencia"] == "2026-09-01"
    assert lido["das_existente"]["id"] == "l-2"
    assert query.call_args.args[1] == (FUNC, "2026-09-01", "das")


def test_ler_das_sem_cnpj_no_cadastro_nao_confere(client, admin_headers, mocker, storage_ok):
    mocker.patch("routes.funcionarios.leitura_documento.ler_boleto_das", return_value={
        "valor": 75.9, "vencimento": None, "competencia": None, "cnpj": "99999999000199", "nome": None})
    _db(mocker, {"FROM fin_funcionarios WHERE": [{**JOSIE, "cnpj": None}]})
    lido = client.post(f"/api/funcionarios/{FUNC}/ler/das", data=_arquivo(), headers=admin_headers,
                       content_type="multipart/form-data").get_json()
    assert lido["cnpj_confere"] is None and lido["das_existente"] is None


def test_ler_nf_leitura_falhou_mantem_token(client, admin_headers, mocker, storage_ok):
    import leitura_documento
    mocker.patch("routes.funcionarios.leitura_documento.ler_nota_fiscal", side_effect=leitura_documento.LeituraFalhou("x"))
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE]})
    r = client.post(f"/api/funcionarios/{FUNC}/ler/nf", data=_arquivo("nf.png", "image/png", b"\x89PNG"),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 200
    lido = r.get_json()
    assert lido["leitura_falhou"] is True and lido["arquivo_token"] == "pendentes/abc.pdf"
    assert lido["numero"] is None and lido["nf_existente"] is None


def test_ler_nf_ia_fora_503_e_nao_sobe_arquivo(client, admin_headers, mocker, storage_ok):
    import leitura_documento
    mocker.patch("routes.funcionarios.leitura_documento.ler_nota_fiscal", side_effect=leitura_documento.LeituraIndisponivel("x"))
    enviar = mocker.patch("routes.funcionarios.storage.enviar_pendente")
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE]})
    r = client.post(f"/api/funcionarios/{FUNC}/ler/nf", data=_arquivo(), headers=admin_headers,
                    content_type="multipart/form-data")
    assert r.status_code == 503
    enviar.assert_not_called()


def test_ler_storage_falha_devolve_aviso(client, admin_headers, mocker):
    import storage
    mocker.patch("routes.funcionarios.storage.limpar_pendentes", return_value=0)
    mocker.patch("routes.funcionarios.storage.enviar_pendente", side_effect=storage.StorageErro("fora"))
    mocker.patch("routes.funcionarios.leitura_documento.ler_nota_fiscal", return_value={
        "numero": "123", "valor": 2500.0, "data_emissao": "2026-09-05", "competencia": "2026-09-01",
        "competencia_inferida": True, "cnpj_prestador": "12345678000195", "nome_prestador": "JOSIE"})
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE], "AND tipo = %s": []})
    lido = client.post(f"/api/funcionarios/{FUNC}/ler/nf", data=_arquivo(), headers=admin_headers,
                       content_type="multipart/form-data").get_json()
    assert lido["arquivo_token"] is None and "guardar" in lido["aviso"]
    assert lido["cnpj_confere"] is True and lido["competencia_inferida"] is True


def test_ler_arquivo_invalido_400_e_viewer_403(client, admin_headers, viewer_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE]})
    r = client.post(f"/api/funcionarios/{FUNC}/ler/pix", data=_arquivo("a.gif", "image/gif", b"gif"),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 400
    r = client.post(f"/api/funcionarios/{FUNC}/ler/pix", data=_arquivo(), headers=viewer_headers,
                    content_type="multipart/form-data")
    assert r.status_code == 403
```

Atenção ao `conftest`: o mock de usuário escolhe viewer quando o **nome do teste** contém "viewer" — por isso o último teste, que usa os dois headers, precisa de `viewer` no nome e usa `admin_headers` só para o 400 (o 400 acontece antes do `require_admin`? **Não**: `require_admin` vem antes do corpo. Então nesse teste o usuário é viewer nas duas chamadas; a primeira também dá 403). Corrigir o teste para o que realmente acontece:

```python
def test_ler_arquivo_invalido_400(client, admin_headers, mocker):
    _db(mocker, {"FROM fin_funcionarios WHERE": [JOSIE]})
    r = client.post(f"/api/funcionarios/{FUNC}/ler/pix", data=_arquivo("a.gif", "image/gif", b"gif"),
                    headers=admin_headers, content_type="multipart/form-data")
    assert r.status_code == 400


def test_ler_viewer_403(client, viewer_headers):
    r = client.post(f"/api/funcionarios/{FUNC}/ler/pix", data=_arquivo(), headers=viewer_headers,
                    content_type="multipart/form-data")
    assert r.status_code == 403
```

(Usar estas duas versões; não a combinada.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `venv/bin/python -m pytest tests/test_funcionarios.py -q -k ler`
Expected: falham com 404.

- [ ] **Step 3: Implementar (acrescentar ao fim de `routes/funcionarios.py`)**

```python
# --- leitura por IA (só lê; gravar é no Salvar dela) --------------------------

def _ler_e_guardar(leitor, rotulo):
    """Lê o multipart com `leitor` e sobe para pendentes/.
    Devolve (lido|None, token|None, aviso|None, resposta_de_erro|None)."""
    dados, mime, erro = anexos.ler_arquivo_enviado()
    if erro:
        return None, None, None, erro
    try:
        lido = leitor(dados, mime)
    except leitura_documento.LeituraIndisponivel as e:
        print(f"[leitura_documento] indisponível ao ler {rotulo}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return None, None, None, (jsonify({"error": anexos.MSG_LEITURA_INDISPONIVEL}), 503)
    except leitura_documento.LeituraFalhou as e:
        print(f"[leitura_documento] falhou ao ler {rotulo}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        lido = None
    # Guardar o arquivo é o acessório: se o Storage falhar, ela ainda lança o
    # que a IA leu — só sem o anexo.
    aviso = None
    try:
        token = anexos.subir_pendente(dados, mime)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao guardar {rotulo}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        token = None
        aviso = anexos.MSG_ANEXO_NAO_GUARDADO
    return lido, token, aviso, None


def _cnpj_confere(funcionario, cnpj_lido):
    if not funcionario.get("cnpj") or not cnpj_lido:
        return None
    return funcionario["cnpj"] == cnpj_lido


@bp.post("/<fid>/ler/pix")
@require_auth
@require_admin
def ler_pix(fid):
    if _funcionario(fid) is None:
        return _erro("Funcionário não encontrado", 404)
    lido, token, aviso, erro = _ler_e_guardar(leitura_documento.ler_comprovante, "comprovante")
    if erro:
        return erro
    base = {"leitura_falhou": lido is None, "arquivo_token": token, "aviso": aviso,
            "valor": None, "data_pagamento": None, "destinatario": None, "id_transacao": None,
            "pagamento_existente": None}
    if lido is None:
        return jsonify(base)
    return jsonify({**base, **lido,
                    "pagamento_existente": _pix_ja_lancado(lido["id_transacao"]) if lido["id_transacao"] else None})


@bp.post("/<fid>/ler/das")
@require_auth
@require_admin
def ler_das(fid):
    f = _funcionario(fid)
    if f is None:
        return _erro("Funcionário não encontrado", 404)
    lido, token, aviso, erro = _ler_e_guardar(leitura_documento.ler_boleto_das, "boleto DAS")
    if erro:
        return erro
    base = {"leitura_falhou": lido is None, "arquivo_token": token, "aviso": aviso,
            "valor": None, "vencimento": None, "competencia": None, "cnpj": None, "nome": None,
            "cnpj_confere": None, "das_existente": None}
    if lido is None:
        return jsonify(base)
    existente = _um_por_mes(fid, lido["competencia"], "das") if lido["competencia"] else None
    return jsonify({**base, **lido, "cnpj_confere": _cnpj_confere(f, lido["cnpj"]), "das_existente": existente})


@bp.post("/<fid>/ler/nf")
@require_auth
@require_admin
def ler_nf(fid):
    f = _funcionario(fid)
    if f is None:
        return _erro("Funcionário não encontrado", 404)
    lido, token, aviso, erro = _ler_e_guardar(leitura_documento.ler_nota_fiscal, "nota fiscal")
    if erro:
        return erro
    base = {"leitura_falhou": lido is None, "arquivo_token": token, "aviso": aviso,
            "numero": None, "valor": None, "data_emissao": None, "competencia": None,
            "competencia_inferida": False, "cnpj_prestador": None, "nome_prestador": None,
            "cnpj_confere": None, "nf_existente": None}
    if lido is None:
        return jsonify(base)
    existente = _um_por_mes(fid, lido["competencia"], "nf") if lido["competencia"] else None
    return jsonify({**base, **lido, "cnpj_confere": _cnpj_confere(f, lido["cnpj_prestador"]), "nf_existente": existente})
```

- [ ] **Step 4: Rodar tudo**

Run: `venv/bin/python -m pytest tests -q`
Expected: tudo verde.

- [ ] **Step 5: Commit**

```bash
git add routes/funcionarios.py tests/test_funcionarios.py
git commit -m "feat: leitura de Pix, DAS e NF do funcionário com checagem de duplicidade e CNPJ

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Aplicar a migração no Supabase (operação — pedir o OK dela antes)

**Files:** nenhum no repo.

**Interfaces:**
- Produces: tabelas `fin_funcionarios` e `fin_funcionario_lancamentos` em produção (projeto `tywirfmaosfztcmalbno`).

- [ ] **Step 1: Pedir o OK**

Mensagem curta para a Cibelly: "Backend pronto e testado. Posso aplicar a migração das duas tabelas de funcionários no Supabase? Não mexe em nada que já existe." Esperar o sim.

- [ ] **Step 2: Aplicar**

Ferramenta MCP do Supabase `apply_migration` (projeto `tywirfmaosfztcmalbno`, nome `funcionarios`) com o conteúdo de `supabase/migrations/20260917_funcionarios.sql`.

- [ ] **Step 3: Conferir**

`execute_sql`:
```sql
SELECT table_name, column_name FROM information_schema.columns
WHERE table_name IN ('fin_funcionarios', 'fin_funcionario_lancamentos') ORDER BY 1, ordinal_position;
SELECT indexname FROM pg_indexes WHERE tablename = 'fin_funcionario_lancamentos';
SELECT tablename, policyname FROM pg_policies WHERE tablename IN ('fin_funcionarios', 'fin_funcionario_lancamentos');
```
Expected: 6 + 15 colunas; 4 índices próprios (+ pkey); 4 policies.

---

### Task 8 (frontend): `lib/meses.js` e `components/upload/comum.jsx` extraído do `UploadPedidoCompra`

**Files:**
- Create: `src/lib/meses.js`, `src/lib/meses.test.js`
- Create: `src/components/upload/comum.jsx`, `src/components/upload/comum.test.jsx`
- Modify: `src/components/UploadPedidoCompra.jsx` (linhas 9–43 e 313–323: usar o comum)
- Modify: `src/pages/Fornecedores.jsx` (linhas 852–864: `abrirAnexo` passa a vir do comum)

**Interfaces:**
- Produces (`src/lib/meses.js`): `mesAtual(hoje = new Date()) -> 'AAAA-MM'`; `mesDe(data) -> 'AAAA-MM' | null` (aceita `'AAAA-MM'`, `'AAAA-MM-DD'`, RFC-1123 do backend); `rotuloMes('2026-09') -> 'Setembro 2026'`.
- Produces (`src/components/upload/comum.jsx`): `TIPOS`, `TAMANHO_MAX`, `inputStyle`, `botaoPrimario`, `botaoSecundario`, `formatMoeda(v)`, `formatData(data)`, `Faixa({tipo='aviso'|'erro', children})`, `validarArquivo(arquivo) -> string|null`, `mensagemDe(err, padrao)`, `PreviewArquivo({url, tipo, alt})`, `BotaoSubirArquivo({rotulo, rotuloLendo, lendo, disabled, onArquivo, style})`, `abrirAnexo(caminho)`.

- [ ] **Step 1: Branch**

```bash
cd /Users/macbookpro/Desktop/Claude/financeiro-frontend
git fetch origin && git checkout -b feat/funcionarios origin/main
```

- [ ] **Step 2: Testes de `meses.js`**

```js
// src/lib/meses.test.js
import { describe, it, expect } from 'vitest'
import { mesAtual, mesDe, rotuloMes } from './meses'

describe('meses', () => {
  it('mesAtual usa a data local', () => {
    expect(mesAtual(new Date(2026, 8, 17))).toBe('2026-09')
    expect(mesAtual(new Date(2026, 0, 1))).toBe('2026-01')
  })
  it('mesDe aceita AAAA-MM, AAAA-MM-DD e a data RFC que o backend manda', () => {
    expect(mesDe('2026-09')).toBe('2026-09')
    expect(mesDe('2026-09-01')).toBe('2026-09')
    expect(mesDe('Tue, 01 Sep 2026 00:00:00 GMT')).toBe('2026-09')
    expect(mesDe(null)).toBeNull()
    expect(mesDe('não é data')).toBeNull()
  })
  it('rotuloMes escreve o mês por extenso', () => {
    expect(rotuloMes('2026-09')).toBe('Setembro 2026')
    expect(rotuloMes('')).toBe('')
  })
})
```

- [ ] **Step 3: `src/lib/meses.js`**

```js
// Meses no formato 'AAAA-MM' — o que o <input type="month"> fala e o que o
// backend aceita como competência.
const NOMES = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

export function mesAtual(hoje = new Date()) {
  return `${hoje.getFullYear()}-${String(hoje.getMonth() + 1).padStart(2, '0')}`
}

/** '2026-09', '2026-09-01' ou data RFC do backend → '2026-09'. Sem data → null. */
export function mesDe(data) {
  if (!data) return null
  if (typeof data === 'string' && /^\d{4}-\d{2}(-\d{2})?$/.test(data)) return data.slice(0, 7)
  const d = new Date(data)
  if (Number.isNaN(d.getTime())) return null
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
}

export function rotuloMes(mes) {
  if (!mes) return ''
  const [ano, m] = mes.split('-')
  return `${NOMES[Number(m) - 1]} ${ano}`
}
```

- [ ] **Step 4: Testes do `comum.jsx`**

```jsx
// src/components/upload/comum.test.jsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { validarArquivo, mensagemDe, Faixa, BotaoSubirArquivo, PreviewArquivo } from './comum'

vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }))

describe('comum do upload', () => {
  it('validarArquivo recusa tipo e tamanho errados', () => {
    expect(validarArquivo(null)).toBe('Escolha um arquivo.')
    expect(validarArquivo(new File(['x'], 'a.gif', { type: 'image/gif' }))).toBe('Só PDF, JPG ou PNG.')
    const grande = new File(['x'], 'a.pdf', { type: 'application/pdf' })
    Object.defineProperty(grande, 'size', { value: 11 * 1024 * 1024 })
    expect(validarArquivo(grande)).toBe('Arquivo maior que 10 MB.')
    expect(validarArquivo(new File(['x'], 'a.pdf', { type: 'application/pdf' }))).toBeNull()
  })
  it('mensagemDe prefere o erro do servidor', () => {
    expect(mensagemDe({ response: { data: { error: 'servidor' } } }, 'padrão')).toBe('servidor')
    expect(mensagemDe(new Error('x'), 'padrão')).toBe('padrão')
  })
  it('Faixa mostra o texto', () => {
    render(<Faixa tipo="erro">deu ruim</Faixa>)
    expect(screen.getByText('deu ruim')).toBeInTheDocument()
  })
  it('BotaoSubirArquivo entrega o arquivo escolhido e muda o rótulo enquanto lê', () => {
    const onArquivo = vi.fn()
    const { container, rerender } = render(<BotaoSubirArquivo rotulo="📎 Subir NF" rotuloLendo="Lendo…" onArquivo={onArquivo} />)
    const arquivo = new File(['x'], 'nf.pdf', { type: 'application/pdf' })
    fireEvent.change(container.querySelector('input[type=file]'), { target: { files: [arquivo] } })
    expect(onArquivo).toHaveBeenCalledWith(arquivo)
    rerender(<BotaoSubirArquivo rotulo="📎 Subir NF" rotuloLendo="Lendo…" lendo onArquivo={onArquivo} />)
    expect(screen.getByRole('button', { name: 'Lendo…' })).toBeDisabled()
  })
  it('PreviewArquivo mostra PDF como object e imagem como img', () => {
    const { container, rerender } = render(<PreviewArquivo url="blob:a" tipo="application/pdf" />)
    expect(container.querySelector('object[type="application/pdf"]')).not.toBeNull()
    rerender(<PreviewArquivo url="blob:b" tipo="image/png" alt="foto" />)
    expect(screen.getByAltText('foto')).toBeInTheDocument()
  })
})
```

- [ ] **Step 5: Rodar e ver falhar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/lib src/components/upload`
Expected: falha ao resolver `./meses` e `./comum`.

- [ ] **Step 6: `src/components/upload/comum.jsx`**

```jsx
// src/components/upload/comum.jsx
// O que os cartões de upload (pedido de compra, documentos de funcionário)
// têm em comum: tipos aceitos, estilos, faixas de aviso, preview do arquivo,
// o botão que esconde o <input type="file"> e o abrir-anexo-em-nova-aba.
import { useRef } from 'react'
import api from '../../services/api'

export const TIPOS = 'application/pdf,image/jpeg,image/png'
export const TAMANHO_MAX = 10 * 1024 * 1024

export const inputStyle = { display: 'block', width: '100%', padding: 8, marginTop: 4, borderRadius: 'var(--radius-sm)', border: '1px solid var(--color-border)', background: 'var(--color-bg)', color: 'var(--color-text)', boxSizing: 'border-box' }
export const botaoPrimario = { padding: '8px 20px', background: 'var(--color-accent-solid)', color: 'var(--color-on-accent)', border: 'none', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }
export const botaoSecundario = { padding: '8px 20px', background: 'transparent', color: 'var(--color-text)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', cursor: 'pointer' }

export function formatMoeda(valor) {
  return Number(valor || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
}
export function formatData(data) {
  return data ? new Date(data).toLocaleDateString('pt-BR', { timeZone: 'UTC' }) : '—'
}

export function Faixa({ tipo = 'aviso', children }) {
  const cor = tipo === 'erro' ? 'var(--color-danger)' : 'var(--color-warning)'
  return (
    <div style={{ borderLeft: `4px solid ${cor}`, background: 'var(--color-bg)', padding: '8px 12px', borderRadius: 'var(--radius-sm)', fontSize: 13, marginBottom: 10 }}>
      {children}
    </div>
  )
}

export function validarArquivo(arquivo) {
  if (!arquivo) return 'Escolha um arquivo.'
  if (!TIPOS.split(',').includes(arquivo.type)) return 'Só PDF, JPG ou PNG.'
  if (arquivo.size > TAMANHO_MAX) return 'Arquivo maior que 10 MB.'
  return null
}

export function mensagemDe(err, padrao) {
  return err?.response?.data?.error || padrao
}

export function PreviewArquivo({ url, tipo, alt = 'Arquivo enviado' }) {
  if (!url) return null
  return (
    <div style={{ position: 'sticky', top: 16, alignSelf: 'start' }}>
      {tipo === 'application/pdf'
        ? <object data={url} type="application/pdf" style={{ width: '100%', height: 420, border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)' }}>
            <a href={url} target="_blank" rel="noopener">Abrir o PDF</a>
          </object>
        : <img src={url} alt={alt} style={{ maxWidth: '100%', borderRadius: 'var(--radius-sm)', border: '1px solid var(--color-border)' }} />}
    </div>
  )
}

/** Botão que abre o seletor de arquivo e entrega o File escolhido. */
export function BotaoSubirArquivo({ rotulo, rotuloLendo = 'Lendo…', lendo = false, disabled = false, onArquivo, style }) {
  const input = useRef(null)
  return (
    <>
      <input ref={input} type="file" accept={TIPOS} style={{ display: 'none' }}
        onChange={e => { const f = e.target.files[0]; e.target.value = ''; if (f) onArquivo(f) }} />
      <button type="button" onClick={() => input.current.click()} disabled={disabled || lendo} style={{ ...botaoSecundario, ...style }}>
        {lendo ? rotuloLendo : rotulo}
      </button>
    </>
  )
}

/** Abre o anexo em nova aba. A aba abre no clique (depois do await o Safari bloqueia) e recebe a URL assinada. */
export async function abrirAnexo(caminho) {
  const janela = window.open('', '_blank')
  if (janela) janela.opener = null
  try {
    const r = await api.get(caminho)
    if (janela) janela.location.replace(r.data.url)
    else window.open(r.data.url, '_blank', 'noopener')
  } catch (err) {
    janela?.close()
    alert(err.response?.data?.error || 'Não consegui abrir o anexo.')
  }
}
```

- [ ] **Step 7: `UploadPedidoCompra.jsx` passa a importar do comum**

1. Trocar as linhas 9–43 (de `const TIPOS` até o fim de `mensagemDe`) por:
```jsx
import { TIPOS, inputStyle, botaoPrimario, botaoSecundario, formatMoeda, formatData, Faixa, validarArquivo, mensagemDe, PreviewArquivo } from './upload/comum'
```
(logo abaixo do `import ItensPedidoForm ...`). Os `useRef` dos dois inputs **ficam** como estão.
2. Trocar o bloco do preview (linhas 313–323, `{previewUrl && (<div style={{ position: 'sticky' ...`) por `<PreviewArquivo url={previewUrl} tipo={previewTipo} alt="Pedido enviado" />`.

- [ ] **Step 8: `Fornecedores.jsx` usa `abrirAnexo` do comum**

Apagar a função `abrirAnexo` (linhas 852–864) e acrescentar `import { abrirAnexo } from '../components/upload/comum'` nos imports. As chamadas nas linhas 1027 e 1102 continuam iguais.

- [ ] **Step 9: Rodar tudo e buildar**

```bash
NODE_OPTIONS=--no-experimental-webstorage npx vitest run && npm run build
```
Expected: tudo verde; build sem erro.

- [ ] **Step 10: Commit**

```bash
git add src/lib/meses.js src/lib/meses.test.js src/components/upload/comum.jsx src/components/upload/comum.test.jsx src/components/UploadPedidoCompra.jsx src/pages/Fornecedores.jsx
git commit -m "refactor: parte comum do upload sai para components/upload/comum e helpers de mês para lib/meses

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9 (frontend): `UploadDocumentoFuncionario.jsx` — o cartão de conferência

**Files:**
- Create: `src/components/UploadDocumentoFuncionario.jsx`, `src/components/UploadDocumentoFuncionario.test.jsx`

**Interfaces:**
- Produces: `export default function UploadDocumentoFuncionario({ funcionario, tipo, competencia, arquivo, existente, onSalvo, onCancelar })`
  - `funcionario`: `{id, nome, cnpj, valor_combinado}`
  - `tipo`: `'pagamento' | 'das_boleto' | 'das_comprovante' | 'nf'`
  - `competencia`: `'AAAA-MM'` (mês aberto na página)
  - `arquivo`: `File` (sobe e lê) ou `null` (lançar à mão)
  - `existente`: a linha `das`/`nf` do mês aberto, ou `null`
  - `onSalvo(competenciaSalva: 'AAAA-MM')`, `onCancelar()`
- Consumes: `POST /api/funcionarios/<id>/ler/{pix|das|nf}`, `POST /api/funcionarios/<id>/lancamentos`, `PUT /api/funcionarios/<id>/lancamentos/<lid>` (Tasks 5–6); tudo do `comum.jsx`; `rotuloMes` de `lib/meses`.

Comportamento (do spec, seção "Cartão de conferência"):
- Rota de leitura por tipo: `pagamento → pix`, `das_boleto → das`, `das_comprovante → pix`, `nf → nf`.
- Campos: `pagamento` → competência, valor, pago em; `das_boleto` → competência, valor, vencimento; `das_comprovante` → valor, pago em (competência fixa = mês aberto, mostrada como texto); `nf` → competência, nº da nota, valor (opcional).
- Pré-preenchimento: `pagamento` sem leitura → `valor_combinado`, pago em = hoje; `das_comprovante` → valor do `existente`, pago em = hoje; `das_boleto`/`nf` à mão → valores do `existente` se houver.
- Faixas: `leitura_falhou`; `aviso`; `pagamento_existente` (vermelha); `cnpj_confere === false` (amarela); competência lida ≠ mês aberto (amarela, campo já vem com a lida); `competencia_inferida` (amarela); DAS/NF já existe na competência escolhida (amarela, botão vira "Substituir" e salva com `PUT`); `das_comprovante` diz se vai marcar o DAS existente como pago ou lançar o DAS já pago.
- 409 com `existente_id` no `POST` → faixa com botão "Substituir" (faz `PUT` em `existente_id`).
- Corpo do `POST/PUT` por tipo:
  - `pagamento`: `{tipo:'pagamento', competencia, valor, pago_em, id_transacao, arquivo_token}`
  - `das_boleto`: `{tipo:'das', competencia, valor, vencimento, boleto_token}`
  - `das_comprovante`: `{tipo:'das', competencia, valor, pago_em, id_transacao, comprovante_token}`
  - `nf`: `{tipo:'nf', competencia, numero_nf, valor|null, arquivo_token}`
  (`*_token` vem de `leitura.arquivo_token`; `id_transacao` de `leitura.id_transacao`.)

- [ ] **Step 1: Testes**

```jsx
// src/components/UploadDocumentoFuncionario.test.jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import UploadDocumentoFuncionario from './UploadDocumentoFuncionario'

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }))
import api from '../services/api'

const JOSIE = { id: 'f-1', nome: 'Josie', cnpj: '12345678000195', valor_combinado: 2500 }
const pdf = () => new File(['%PDF'], 'doc.pdf', { type: 'application/pdf' })

beforeEach(() => {
  api.post.mockReset(); api.put.mockReset()
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:x')
  globalThis.URL.revokeObjectURL = vi.fn()
})

describe('UploadDocumentoFuncionario', () => {
  it('DAS lido de outro mês: avisa e já traz a competência do documento', async () => {
    api.post.mockResolvedValueOnce({ data: {
      leitura_falhou: false, arquivo_token: 'pendentes/' + 'a'.repeat(32) + '.pdf', aviso: null,
      valor: 75.9, vencimento: '2026-10-20', competencia: '2026-08-01', cnpj: '12345678000195', nome: 'JOSIE',
      cnpj_confere: true, das_existente: null,
    } })
    const onSalvo = vi.fn()
    render(<UploadDocumentoFuncionario funcionario={JOSIE} tipo="das_boleto" competencia="2026-09" arquivo={pdf()} existente={null} onSalvo={onSalvo} onCancelar={() => {}} />)
    await waitFor(() => expect(screen.getByText(/O documento é de Agosto 2026/)).toBeInTheDocument())
    expect(api.post.mock.calls[0][0]).toBe('/api/funcionarios/f-1/ler/das')
    expect(screen.getByLabelText(/Competência/).value).toBe('2026-08')
    expect(screen.getByLabelText(/Vencimento/).value).toBe('2026-10-20')

    api.post.mockResolvedValueOnce({ data: { id: 'l-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(onSalvo).toHaveBeenCalledWith('2026-08'))
    expect(api.post.mock.calls[1][0]).toBe('/api/funcionarios/f-1/lancamentos')
    expect(api.post.mock.calls[1][1]).toEqual({ tipo: 'das', competencia: '2026-08', valor: 75.9, vencimento: '2026-10-20', boleto_token: 'pendentes/' + 'a'.repeat(32) + '.pdf' })
  })

  it('pagamento à mão vem com o valor combinado e não chama a leitura', () => {
    render(<UploadDocumentoFuncionario funcionario={JOSIE} tipo="pagamento" competencia="2026-09" arquivo={null} existente={null} onSalvo={() => {}} onCancelar={() => {}} />)
    expect(api.post).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/Valor/).value).toBe('2500')
    expect(screen.getByLabelText(/Pago em/).value).not.toBe('')
  })

  it('NF de outro CNPJ mostra a faixa amarela', async () => {
    api.post.mockResolvedValueOnce({ data: {
      leitura_falhou: false, arquivo_token: null, aviso: null, numero: '123', valor: 2500, data_emissao: '2026-09-05',
      competencia: '2026-09-01', competencia_inferida: true, cnpj_prestador: '99999999000199', nome_prestador: 'OUTRA',
      cnpj_confere: false, nf_existente: null,
    } })
    render(<UploadDocumentoFuncionario funcionario={JOSIE} tipo="nf" competencia="2026-09" arquivo={pdf()} existente={null} onSalvo={() => {}} onCancelar={() => {}} />)
    await waitFor(() => expect(screen.getByText(/CNPJ/)).toBeInTheDocument())
    expect(screen.getByText(/não diz o mês dos serviços/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Nº da nota/).value).toBe('123')
  })

  it('comprovante do DAS marca o DAS existente como pago com PUT', async () => {
    api.post.mockResolvedValueOnce({ data: {
      leitura_falhou: false, arquivo_token: 'pendentes/' + 'b'.repeat(32) + '.png', aviso: null,
      valor: 75.9, data_pagamento: '2026-10-18', destinatario: 'SIMPLES NACIONAL', id_transacao: 'E81x', pagamento_existente: null,
    } })
    api.put.mockResolvedValueOnce({ data: { id: 'l-2' } })
    const onSalvo = vi.fn()
    const das = { id: 'l-2', tipo: 'das', competencia: '2026-09-01', valor: 75.9, vencimento: '2026-10-20', pago_em: null }
    render(<UploadDocumentoFuncionario funcionario={JOSIE} tipo="das_comprovante" competencia="2026-09" arquivo={new File(['x'], 'pix.png', { type: 'image/png' })} existente={das} onSalvo={onSalvo} onCancelar={() => {}} />)
    await waitFor(() => expect(screen.getByText(/Vai marcar o DAS de Setembro 2026 como pago/)).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(onSalvo).toHaveBeenCalledWith('2026-09'))
    expect(api.put.mock.calls[0][0]).toBe('/api/funcionarios/f-1/lancamentos/l-2')
    expect(api.put.mock.calls[0][1]).toEqual({ tipo: 'das', competencia: '2026-09', valor: 75.9, pago_em: '2026-10-18', id_transacao: 'E81x', comprovante_token: 'pendentes/' + 'b'.repeat(32) + '.png' })
  })

  it('Pix já lançado mostra a faixa vermelha', async () => {
    api.post.mockResolvedValueOnce({ data: {
      leitura_falhou: false, arquivo_token: null, aviso: null, valor: 2500, data_pagamento: '2026-09-15',
      destinatario: 'JOSIE', id_transacao: 'E81y', pagamento_existente: { id: 'x', data_pagamento: '2026-09-15', valor: 2500, onde: 'fornecedor' },
    } })
    render(<UploadDocumentoFuncionario funcionario={JOSIE} tipo="pagamento" competencia="2026-09" arquivo={pdf()} existente={null} onSalvo={() => {}} onCancelar={() => {}} />)
    await waitFor(() => expect(screen.getByText(/já foi lançado em 15\/09\/2026/)).toBeInTheDocument())
  })

  it('409 com existente_id oferece Substituir', async () => {
    api.post.mockResolvedValueOnce({ data: { leitura_falhou: true, arquivo_token: null, aviso: null, numero: null, valor: null, data_emissao: null, competencia: null, competencia_inferida: false, cnpj_prestador: null, nome_prestador: null, cnpj_confere: null, nf_existente: null } })
    render(<UploadDocumentoFuncionario funcionario={JOSIE} tipo="nf" competencia="2026-09" arquivo={pdf()} existente={null} onSalvo={() => {}} onCancelar={() => {}} />)
    await waitFor(() => expect(screen.getByText(/Não consegui ler/)).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/Nº da nota/), { target: { value: '77' } })
    api.post.mockRejectedValueOnce({ response: { status: 409, data: { error: 'Já existe NF em 09/2026', existente_id: 'l-9' } } })
    fireEvent.click(screen.getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Substituir' })).toBeInTheDocument())
    api.put.mockResolvedValueOnce({ data: { id: 'l-9' } })
    fireEvent.click(screen.getByRole('button', { name: 'Substituir' }))
    await waitFor(() => expect(api.put.mock.calls[0][0]).toBe('/api/funcionarios/f-1/lancamentos/l-9'))
  })
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/components/UploadDocumentoFuncionario`
Expected: falha ao resolver o componente.

- [ ] **Step 3: Implementar**

```jsx
// src/components/UploadDocumentoFuncionario.jsx
// Cartão de conferência de um documento de funcionário: sobe o arquivo (ou
// abre vazio, "à mão") → a IA lê → ela confere → Salvar. A IA só lê; gravar
// é sempre no botão. Um componente para os quatro casos (pagamento, boleto do
// DAS, comprovante do DAS, NF) porque a mecânica é a mesma; o que muda são os
// campos e o corpo que vai para a API.
import { useEffect, useState } from 'react'
import api from '../services/api'
import { Faixa, PreviewArquivo, inputStyle, botaoPrimario, botaoSecundario, formatMoeda, formatData, mensagemDe, validarArquivo } from './upload/comum'
import { rotuloMes } from '../lib/meses'

const ROTA_LEITURA = { pagamento: 'pix', das_boleto: 'das', das_comprovante: 'pix', nf: 'nf' }
const TITULO = { pagamento: 'Pagamento', das_boleto: 'Boleto do DAS', das_comprovante: 'Comprovante do DAS', nf: 'Nota fiscal' }
const ROTULO_EXISTENTE = { das_boleto: 'DAS', nf: 'NF' }

const hojeISO = () => new Date().toISOString().slice(0, 10)
const mesDeISO = d => (d ? String(d).slice(0, 7) : null)

export default function UploadDocumentoFuncionario({ funcionario, tipo, competencia, arquivo, existente, onSalvo, onCancelar }) {
  const [etapa, setEtapa] = useState(arquivo ? 'lendo' : 'conferindo')
  const [leitura, setLeitura] = useState(null)
  const [erro, setErro] = useState(null)
  const [conflito, setConflito] = useState(null)   // { id, mensagem } — 409 do POST
  const [previewUrl] = useState(() => (arquivo ? URL.createObjectURL(arquivo) : null))

  const [comp, setComp] = useState(competencia)
  const [valor, setValor] = useState(() => {
    if (tipo === 'pagamento') return funcionario.valor_combinado ?? ''
    if (existente?.valor != null) return existente.valor
    return ''
  })
  const [data, setData] = useState(hojeISO())          // pago_em
  const [vencimento, setVencimento] = useState(existente?.vencimento?.slice(0, 10) || '')
  const [numeroNf, setNumeroNf] = useState(existente?.numero_nf || '')

  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])

  useEffect(() => {
    if (!arquivo) return
    const invalido = validarArquivo(arquivo)
    if (invalido) { setErro(invalido); setEtapa('conferindo'); return }
    const form = new FormData()
    form.append('arquivo', arquivo)
    api.post(`/api/funcionarios/${funcionario.id}/ler/${ROTA_LEITURA[tipo]}`, form)
      .then(r => { setLeitura(r.data); preencher(r.data) })
      .catch(err => setErro(mensagemDe(err, 'Não consegui ler o arquivo.')))
      .finally(() => setEtapa('conferindo'))
  }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  function preencher(lido) {
    if (lido.leitura_falhou) return
    if (tipo === 'pagamento' || tipo === 'das_comprovante') {
      if (lido.valor != null) setValor(lido.valor)
      if (lido.data_pagamento) setData(lido.data_pagamento)
    }
    if (tipo === 'das_boleto') {
      if (lido.valor != null) setValor(lido.valor)
      setVencimento(lido.vencimento || '')
      if (lido.competencia) setComp(mesDeISO(lido.competencia))
    }
    if (tipo === 'nf') {
      setNumeroNf(lido.numero || '')
      if (lido.valor != null) setValor(lido.valor)
      if (lido.competencia) setComp(mesDeISO(lido.competencia))
    }
  }

  // DAS/NF que já existe na competência escolhida: o do mês aberto (vem da
  // página) ou o do mês lido (vem do /ler). Outro mês qualquer → só o 409 diz.
  const compLida = mesDeISO(leitura?.competencia)
  const jaExiste = tipo === 'das_comprovante' ? null
    : comp === competencia ? existente
    : comp === compLida ? (leitura?.das_existente || leitura?.nf_existente || null)
    : null
  const alvoPut = conflito?.id || (tipo === 'das_comprovante' ? existente?.id : jaExiste?.id) || null

  function corpo() {
    const token = leitura?.arquivo_token || null
    if (tipo === 'pagamento') return { tipo: 'pagamento', competencia: comp, valor: parseFloat(valor), pago_em: data, id_transacao: leitura?.id_transacao || null, arquivo_token: token }
    if (tipo === 'das_boleto') return { tipo: 'das', competencia: comp, valor: parseFloat(valor), vencimento: vencimento || null, boleto_token: token }
    if (tipo === 'das_comprovante') return { tipo: 'das', competencia, valor: parseFloat(valor), pago_em: data, id_transacao: leitura?.id_transacao || null, comprovante_token: token }
    return { tipo: 'nf', competencia: comp, numero_nf: numeroNf || null, valor: valor === '' ? null : parseFloat(valor), arquivo_token: token }
  }

  function validar() {
    if (tipo !== 'das_comprovante' && !comp) return 'Informe a competência.'
    if (tipo !== 'nf' && !(parseFloat(valor) > 0)) return 'Informe o valor.'
    if ((tipo === 'pagamento' || tipo === 'das_comprovante') && !data) return 'Informe a data do pagamento.'
    if (tipo === 'nf' && !numeroNf && !leitura?.arquivo_token) return 'Informe o número da nota ou suba o arquivo.'
    return null
  }

  async function salvar(e, forcarPut = null) {
    e?.preventDefault()
    const invalido = validar()
    if (invalido) { setErro(invalido); return }
    setErro(null); setEtapa('salvando')
    const alvo = forcarPut || alvoPut
    const compSalva = tipo === 'das_comprovante' ? competencia : comp
    try {
      if (alvo) await api.put(`/api/funcionarios/${funcionario.id}/lancamentos/${alvo}`, corpo())
      else await api.post(`/api/funcionarios/${funcionario.id}/lancamentos`, corpo())
      onSalvo(compSalva)
    } catch (err) {
      const r = err.response
      if (r?.status === 409 && r.data?.existente_id && tipo !== 'pagamento') setConflito({ id: r.data.existente_id, mensagem: r.data.error })
      else setErro(mensagemDe(err, 'Não consegui salvar.'))
      setEtapa('conferindo')
    }
  }

  const campoCompetencia = (
    <label style={{ fontSize: 12 }}>Competência (mês do serviço)<br />
      <input type="month" value={comp} onChange={e => setComp(e.target.value)} style={{ ...inputStyle, width: 170 }} />
    </label>
  )
  const campoValor = (
    <label style={{ fontSize: 12 }}>Valor (R$)<br />
      <input type="number" step="0.01" min="0" value={valor} onChange={e => setValor(e.target.value)} style={{ ...inputStyle, width: 140 }} />
    </label>
  )
  const campoPagoEm = (
    <label style={{ fontSize: 12 }}>Pago em<br />
      <input type="date" value={data} onChange={e => setData(e.target.value)} style={{ ...inputStyle, width: 160 }} />
    </label>
  )

  return (
    <form onSubmit={salvar} style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: 24, marginBottom: 24, display: 'grid', gridTemplateColumns: previewUrl ? '1fr 320px' : '1fr', gap: 24 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ fontWeight: 600, fontSize: 15 }}>
          {TITULO[tipo]} · {funcionario.nome}
          {tipo === 'das_comprovante' && <span style={{ fontWeight: 400, color: 'var(--color-text-muted)' }}> · {rotuloMes(competencia)}</span>}
        </div>

        {etapa === 'lendo' && <p style={{ margin: 0, fontSize: 13, color: 'var(--color-text-muted)' }}>Lendo o arquivo…</p>}
        {leitura?.leitura_falhou && <Faixa>Não consegui ler esse arquivo. Preencha à mão.</Faixa>}
        {leitura?.aviso && <Faixa>{leitura.aviso}</Faixa>}
        {leitura?.pagamento_existente && (
          <Faixa tipo="erro">Esse comprovante já foi lançado em {formatData(leitura.pagamento_existente.data_pagamento)} ({formatMoeda(leitura.pagamento_existente.valor)}) — em {leitura.pagamento_existente.onde}.</Faixa>
        )}
        {leitura && leitura.cnpj_confere === false && (
          <Faixa>O CNPJ do documento ({leitura.cnpj || leitura.cnpj_prestador}) não é o de {funcionario.nome} ({funcionario.cnpj}). É dessa pessoa mesmo?</Faixa>
        )}
        {compLida && compLida !== competencia && tipo !== 'das_comprovante' && (
          <Faixa>O documento é de {rotuloMes(compLida)}, e o mês aberto é {rotuloMes(competencia)}. A competência abaixo já veio com a do documento — confira.</Faixa>
        )}
        {leitura?.competencia_inferida && <Faixa>A nota não diz o mês dos serviços; usei o mês da emissão ({formatData(leitura.data_emissao)}).</Faixa>}
        {jaExiste && (
          <Faixa>Já existe {ROTULO_EXISTENTE[tipo]} em {rotuloMes(comp)}{jaExiste.valor != null ? ` (${formatMoeda(jaExiste.valor)})` : ''}. Salvar substitui.</Faixa>
        )}
        {tipo === 'das_comprovante' && (
          <p style={{ margin: 0, fontSize: 13, color: 'var(--color-text-muted)' }}>
            {existente ? `Vai marcar o DAS de ${rotuloMes(competencia)} como pago.` : `Não há boleto do DAS em ${rotuloMes(competencia)} — vai lançar o DAS já pago.`}
          </p>
        )}
        {conflito && (
          <Faixa>{conflito.mensagem}. <button type="button" onClick={() => salvar(null, conflito.id)} style={{ ...botaoSecundario, padding: '4px 10px', fontSize: 12, marginLeft: 8 }}>Substituir</button></Faixa>
        )}

        {leitura && !leitura.leitura_falhou && (tipo === 'pagamento' || tipo === 'das_comprovante') && (
          <p style={{ margin: 0, fontSize: 14 }}>
            Pix de <strong>{formatMoeda(leitura.valor)}</strong> em <strong>{formatData(leitura.data_pagamento)}</strong>
            {leitura.destinatario && <> para <strong>{leitura.destinatario}</strong></>}
          </p>
        )}

        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          {tipo === 'pagamento' && <>{campoCompetencia}{campoValor}{campoPagoEm}</>}
          {tipo === 'das_boleto' && <>{campoCompetencia}{campoValor}
            <label style={{ fontSize: 12 }}>Vencimento<br />
              <input type="date" value={vencimento} onChange={e => setVencimento(e.target.value)} style={{ ...inputStyle, width: 160 }} />
            </label></>}
          {tipo === 'das_comprovante' && <>{campoValor}{campoPagoEm}</>}
          {tipo === 'nf' && <>{campoCompetencia}
            <label style={{ fontSize: 12 }}>Nº da nota<br />
              <input value={numeroNf} onChange={e => setNumeroNf(e.target.value)} style={{ ...inputStyle, width: 160 }} />
            </label>{campoValor}</>}
        </div>

        {erro && <p style={{ color: 'var(--color-danger)', margin: 0, fontSize: 13 }}>{erro}</p>}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" onClick={onCancelar} disabled={etapa === 'salvando'} style={botaoSecundario}>Cancelar</button>
          <button type="submit" disabled={etapa !== 'conferindo'} style={botaoPrimario}>
            {etapa === 'salvando' ? 'Salvando…' : jaExiste ? 'Substituir' : 'Salvar'}
          </button>
        </div>
      </div>

      <PreviewArquivo url={previewUrl} tipo={arquivo?.type} alt={TITULO[tipo]} />
    </form>
  )
}
```

Cuidado no teste 6 ("409 oferece Substituir"): depois do 409 há dois botões "Substituir"? Não — `jaExiste` é null (sem existente e sem leitura de competência), então o botão de submit continua "Salvar" e só a faixa tem "Substituir". Se em algum caso os dois aparecerem, o `getByRole` falha por ambiguidade: nesse caso o botão da faixa deve dizer "Substituir o existente".

- [ ] **Step 4: Rodar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/components/UploadDocumentoFuncionario`
Expected: 6 passando.

- [ ] **Step 5: Commit**

```bash
git add src/components/UploadDocumentoFuncionario.jsx src/components/UploadDocumentoFuncionario.test.jsx
git commit -m "feat: cartão de conferência dos documentos do funcionário (Pix, DAS, NF)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 10 (frontend): `BlocoLancamentoFuncionario.jsx` — um bloco (Pagamento / DAS / NF)

**Files:**
- Create: `src/components/BlocoLancamentoFuncionario.jsx`, `src/components/BlocoLancamentoFuncionario.test.jsx`

**Interfaces:**
- Produces: `export default function BlocoLancamentoFuncionario({ tipo, linhas, podeEditar, onAbrir, onMudou, onAbrirAnexo })` e `export function descricaoDaLinha(linha) -> string`.
  - `tipo`: `'pagamento' | 'das' | 'nf'`; `linhas`: as linhas desse tipo no mês aberto (já filtradas pela página).
  - `onAbrir(tipoCartao, arquivo|null)` — `tipoCartao` ∈ `'pagamento' | 'das_boleto' | 'das_comprovante' | 'nf'` (os tipos do `UploadDocumentoFuncionario`).
  - `onMudou()` — depois de editar/apagar (a página recarrega).
  - `onAbrirAnexo(linha, qual)` — `qual` ∈ `'arquivo' | 'boleto' | 'comprovante'`.
- Consumes: `PUT/DELETE /api/funcionarios/<fid>/lancamentos/<lid>` (linha traz `funcionario_id`); `comum.jsx`; `mesDe` de `lib/meses`.

Comportamento:
- Título por tipo (`PAGAMENTO`, `DAS`, `NF`); vazio → "— nada ainda —".
- `descricaoDaLinha`: pagamento → `R$ 2.500,00 · pago em 05/10/2026`; das → `R$ 75,90 · vence 20/10/2026 · pago em 18/10/2026` ou `· em aberto`; nf → `NF nº 123 · R$ 2.500,00` (sem número: `NF sem número`).
- Links 📎: pagamento/nf → `arquivo_path`; das → `📎 boleto` (`boleto_path`) e `📎 comprovante` (`comprovante_path`).
- Botões (só `podeEditar`):
  - pagamento: `📎 Subir comprovante do Pix` → `onAbrir('pagamento', f)`; `+ lançar à mão` → `onAbrir('pagamento', null)`.
  - das sem linha: `📎 Subir boleto` → `('das_boleto', f)`; `📎 Subir comprovante` → `('das_comprovante', f)`; `+ lançar à mão` → `('das_boleto', null)`.
  - das em aberto: `📎 Subir boleto` só se não tem `boleto_path`; `📎 Subir comprovante`; `✓ marcar pago à mão` → `('das_comprovante', null)`.
  - das pago: `📎 Subir boleto` se falta `boleto_path`; `📎 Subir comprovante` se falta `comprovante_path`.
  - nf sem linha: `📎 Subir NF` → `('nf', f)`; `+ lançar à mão` → `('nf', null)`. Com linha sem arquivo: `📎 Anexar o arquivo da NF` → `('nf', f)`.
- ✏️ abre edição inline (campos por tipo: pagamento → competência, valor, pago em; das → competência, valor, vencimento, pago em (vazio = em aberto); nf → competência, nº, valor) → `PUT` com `{competencia, valor, vencimento, pago_em, numero_nf}` só os que o tipo tem → `onMudou()`. 🗑️ → `confirm('Apagar este lançamento?')` → `DELETE` → `onMudou()`.

- [ ] **Step 1: Testes**

```jsx
// src/components/BlocoLancamentoFuncionario.test.jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import BlocoLancamentoFuncionario, { descricaoDaLinha } from './BlocoLancamentoFuncionario'

vi.mock('../services/api', () => ({ default: { get: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
import api from '../services/api'

const DAS_ABERTO = { id: 'l-2', funcionario_id: 'f-1', tipo: 'das', competencia: '2026-09-01', valor: 75.9, vencimento: '2026-10-20', pago_em: null, boleto_path: 'x', comprovante_path: null }

beforeEach(() => { api.put.mockReset(); api.delete.mockReset() })

describe('descricaoDaLinha', () => {
  it('descreve cada tipo', () => {
    expect(descricaoDaLinha({ tipo: 'pagamento', valor: 2500, pago_em: '2026-10-05' })).toBe('R$ 2.500,00 · pago em 05/10/2026')
    expect(descricaoDaLinha(DAS_ABERTO)).toBe('R$ 75,90 · vence 20/10/2026 · em aberto')
    expect(descricaoDaLinha({ ...DAS_ABERTO, pago_em: '2026-10-18' })).toBe('R$ 75,90 · vence 20/10/2026 · pago em 18/10/2026')
    expect(descricaoDaLinha({ tipo: 'nf', numero_nf: '123', valor: 2500 })).toBe('NF nº 123 · R$ 2.500,00')
    expect(descricaoDaLinha({ tipo: 'nf', numero_nf: null, valor: null })).toBe('NF sem número')
  })
})

describe('BlocoLancamentoFuncionario', () => {
  it('vazio diz que não tem nada e oferece subir ou lançar à mão', () => {
    const onAbrir = vi.fn()
    render(<BlocoLancamentoFuncionario tipo="nf" linhas={[]} podeEditar onAbrir={onAbrir} onMudou={() => {}} onAbrirAnexo={() => {}} />)
    expect(screen.getByText('— nada ainda —')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '+ lançar à mão' }))
    expect(onAbrir).toHaveBeenCalledWith('nf', null)
  })

  it('DAS em aberto: mostra "em aberto", só comprovante e marcar pago (boleto já tem)', () => {
    const onAbrir = vi.fn()
    render(<BlocoLancamentoFuncionario tipo="das" linhas={[DAS_ABERTO]} podeEditar onAbrir={onAbrir} onMudou={() => {}} onAbrirAnexo={() => {}} />)
    expect(screen.getByText(/em aberto/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '📎 Subir boleto' })).toBeNull()
    expect(screen.getByRole('button', { name: '📎 Subir comprovante' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '✓ marcar pago à mão' }))
    expect(onAbrir).toHaveBeenCalledWith('das_comprovante', null)
    expect(screen.getByRole('button', { name: '📎 boleto' })).toBeInTheDocument()
  })

  it('viewer não vê botões de gravar', () => {
    render(<BlocoLancamentoFuncionario tipo="pagamento" linhas={[]} podeEditar={false} onAbrir={() => {}} onMudou={() => {}} onAbrirAnexo={() => {}} />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('editar manda PUT só com os campos do tipo e avisa a página', async () => {
    api.put.mockResolvedValue({ data: {} })
    const onMudou = vi.fn()
    render(<BlocoLancamentoFuncionario tipo="das" linhas={[DAS_ABERTO]} podeEditar onAbrir={() => {}} onMudou={onMudou} onAbrirAnexo={() => {}} />)
    fireEvent.click(screen.getByTitle('Editar'))
    fireEvent.change(screen.getByLabelText(/Pago em/), { target: { value: '2026-10-18' } })
    fireEvent.click(screen.getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(onMudou).toHaveBeenCalled())
    expect(api.put.mock.calls[0][0]).toBe('/api/funcionarios/f-1/lancamentos/l-2')
    expect(api.put.mock.calls[0][1]).toEqual({ competencia: '2026-09', valor: 75.9, vencimento: '2026-10-20', pago_em: '2026-10-18' })
  })

  it('apagar pede confirmação e manda DELETE', async () => {
    api.delete.mockResolvedValue({})
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const onMudou = vi.fn()
    render(<BlocoLancamentoFuncionario tipo="das" linhas={[DAS_ABERTO]} podeEditar onAbrir={() => {}} onMudou={onMudou} onAbrirAnexo={() => {}} />)
    fireEvent.click(screen.getByTitle('Apagar'))
    await waitFor(() => expect(onMudou).toHaveBeenCalled())
    expect(api.delete).toHaveBeenCalledWith('/api/funcionarios/f-1/lancamentos/l-2')
  })
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/components/BlocoLancamentoFuncionario`
Expected: falha ao resolver o componente.

- [ ] **Step 3: Implementar**

```jsx
// src/components/BlocoLancamentoFuncionario.jsx
// Um dos três blocos do mês de um funcionário: Pagamento, DAS ou NF.
// Mostra as linhas daquele tipo, os botões de subir/lançar e o ✏️/🗑️ de cada
// linha. Quem abre o cartão de conferência é a página (onAbrir).
import { useState } from 'react'
import api from '../services/api'
import { BotaoSubirArquivo, formatMoeda, formatData, inputStyle, botaoSecundario, botaoPrimario, mensagemDe } from './upload/comum'
import { mesDe } from '../lib/meses'

const TITULO = { pagamento: 'PAGAMENTO', das: 'DAS', nf: 'NF' }
const botaoMini = { ...botaoSecundario, padding: '6px 12px', fontSize: 12 }
const botaoIcone = { background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 14, opacity: 0.7, padding: 4 }

export function descricaoDaLinha(linha) {
  if (linha.tipo === 'pagamento') return `${formatMoeda(linha.valor)} · pago em ${formatData(linha.pago_em)}`
  if (linha.tipo === 'das') {
    const partes = [formatMoeda(linha.valor)]
    if (linha.vencimento) partes.push(`vence ${formatData(linha.vencimento)}`)
    partes.push(linha.pago_em ? `pago em ${formatData(linha.pago_em)}` : 'em aberto')
    return partes.join(' · ')
  }
  const partes = [linha.numero_nf ? `NF nº ${linha.numero_nf}` : 'NF sem número']
  if (linha.valor != null) partes.push(formatMoeda(linha.valor))
  return partes.join(' · ')
}

function Anexos({ linha, onAbrirAnexo }) {
  const link = (qual, rotulo) => (
    <button type="button" key={qual} onClick={() => onAbrirAnexo(linha, qual)} title="Abrir em nova aba"
      style={{ ...botaoIcone, fontSize: 12, textDecoration: 'underline', color: 'var(--color-text-muted)' }}>{rotulo}</button>
  )
  if (linha.tipo === 'das') return <>{linha.boleto_path && link('boleto', '📎 boleto')}{linha.comprovante_path && link('comprovante', '📎 comprovante')}</>
  return linha.arquivo_path ? link('arquivo', '📎') : null
}

function LinhaLancamento({ linha, podeEditar, onMudou, onAbrirAnexo }) {
  const [editando, setEditando] = useState(false)
  const [comp, setComp] = useState(mesDe(linha.competencia) || '')
  const [valor, setValor] = useState(linha.valor ?? '')
  const [pagoEm, setPagoEm] = useState(linha.pago_em ? String(linha.pago_em).slice(0, 10) : '')
  const [vencimento, setVencimento] = useState(linha.vencimento ? String(linha.vencimento).slice(0, 10) : '')
  const [numeroNf, setNumeroNf] = useState(linha.numero_nf || '')
  const [erro, setErro] = useState(null)
  const [salvando, setSalvando] = useState(false)

  async function salvar(e) {
    e.preventDefault()
    setErro(null); setSalvando(true)
    const corpo = { competencia: comp, valor: valor === '' ? null : parseFloat(valor) }
    if (linha.tipo === 'pagamento') corpo.pago_em = pagoEm
    if (linha.tipo === 'das') { corpo.vencimento = vencimento || null; corpo.pago_em = pagoEm || null }
    if (linha.tipo === 'nf') corpo.numero_nf = numeroNf || null
    try {
      await api.put(`/api/funcionarios/${linha.funcionario_id}/lancamentos/${linha.id}`, corpo)
      setEditando(false)
      onMudou()
    } catch (err) {
      setErro(mensagemDe(err, 'Não consegui salvar.'))
    } finally {
      setSalvando(false)
    }
  }

  async function apagar() {
    if (!confirm('Apagar este lançamento?')) return
    try {
      await api.delete(`/api/funcionarios/${linha.funcionario_id}/lancamentos/${linha.id}`)
      onMudou()
    } catch (err) {
      alert(mensagemDe(err, 'Não consegui apagar.'))
    }
  }

  if (editando) {
    return (
      <form onSubmit={salvar} style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', padding: '8px 0' }}>
        <label style={{ fontSize: 12 }}>Competência<br /><input type="month" value={comp} onChange={e => setComp(e.target.value)} style={{ ...inputStyle, width: 150 }} /></label>
        {linha.tipo === 'nf' && <label style={{ fontSize: 12 }}>Nº da nota<br /><input value={numeroNf} onChange={e => setNumeroNf(e.target.value)} style={{ ...inputStyle, width: 130 }} /></label>}
        <label style={{ fontSize: 12 }}>Valor (R$)<br /><input type="number" step="0.01" min="0" value={valor} onChange={e => setValor(e.target.value)} style={{ ...inputStyle, width: 120 }} /></label>
        {linha.tipo === 'das' && <label style={{ fontSize: 12 }}>Vencimento<br /><input type="date" value={vencimento} onChange={e => setVencimento(e.target.value)} style={{ ...inputStyle, width: 150 }} /></label>}
        {linha.tipo !== 'nf' && <label style={{ fontSize: 12 }}>Pago em{linha.tipo === 'das' ? ' (vazio = em aberto)' : ''}<br /><input type="date" value={pagoEm} onChange={e => setPagoEm(e.target.value)} style={{ ...inputStyle, width: 150 }} /></label>}
        <button type="submit" disabled={salvando} style={{ ...botaoPrimario, padding: '8px 14px' }}>Salvar</button>
        <button type="button" onClick={() => setEditando(false)} style={botaoMini}>Cancelar</button>
        {erro && <span style={{ color: 'var(--color-danger)', fontSize: 12 }}>{erro}</span>}
      </form>
    )
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', fontSize: 14 }}>
      <span>{descricaoDaLinha(linha)}</span>
      <Anexos linha={linha} onAbrirAnexo={onAbrirAnexo} />
      {podeEditar && (
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 2 }}>
          <button type="button" onClick={() => setEditando(true)} title="Editar" style={botaoIcone}>✏️</button>
          <button type="button" onClick={apagar} title="Apagar" style={botaoIcone}>🗑️</button>
        </span>
      )}
    </div>
  )
}

export default function BlocoLancamentoFuncionario({ tipo, linhas, podeEditar, onAbrir, onMudou, onAbrirAnexo }) {
  const [lendo, setLendo] = useState(false)
  const subir = (rotulo, tipoCartao) => (
    <BotaoSubirArquivo key={tipoCartao} rotulo={rotulo} lendo={lendo} style={{ padding: '6px 12px', fontSize: 12 }}
      onArquivo={f => { setLendo(false); onAbrir(tipoCartao, f) }} />
  )
  const aMao = (rotulo, tipoCartao) => (
    <button type="button" key={rotulo} onClick={() => onAbrir(tipoCartao, null)} style={botaoMini}>{rotulo}</button>
  )

  let botoes = []
  if (podeEditar) {
    if (tipo === 'pagamento') botoes = [subir('📎 Subir comprovante do Pix', 'pagamento'), aMao('+ lançar à mão', 'pagamento')]
    if (tipo === 'das') {
      const das = linhas[0]
      if (!das) botoes = [subir('📎 Subir boleto', 'das_boleto'), subir('📎 Subir comprovante', 'das_comprovante'), aMao('+ lançar à mão', 'das_boleto')]
      else if (!das.pago_em) botoes = [!das.boleto_path && subir('📎 Subir boleto', 'das_boleto'), subir('📎 Subir comprovante', 'das_comprovante'), aMao('✓ marcar pago à mão', 'das_comprovante')]
      else botoes = [!das.boleto_path && subir('📎 Subir boleto', 'das_boleto'), !das.comprovante_path && subir('📎 Subir comprovante', 'das_comprovante')]
    }
    if (tipo === 'nf') {
      const nf = linhas[0]
      if (!nf) botoes = [subir('📎 Subir NF', 'nf'), aMao('+ lançar à mão', 'nf')]
      else if (!nf.arquivo_path) botoes = [subir('📎 Anexar o arquivo da NF', 'nf')]
    }
  }

  return (
    <section style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: '12px 16px', marginBottom: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span style={{ fontWeight: 700, fontSize: 12, letterSpacing: '0.06em', minWidth: 90, color: 'var(--color-text-muted)' }}>{TITULO[tipo]}</span>
        <div style={{ flex: 1, minWidth: 220 }}>
          {linhas.length === 0
            ? <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>— nada ainda —</span>
            : linhas.map(l => <LinhaLancamento key={l.id} linha={l} podeEditar={podeEditar} onMudou={onMudou} onAbrirAnexo={onAbrirAnexo} />)}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>{botoes.filter(Boolean)}</div>
      </div>
    </section>
  )
}
```

- [ ] **Step 4: Rodar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/components/BlocoLancamentoFuncionario`
Expected: 6 passando. (Se `getByLabelText(/Pago em/)` achar dois elementos, o rótulo do DAS é "Pago em (vazio = em aberto)" — só um `<label>` por bloco de edição; não há duplicidade.)

- [ ] **Step 5: Commit**

```bash
git add src/components/BlocoLancamentoFuncionario.jsx src/components/BlocoLancamentoFuncionario.test.jsx
git commit -m "feat: bloco de lançamento do funcionário (pagamento, DAS, NF) com edição inline

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 11 (frontend): Página `Funcionarios.jsx`, menu e rota

**Files:**
- Create: `src/pages/Funcionarios.jsx`, `src/pages/Funcionarios.test.jsx`
- Modify: `src/components/Layout.jsx` (linha 21: item novo depois de Fornecedores)
- Modify: `src/App.jsx` (import + rota `/funcionarios`)

**Interfaces:**
- Produces: `export default function Funcionarios()`; `export function resumoTexto(resumo) -> string` (`'falta: DAS, NF'`, `'DAS em aberto, vence 20/10'`, `'mês completo ✓'`, combinados com `' · '`).
- Consumes: `GET /api/funcionarios`, `POST/PUT/DELETE /api/funcionarios[/<id>]`, `GET /api/funcionarios/<id>/lancamentos?competencia=`, `GET /api/funcionarios/<id>/meses?ate=&n=12`, `GET .../lancamentos/<lid>/anexo?qual=`; `BlocoLancamentoFuncionario`, `UploadDocumentoFuncionario`, `comum.jsx`, `lib/meses`, `Layout`, `PaginaHeader`, `useAuth`.

- [ ] **Step 1: Testes**

```jsx
// src/pages/Funcionarios.test.jsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Funcionarios, { resumoTexto } from './Funcionarios'

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
vi.mock('../components/Layout', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ finRole: 'fin_admin' }) }))
import api from '../services/api'

const JOSIE = { id: 'f-1', nome: 'Josie', cnpj: '12345678000195', valor_combinado: 2500, ativo: true,
  mes_atual: { competencia: '2026-09-01', falta: ['nf'], das_em_aberto: true, das_vencimento: '2026-10-20', completo: false, total_pago: 2500, das_valor: 75.9, nf_valor: null, nf_numero: null } }

function respostas({ funcionarios = [], linhas = [], meses = [] }) {
  api.get.mockImplementation(url => {
    if (url === '/api/funcionarios') return Promise.resolve({ data: funcionarios })
    if (url.includes('/lancamentos?competencia=')) return Promise.resolve({ data: linhas })
    if (url.includes('/meses?')) return Promise.resolve({ data: meses })
    throw new Error('URL não prevista: ' + url)
  })
}

beforeEach(() => { api.get.mockReset() })

describe('resumoTexto', () => {
  it('diz o que falta, o DAS em aberto ou que o mês está completo', () => {
    expect(resumoTexto({ falta: ['das', 'nf'], das_em_aberto: false })).toBe('falta: DAS, NF')
    expect(resumoTexto({ falta: [], das_em_aberto: true, das_vencimento: '2026-10-20' })).toBe('DAS em aberto, vence 20/10')
    expect(resumoTexto({ falta: ['nf'], das_em_aberto: true, das_vencimento: null })).toBe('falta: NF · DAS em aberto')
    expect(resumoTexto({ falta: [], das_em_aberto: false, completo: true })).toBe('mês completo ✓')
    expect(resumoTexto(null)).toBe('')
  })
})

describe('Funcionários', () => {
  it('monta sem ninguém cadastrado', async () => {
    respostas({})
    render(<MemoryRouter><Funcionarios /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText(/Nenhum funcionário/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: '+ Novo funcionário' })).toBeInTheDocument()
  })

  it('cartão mostra o resumo do mês atual e, ao clicar, abre os três blocos e a lista de meses', async () => {
    respostas({
      funcionarios: [JOSIE],
      linhas: [{ id: 'l-1', funcionario_id: 'f-1', tipo: 'pagamento', competencia: '2026-09-01', valor: 2500, pago_em: '2026-09-15' },
               { id: 'l-2', funcionario_id: 'f-1', tipo: 'das', competencia: '2026-09-01', valor: 75.9, vencimento: '2026-10-20', pago_em: null }],
      meses: [{ competencia: '2026-09-01', falta: ['nf'], das_em_aberto: true, das_vencimento: '2026-10-20', total_pago: 2500 },
              { competencia: '2026-08-01', falta: [], das_em_aberto: false, completo: true, total_pago: 2500 }],
    })
    render(<MemoryRouter><Funcionarios /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('falta: NF · DAS em aberto, vence 20/10')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Josie'))
    await waitFor(() => expect(screen.getByText('PAGAMENTO')).toBeInTheDocument())
    expect(screen.getByText('DAS')).toBeInTheDocument()
    expect(screen.getByText('NF')).toBeInTheDocument()
    expect(screen.getByText(/R\$\s?75,90 · vence 20\/10\/2026 · em aberto/)).toBeInTheDocument()
    expect(screen.getByText('Agosto 2026')).toBeInTheDocument()
    expect(screen.getByText('mês completo ✓')).toBeInTheDocument()
  })

  it('trocar o mês recarrega os lançamentos daquela competência', async () => {
    respostas({ funcionarios: [JOSIE] })
    render(<MemoryRouter><Funcionarios /></MemoryRouter>)
    await waitFor(() => screen.getByText('Josie'))
    fireEvent.click(screen.getByText('Josie'))
    await waitFor(() => screen.getByText('PAGAMENTO'))
    fireEvent.change(screen.getByLabelText(/Mês/), { target: { value: '2026-08' } })
    await waitFor(() => expect(api.get).toHaveBeenCalledWith('/api/funcionarios/f-1/lancamentos?competencia=2026-08'))
  })
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/Funcionarios`
Expected: falha ao resolver a página.

- [ ] **Step 3: Implementar a página**

```jsx
// src/pages/Funcionarios.jsx
// Funcionários (prestadores MEI): cartões com o nome, e dentro de cada um o
// mês de competência com três blocos — pagamento, DAS e NF. Não copia
// Fornecedores.jsx: a página é a cola entre blocos pequenos.
import { useEffect, useState, useCallback } from 'react'
import Layout from '../components/Layout'
import PaginaHeader from '../components/PaginaHeader'
import api from '../services/api'
import { useAuth } from '../contexts/AuthContext'
import BlocoLancamentoFuncionario from '../components/BlocoLancamentoFuncionario'
import UploadDocumentoFuncionario from '../components/UploadDocumentoFuncionario'
import { abrirAnexo, botaoPrimario, botaoSecundario, inputStyle, formatData, formatMoeda, mensagemDe } from '../components/upload/comum'
import { mesAtual, mesDe, rotuloMes } from '../lib/meses'

const ROTULO_FALTA = { pagamento: 'pagamento', das: 'DAS', nf: 'NF' }

/** "falta: DAS, NF" / "DAS em aberto, vence 20/10" / "mês completo ✓" */
export function resumoTexto(r) {
  if (!r) return ''
  const partes = []
  if (r.falta?.length) partes.push(`falta: ${r.falta.map(t => ROTULO_FALTA[t] || t).join(', ')}`)
  if (r.das_em_aberto) partes.push(`DAS em aberto${r.das_vencimento ? `, vence ${formatData(r.das_vencimento).slice(0, 5)}` : ''}`)
  return partes.length ? partes.join(' · ') : 'mês completo ✓'
}

const modalOverlay = { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'grid', placeItems: 'center', zIndex: 50 }
const modalBox = { background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: 24, width: 360, maxWidth: '92vw' }

function ModalFuncionario({ titulo, inicial, onSalvar, onFechar }) {
  const [nome, setNome] = useState(inicial?.nome || '')
  const [cnpj, setCnpj] = useState(inicial?.cnpj || '')
  const [valor, setValor] = useState(inicial?.valor_combinado ?? '')
  const [erro, setErro] = useState(null)
  const [salvando, setSalvando] = useState(false)
  async function submit(e) {
    e.preventDefault()
    setErro(null); setSalvando(true)
    try {
      await onSalvar({ nome, cnpj: cnpj || null, valor_combinado: valor === '' ? null : parseFloat(valor) })
      onFechar()
    } catch (err) {
      setErro(mensagemDe(err, 'Não consegui salvar.'))
    } finally {
      setSalvando(false)
    }
  }
  return (
    <div style={modalOverlay} onClick={onFechar}>
      <form style={modalBox} onClick={e => e.stopPropagation()} onSubmit={submit}>
        <h2 style={{ margin: '0 0 12px', fontSize: 17 }}>{titulo}</h2>
        <label style={{ fontSize: 12 }}>Nome<br /><input required value={nome} onChange={e => setNome(e.target.value)} style={inputStyle} /></label>
        <label style={{ fontSize: 12, display: 'block', marginTop: 10 }}>CNPJ do MEI (opcional)<br /><input value={cnpj} onChange={e => setCnpj(e.target.value)} style={inputStyle} placeholder="só números" /></label>
        <label style={{ fontSize: 12, display: 'block', marginTop: 10 }}>Valor combinado por mês (opcional)<br /><input type="number" step="0.01" min="0" value={valor} onChange={e => setValor(e.target.value)} style={inputStyle} /></label>
        {erro && <p style={{ color: 'var(--color-danger)', fontSize: 13 }}>{erro}</p>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
          <button type="button" onClick={onFechar} style={botaoSecundario}>Cancelar</button>
          <button type="submit" disabled={salvando} style={botaoPrimario}>{salvando ? 'Salvando…' : 'Salvar'}</button>
        </div>
      </form>
    </div>
  )
}

export default function Funcionarios() {
  const { finRole } = useAuth()
  const podeEditar = finRole === 'fin_admin'
  const [funcionarios, setFuncionarios] = useState(null)
  const [sel, setSel] = useState(null)
  const [mes, setMes] = useState(mesAtual())
  const [linhas, setLinhas] = useState([])
  const [meses, setMeses] = useState([])
  const [cartao, setCartao] = useState(null)      // { tipo, arquivo } com o cartão de conferência aberto
  const [modalNovo, setModalNovo] = useState(false)
  const [modalEditar, setModalEditar] = useState(null)
  const [erro, setErro] = useState(null)

  const carregarFuncionarios = useCallback(async () => {
    try {
      const r = await api.get('/api/funcionarios')
      setFuncionarios(r.data)
      setSel(s => (s ? r.data.find(f => f.id === s.id) || null : s))
    } catch {
      setErro('Não consegui carregar os funcionários.')
    }
  }, [])

  const carregarMes = useCallback(async (f, m) => {
    try {
      const [rLinhas, rMeses] = await Promise.all([
        api.get(`/api/funcionarios/${f.id}/lancamentos?competencia=${m}`),
        api.get(`/api/funcionarios/${f.id}/meses?ate=${m}&n=12`),
      ])
      setLinhas(rLinhas.data)
      setMeses(rMeses.data)
    } catch {
      setErro('Não consegui carregar o mês.')
    }
  }, [])

  useEffect(() => { carregarFuncionarios() }, [carregarFuncionarios])
  useEffect(() => { if (sel) carregarMes(sel, mes) }, [sel?.id, mes])  // eslint-disable-line react-hooks/exhaustive-deps

  function recarregar() {
    carregarFuncionarios()
    if (sel) carregarMes(sel, mes)
  }

  async function excluir(f) {
    if (!confirm(`Desativar "${f.nome}"? Os lançamentos ficam guardados.`)) return
    try {
      await api.delete(`/api/funcionarios/${f.id}`)
      if (sel?.id === f.id) setSel(null)
      carregarFuncionarios()
    } catch (err) {
      alert(mensagemDe(err, 'Não consegui desativar.'))
    }
  }

  const doTipo = t => linhas.filter(l => l.tipo === t)
  const resumoDoMes = meses.find(m => mesDe(m.competencia) === mes)
  const existenteParaCartao = cartao
    ? (cartao.tipo === 'nf' ? doTipo('nf')[0] : cartao.tipo.startsWith('das') ? doTipo('das')[0] : null) || null
    : null

  return (
    <Layout>
      <PaginaHeader
        titulo="Funcionários"
        subtitulo="Por pessoa e por mês de competência: o pagamento, o DAS e a NF. Pagamento e DAS pagos saem da sobra na Caixa da Semana."
        acao={podeEditar && <button onClick={() => setModalNovo(true)} style={botaoPrimario}>+ Novo funcionário</button>}
      />

      {erro && <p style={{ color: 'var(--color-danger)' }}>{erro}</p>}

      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 28 }}>
        {funcionarios && funcionarios.length === 0 && (
          <p style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>Nenhum funcionário cadastrado ainda.</p>
        )}
        {(funcionarios || []).map(f => {
          const ativo = sel?.id === f.id
          return (
            <div key={f.id} style={{ position: 'relative', cursor: 'pointer', minWidth: 180, padding: '14px 18px', borderRadius: 'var(--radius-md)', border: '1px solid var(--color-border)', background: ativo ? 'var(--color-accent-solid)' : 'var(--color-surface)', color: ativo ? 'var(--color-on-accent)' : 'var(--color-text)' }}>
              <div onClick={() => { setSel(f); setCartao(null) }}>
                <div style={{ fontWeight: 700, fontSize: 16 }}>{f.nome}</div>
                <div style={{ fontSize: 12, opacity: 0.85, marginTop: 4 }}>{rotuloMes(mesDe(f.mes_atual?.competencia))}: {resumoTexto(f.mes_atual)}</div>
              </div>
              {podeEditar && (
                <div style={{ position: 'absolute', top: 6, right: 6, display: 'flex', gap: 2 }}>
                  <button onClick={e => { e.stopPropagation(); setModalEditar(f) }} title="Editar funcionário" style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 13, opacity: 0.7, color: 'inherit' }}>✏️</button>
                  <button onClick={e => { e.stopPropagation(); excluir(f) }} title="Desativar funcionário" style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 13, opacity: 0.7, color: 'inherit' }}>🗑️</button>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {sel && (
        <>
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: 16, flexWrap: 'wrap', marginBottom: 14 }}>
            <h2 style={{ margin: 0, fontSize: 19 }}>{sel.nome} · {rotuloMes(mes)}
              <span style={{ fontWeight: 400, fontSize: 14, color: 'var(--color-text-muted)', marginLeft: 10 }}>{resumoTexto(resumoDoMes)}</span>
            </h2>
            <label style={{ fontSize: 12, color: 'var(--color-text-muted)', marginLeft: 'auto' }}>Mês<br />
              <input type="month" value={mes} onChange={e => { setMes(e.target.value); setCartao(null) }} style={{ ...inputStyle, width: 170 }} />
            </label>
          </div>

          {cartao && (
            <UploadDocumentoFuncionario
              key={`${cartao.tipo}-${mes}`}
              funcionario={sel} tipo={cartao.tipo} competencia={mes} arquivo={cartao.arquivo} existente={existenteParaCartao}
              onSalvo={compSalva => { setCartao(null); if (compSalva !== mes) setMes(compSalva); else recarregar() }}
              onCancelar={() => setCartao(null)}
            />
          )}

          {['pagamento', 'das', 'nf'].map(t => (
            <BlocoLancamentoFuncionario key={t} tipo={t} linhas={doTipo(t)} podeEditar={podeEditar}
              onAbrir={(tipoCartao, arquivo) => setCartao({ tipo: tipoCartao, arquivo })}
              onMudou={recarregar}
              onAbrirAnexo={(l, qual) => abrirAnexo(`/api/funcionarios/${sel.id}/lancamentos/${l.id}/anexo?qual=${qual}`)} />
          ))}

          <section style={{ marginTop: 24 }}>
            <h3 style={{ fontSize: 14, color: 'var(--color-text-muted)', margin: '0 0 8px' }}>Últimos 12 meses</h3>
            <div style={{ display: 'grid', gap: 4 }}>
              {meses.map(m => {
                const chave = mesDe(m.competencia)
                return (
                  <button key={chave} type="button" onClick={() => { setMes(chave); setCartao(null) }}
                    style={{ display: 'flex', justifyContent: 'space-between', gap: 12, textAlign: 'left', padding: '8px 12px', fontSize: 13, background: chave === mes ? 'var(--color-bg)' : 'transparent', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', color: 'var(--color-text)', cursor: 'pointer' }}>
                    <span>{rotuloMes(chave)}</span>
                    <span style={{ color: 'var(--color-text-muted)' }}>{m.total_pago > 0 ? `${formatMoeda(m.total_pago)} · ` : ''}{resumoTexto(m)}</span>
                  </button>
                )
              })}
            </div>
          </section>
        </>
      )}

      {modalNovo && <ModalFuncionario titulo="Novo funcionário" onFechar={() => setModalNovo(false)}
        onSalvar={async d => { await api.post('/api/funcionarios', d); carregarFuncionarios() }} />}
      {modalEditar && <ModalFuncionario titulo="Editar funcionário" inicial={modalEditar} onFechar={() => setModalEditar(null)}
        onSalvar={async d => { await api.put(`/api/funcionarios/${modalEditar.id}`, d); carregarFuncionarios() }} />}
    </Layout>
  )
}
```

- [ ] **Step 4: Menu e rota**

`src/components/Layout.jsx`, no array `nav` (linha 21), depois de Fornecedores:
```js
  { path: '/funcionarios', label: 'Funcionários' },
```
`src/App.jsx`: `import Funcionarios from './pages/Funcionarios'` e, depois da rota de fornecedores:
```jsx
          <Route path="/funcionarios" element={<ProtectedRoute><Funcionarios /></ProtectedRoute>} />
```

- [ ] **Step 5: Rodar tudo e buildar**

```bash
NODE_OPTIONS=--no-experimental-webstorage npx vitest run && npm run build
```
Expected: tudo verde (o teste da gaveta do Layout continua passando com o item a mais); build ok.

- [ ] **Step 6: Commit**

```bash
git add src/pages/Funcionarios.jsx src/pages/Funcionarios.test.jsx src/components/Layout.jsx src/App.jsx
git commit -m "feat: aba Funcionários — cadastro, mês de competência e os três blocos

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 12 (frontend): Caixa da Semana — "Pago a funcionários" sai da sobra

**Files:**
- Modify: `src/pages/CaixaSemana.jsx` (estado + carga ~linhas 498–512; totais ~618–629; `dias` ~637–651; notas ~900–901; cards ~728–747; seção de lista ~1053–1079)
- Modify: `src/pages/CaixaSemana.test.jsx` (`respostas()` + 2 testes)
- Modify: `docs/regras-caixa-semana.md`

**Interfaces:**
- Consumes: `GET /api/funcionarios/pagamentos?de&ate` (Task 4) — itens `{id, tipo:'pagamento'|'das', valor, data_pagamento, funcionario_nome}`; `pagamentosDaSemana()` (já existe e serve igual: usa `data_pagamento`, `valor`, `id`).
- Produces: `totalPagoFuncionarios`; card "Pago a funcionários"; `sobra` com a linha nova; `dias[i].saiFuncionarios`; seção "Pagamentos a funcionários" com "Descontar / Não descontar" no mesmo `ajustes_pagamento`.

- [ ] **Step 1: Testes**

Em `src/pages/CaixaSemana.test.jsx`:
1. Em `respostas({ ... })` acrescentar o parâmetro `pagosFuncionarios = []` e, **antes** da linha `if (url.startsWith('/api/fornecedores/pagamentos?'))`, a linha:
```js
    if (url.startsWith('/api/funcionarios/pagamentos?')) return Promise.resolve({ data: pagosFuncionarios })
```
2. Dentro de `describe('A conta da semana (ditada em 17/09/2026)')`, acrescentar:

```jsx
  it('pagamento e DAS de funcionário saem da sobra, e o card diz de quem é', async () => {
    respostas({
      planejamento: { ...SEM_PLANEJAMENTO, agenda: { [ymd(seg)]: 1000 }, updated_at: hoje.toUTCString() },
      pagosFuncionarios: [
        { id: 'u1', tipo: 'pagamento', funcionario_nome: 'Josie', valor: 300, data_pagamento: ymd(hoje), created_at: hoje.toUTCString() },
        { id: 'u2', tipo: 'das', funcionario_nome: 'Josie', valor: 75.9, data_pagamento: ymd(hoje), created_at: hoje.toUTCString() },
      ],
    })
    montar()
    await waitFor(() => expect(screen.getByText('Pago a funcionários')).toBeInTheDocument())
    expect(screen.getByText(/Josie R\$\s?300,00 · DAS Josie R\$\s?75,90/)).toBeInTheDocument()
    expect(screen.getByText(/− R\$\s?375,90 a funcionários/)).toBeInTheDocument()
  })

  it('a Caixa abre mesmo se o endpoint de funcionários falhar', async () => {
    respostas({ planejamento: { ...SEM_PLANEJAMENTO, agenda: { [ymd(seg)]: 1000 }, updated_at: hoje.toUTCString() } })
    const original = api.get.getMockImplementation()
    api.get.mockImplementation(url => url.startsWith('/api/funcionarios/') ? Promise.reject(new Error('404')) : original(url))
    montar()
    await waitFor(() => expect(screen.getByText('Pago a funcionários')).toBeInTheDocument())
    expect(screen.getByText('Nenhum pagamento na semana')).toBeInTheDocument()
  })
```
(`seg`, `hoje`, `ymd` já existem nesse `describe`.) Se "Nenhum pagamento na semana" aparecer duas vezes (fornecedor e funcionários), usar `getAllByText(...).length === 2`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `NODE_OPTIONS=--no-experimental-webstorage npx vitest run src/pages/CaixaSemana.test.jsx`
Expected: os 2 novos falham ("Pago a funcionários" não existe).

- [ ] **Step 3: Editar `CaixaSemana.jsx`**

1. Estado (junto de `const [pagamentos, setPagamentos]`):
```js
  const [pagosFuncionarios, setPagosFuncionarios] = useState(null)
```
2. Na carga, o `Promise.all` vira:
```js
        const [rContas, rFornecedores, rPagosSemana, rPagosFunc] = await Promise.all([
          api.get('/api/contas'),
          api.get('/api/fornecedores'),
          api.get(`/api/fornecedores/pagamentos?de=${iso(segunda)}&ate=${iso(domingo)}`),
          // Tolerante: se este endpoint falhar, a Caixa abre sem a linha, em
          // vez de cair inteira por causa da parte mais nova.
          api.get(`/api/funcionarios/pagamentos?de=${iso(segunda)}&ate=${iso(domingo)}`).catch(() => ({ data: [] })),
        ])
        if (!vivo) return
        setContas(rContas.data)
        setPagamentos(rPagosSemana.data)
        setPagosFuncionarios(rPagosFunc.data)
```
e `const carregando = !contas || !repasses || !flavia || !pagamentos || !pagosFuncionarios`.
3. Depois de `const totalPagoFornecedor = ...`:
```js
  // Funcionários: pagamento do mês e DAS pago saem da sobra igual (decisão
  // dela em 17/09/2026). O mesmo botão "Não descontar" vale — ids são UUID.
  const funcSemana = pagamentosDaSemana(pagosFuncionarios, segunda, domingo, ajustesPagamento)
  const funcDescontados = funcSemana.filter(p => !p.jaFora)
  const totalPagoFuncionarios = funcDescontados.reduce((s, p) => s + p.valor, 0)
  const nomeFuncionario = p => (p.tipo === 'das' ? `DAS ${p.funcionario_nome}` : p.funcionario_nome)
```
4. `const sobra = totalRepasse - totalBoletos - totalPagoFornecedor - totalPagoFuncionarios`
5. No `useMemo` de `dias`: depois de `const saiPagos = ...`:
```js
      const saiFuncionarios = funcDescontados.filter(p => iso(p.data) === iso(data))
```
somar no `sai` (`+ saiFuncionarios.reduce((s, p) => s + p.valor, 0)`), devolver `saiFuncionarios` no objeto, e acrescentar `pagosFuncionarios` na lista de deps.
6. Nas notas do dia a dia, depois da linha de `d.saiPagos.forEach(...)`:
```js
                    d.saiFuncionarios.forEach(p => notas.push(`− ${nomeFuncionario(p)} ${brl(p.valor)}`))
```
7. Card novo, logo depois do `<Indicador rotulo="Pago a fornecedor" ... />`:
```jsx
            <Indicador
              rotulo="Pago a funcionários"
              valor={totalPagoFuncionarios}
              tom="divida"
              composicao={funcDescontados.length
                ? funcDescontados.map(p => `${nomeFuncionario(p)} ${brl(p.valor)}`).join(' · ')
                : 'Nenhum pagamento na semana'}
            />
```
8. Na `composicao` do card "Sobra para comprar", depois de `${brl(totalPagoFornecedor)} pagos` inserir:
```js
                (totalPagoFuncionarios > 0 ? ` − ${brl(totalPagoFuncionarios)} a funcionários` : '') +
```
9. Seção nova, depois do `</SecaoCard>` de "Pagamentos a fornecedor":
```jsx
          <SecaoCard
            titulo="Pagamentos a funcionários"
            subtitulo="Pagamento do mês e DAS pagos nesta semana, lançados em Funcionários. Saem da sobra para comprar."
            total={brl(totalPagoFuncionarios)}
          >
            {funcSemana.length === 0 ? (
              <Vazio>Nenhum pagamento a funcionário nesta semana.</Vazio>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {funcSemana.map(p => (
                  <Linha key={p.id}
                         esquerda={nomeFuncionario(p)}
                         apoio={p.jaFora
                           ? `Pago em ${dia(iso(p.data))} · não descontado — sua escolha`
                           : `Pago em ${dia(iso(p.data))} · descontado da sobra`}
                         direita={brl(p.valor)}
                         extra={
                           <button type="button" style={{ ...botao, padding: '4px 9px', fontSize: 12 }}
                                   onClick={() => salvarAjuste({ ...ajustesPagamento, [p.id]: p.jaFora })}>
                             {p.jaFora ? 'Descontar da sobra' : 'Não descontar'}
                           </button>
                         } />
                ))}
              </div>
            )}
          </SecaoCard>
```
10. Atualizar o comentário de cabeçalho do arquivo e o do bloco "a conta" (linhas ~607–611) para citar a linha de funcionários: "entra − boletos − pago a fornecedor − pago a funcionários".

- [ ] **Step 4: Documentação**

Em `docs/regras-caixa-semana.md`, na seção "A conta", acrescentar a linha ao diagrama:
```
 − Pagamentos a funcionários    pagamento do mês e DAS pagos na semana
```
e, depois da seção "Boletos: ...", a seção:
```markdown
## Funcionários: pagamento e DAS saem da sobra

Decisão dela em 17/09/2026, ao criar a aba Funcionários: o que foi pago a
prestador (MEI) na semana — o pagamento dos serviços e o DAS, que a empresa
paga — **sai da sobra**, como linha própria. O DAS em aberto não sai de lugar
nenhum até ser pago. O mês de competência (o do serviço) é só organização da
aba; a Caixa desconta cada valor na semana em que foi pago.
```

- [ ] **Step 5: Rodar tudo e buildar**

```bash
NODE_OPTIONS=--no-experimental-webstorage npx vitest run && npm run build
```
Expected: tudo verde (os testes antigos do card de sobra continuam: a linha nova só aparece quando > 0).

- [ ] **Step 6: Commit**

```bash
git add src/pages/CaixaSemana.jsx src/pages/CaixaSemana.test.jsx docs/regras-caixa-semana.md
git commit -m "feat: Caixa da Semana desconta pagamento e DAS de funcionários da sobra

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 13: Subir, testar no ar com documento real e fechar

**Files:** nenhum (operação + smoke test); ao fim, `docs/superpowers/specs/2026-09-17-funcionarios-design.md` ganha a seção "Conferido no ar".

- [ ] **Step 1: Backend — merge e deploy (antes do frontend)**

```bash
cd /Users/macbookpro/Desktop/Claude/financeiro-backend
venv/bin/python -m pytest tests -q
git fetch origin && git merge-base --is-ancestor origin/main feat/funcionarios && echo "main não andou" || echo "ATENÇÃO: main andou — rebase antes"
git checkout main && git merge --ff-only feat/funcionarios && git push origin main
```
(Se o push der 403, `gh auth switch --user cibellycarvalho` e repetir.) Esperar ~40 s e conferir:
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://financeiro.cravelli.com.br/api/funcionarios
```
Expected: `401` (rota existe e está protegida). `404` = deploy ainda não subiu.

- [ ] **Step 2: Frontend — merge e deploy**

```bash
cd /Users/macbookpro/Desktop/Claude/financeiro-frontend
NODE_OPTIONS=--no-experimental-webstorage npx vitest run && npm run build
git fetch origin && git merge-base --is-ancestor origin/main feat/funcionarios && echo "main não andou" || echo "ATENÇÃO: main andou — rebase antes"
git checkout main && git merge --ff-only feat/funcionarios && git push origin main
```
Conferir o bundle:
```bash
js=$(curl -s https://financeiro.cravelli.com.br/ | grep -o 'assets/index-[A-Za-z0-9_-]*\.js' | head -1); curl -s "https://financeiro.cravelli.com.br/$js" | grep -c "Subir comprovante do Pix"
```
Expected: `1` (repetir após 20 s se der 0).

- [ ] **Step 3: Smoke test no ar** (no Chrome dela, logada; navegar antes de ler — a aba é compartilhada)

1. Menu → **Funcionários** → "+ Novo funcionário" → nome `Teste Claude`, CNPJ em branco, valor 100 → Salvar. Cartão aparece com "falta: pagamento, DAS, NF".
2. Clicar no cartão → mês atual → bloco PAGAMENTO → "📎 Subir comprovante do Pix" com um comprovante Sicredi **já lançado em fornecedor** (ex.: `~/Downloads/sicredi_1787532061.pdf`): tem que aparecer a faixa vermelha "já foi lançado … — em fornecedor". Cancelar.
3. Pedir a ela um **DAS real** (PDF) e uma **NF real** de um prestador: subir o DAS em `Teste Claude` → conferir valor, vencimento, competência lida (Período de Apuração), CNPJ (sem cadastro → sem faixa) → Salvar → linha "R$ … · vence … · em aberto" com 📎 boleto. Subir a NF → conferir número, valor, competência (faixa amarela se inferida) → Salvar.
4. "+ lançar à mão" no PAGAMENTO com valor 100 e data de hoje → Salvar → Caixa da Semana: card "Pago a funcionários" mostra `Teste Claude R$ 100,00` e a sobra caiu 100. Clicar "Não descontar" → sobra volta.
5. Clicar cada 📎 e ver abrir em nova aba (URL assinada).
6. Lista "Últimos 12 meses" mostra o mês atual com o resumo; trocar o mês e voltar.
7. Apagar os lançamentos de teste (🗑️) e desativar `Teste Claude`. Conferir na Caixa que a linha sumiu.

Se a leitura do DAS ou da NF vier errada, anotar o caso, ajustar `INSTRUCAO_DAS`/`INSTRUCAO_NF` em `leitura_documento.py` e repetir — sem mexer no resto.

- [ ] **Step 4: Registrar o resultado**

Acrescentar ao fim do spec a seção `## Conferido no ar (DD/MM/2026)`: modelo usado, o que leu certo/errado no DAS e na NF, tempo de leitura. Commit `docs:` na `main` do backend.

- [ ] **Step 5: Memória**

Criar `project_funcionarios_aba.md` na memória do Claude: aba no ar desde DD/MM/2026; competência = mês do serviço, escolhida ao anexar; empresa paga o DAS; pagamento + DAS pago saem da sobra; um DAS/NF por mês; Pix conferido nas duas tabelas. Linha nova em `MEMORY.md`.

---

## Self-review (feito ao escrever)

**Cobertura do spec:** migração (T1); helpers em `anexos.py` com prefixo (T2); leitores DAS/NF com normalização, CNPJ, `competencia_inferida`, fixtures sintéticas (T3); rotas de cadastro, resumo do mês, `/pagamentos` para a Caixa (T4); `/meses`, `/lancamentos` GET/POST/PUT/DELETE com regras por tipo, 409 com `existente_id`, E2E nas duas tabelas, anexo na transação, `/anexo?qual=` (T5); `/ler/pix|das|nf` com `cnpj_confere` e `*_existente` (T6); migração aplicada (T7); `comum.jsx` + `meses.js` (T8); cartão de conferência com todas as faixas da tabela "Quando dá errado" — tamanho/tipo (`validarArquivo`), leitura falhou, anexo não guardado, Pix já usado, CNPJ ≠, competência ≠ mês aberto, DAS/NF já existe → Substituir, Storage ao mover → 500 com mensagem (T9); blocos com ✏️/🗑️/📎 e botões por estado (T10); página com cartões, cadastro, seletor de competência, cabeçalho "falta: …", lista de 12 meses, menu e rota (T11); Caixa: card, sobra, dia a dia, lista com "Não descontar", docs (T12); deploy backend antes do frontend e smoke test com DAS/NF reais (T13). Fora do escopo (aviso de DAS a vencer, relatório do contador, alias) continua fora.

**Placeholders:** nenhum "TBD"; todo passo de código tem o código. A migração não tem teste local (não há Postgres) — a conferência é a T7.

**Consistência de nomes:** `anexos.destino_anexo(prefixo, pasta, registro_id, token)` (T2) usado em T5 como `destino_anexo(f"funcionarios/{fid}", pasta, f"{tipo}{sufixo}-{id}", token)` → `funcionarios/<fid>/2026-09/das-boleto-l-2.pdf` (bate com os testes de T5). `url_anexo(tabela, coluna_dono, dono_id, registro_id, coluna_arquivo)` igual em T2 e T5. `_pix_ja_lancado`/`_um_por_mes` definidos em T5 e usados em T6; `_funcionario`, `_linha`, `_resumo`, `_hoje`, `_competencia` definidos em T4 e usados em T5/T6. Campos de resposta dos `/ler` (T6) são os que o cartão (T9) lê: `arquivo_token`, `leitura_falhou`, `aviso`, `pagamento_existente{data_pagamento,valor,onde}`, `cnpj_confere`, `competencia`, `competencia_inferida`, `das_existente`/`nf_existente`, `numero`, `vencimento`, `data_pagamento`, `id_transacao`. Tipos de cartão `pagamento|das_boleto|das_comprovante|nf` iguais em T9, T10 e T11. `resumo` do backend (T4: `falta`, `das_em_aberto`, `das_vencimento`, `completo`, `total_pago`, …) é o que `resumoTexto` (T11) lê. Endpoint `/api/funcionarios/pagamentos` devolve `data_pagamento`/`valor`/`id`/`tipo`/`funcionario_nome`, que `pagamentosDaSemana` e o card (T12) usam.
