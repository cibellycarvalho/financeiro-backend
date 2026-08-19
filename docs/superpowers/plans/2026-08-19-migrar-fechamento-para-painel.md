# Migração do Fechamento e Lucro Real para o Painel Financeiro — Plano de Implementação

> **Para quem executa:** use `superpowers:subagent-driven-development` (recomendado) ou
> `superpowers:executing-plans` para implementar tarefa a tarefa. Os passos usam
> checkbox (`- [ ]`) para acompanhamento.

**Objetivo:** mover a tela de Fechamento (com suas rotas) e a tela de Lucro Real do CRM
para o Painel Financeiro, sem que nenhum número mude de valor e sem janela de
indisponibilidade.

**Arquitetura:** os dois sistemas já compartilham o mesmo banco Supabase e o mesmo login
(JWT ES256 do mesmo projeto), então nenhum dado se move. O CRUD de fechamento — que só
depende do banco — passa para o backend financeiro. O cálculo do Lucro Real fica no CRM,
porque depende da integração com o Mercado Livre; só a tela migra e passa a chamar o CRM
de lá, via CORS.

**Stack:** Flask + psycopg2 (backend financeiro, helpers `db.query`/`db.execute`),
React + Vite (frontend financeiro), pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-migrar-fechamento-para-painel-design.md`

## Restrições globais

- **A trava por loja não pode ser afrouxada em nenhum momento.** Usuário não-admin só
  lê e grava dados da própria `conta_ml`, mesmo passando `conta_ml` na query string.
  Esta é a única fronteira de segurança da migração; qualquer tarefa que a toque tem
  teste antes de código.
- **`conta_ml` vem dos metadados do usuário no Supabase** (`user_metadata.conta_ml`),
  a mesma fonte que o CRM usa. Não criar segunda fonte de verdade.
- **`fin_role` continua sendo do Painel** (quem administra o financeiro) e não se
  mistura com "de qual loja" — são perguntas diferentes.
- **Backend financeiro acessa banco por `db.query(sql, params)` e `db.execute(sql, params)`**,
  não por `conn.cursor()` como o CRM. Todo código portado precisa ser traduzido para
  esses helpers.
- **Nenhuma tela sai do ar durante a migração.** O CRM só deixa de servir Fechamento e
  Lucro Real na última tarefa.
- Nomes de arquivo de migração seguem `AAAAMMDD_HHMM_nome.sql` (convenção adotada em
  19/08 para evitar colisão entre sessões paralelas).

---

## Estrutura de arquivos

**Criar:**
- `financeiro-backend/contas_ml.py` — resolução de `conta_ml` e a trava por loja. Um
  arquivo só para isso porque é a fronteira de segurança: fácil de achar, de revisar e
  de testar isolado.
- `financeiro-backend/routes/fechamento.py` — CRUD de compras, fretes, montagem, despesas.
- `financeiro-backend/routes/estoque_mensal.py` — estoque mensal e contagem de galpão.
- `financeiro-backend/tests/test_contas_ml.py` — testes da trava.
- `financeiro-backend/tests/test_fechamento.py` — testes das rotas portadas.
- `financeiro-frontend/src/pages/Fechamento.jsx` — tela portada.
- `financeiro-frontend/src/pages/LucroReal.jsx` — tela portada, consumindo o CRM.

**Modificar:**
- `financeiro-backend/auth.py` — `verify_jwt` passa a devolver `conta_ml` e `is_admin`.
- `financeiro-backend/app.py` — registrar os dois blueprints novos.
- `financeiro-frontend/src/App.jsx` — rotas novas.
- `ml-seller-api/app.py` — CORS liberando o domínio do Painel.
- `ml-seller-app/src/App.jsx` e `src/components/Sidebar.jsx` — remover as telas e
  redirecionar.

---

### Task 1: `conta_ml` no contexto do usuário do Painel

**Files:**
- Create: `financeiro-backend/contas_ml.py`
- Create: `financeiro-backend/tests/test_contas_ml.py`
- Modify: `financeiro-backend/auth.py:16-31` (função `verify_jwt`)

**Interfaces:**
- Consome: nada.
- Produz: `contas_ml.conta_do_request()` → `str`; levanta `contas_ml.SemConta` quando o
  usuário não tem loja nos metadados. `auth.verify_jwt` passa a incluir as chaves
  `conta_ml` (str | None) e `is_admin` (bool) no dict devolvido.

- [ ] **Step 1: Escrever o teste que falha**

```python
# financeiro-backend/tests/test_contas_ml.py
import pytest
from unittest.mock import patch
from flask import Flask, g
import contas_ml


def _app_com_usuario(user):
    app = Flask(__name__)

    @app.route("/x", methods=["GET", "POST"])
    def x():
        g.user = user
        try:
            return {"conta": contas_ml.conta_do_request()}
        except contas_ml.SemConta:
            return {"erro": "sem conta"}, 400

    return app.test_client()


ADMIN = {"user_id": "u1", "email": "a@b.c", "fin_role": "fin_admin",
         "conta_ml": "YUSO", "is_admin": True}
COMUM = {"user_id": "u2", "email": "d@e.f", "fin_role": "fin_viewer",
         "conta_ml": "M12", "is_admin": False}


def test_admin_pode_escolher_a_loja_pela_query():
    c = _app_com_usuario(ADMIN)
    assert c.get("/x?conta_ml=LOCITECH").get_json()["conta"] == "LOCITECH"


def test_nao_admin_fica_travado_na_propria_loja():
    """A fronteira de segurança da migração: passar conta_ml na query NÃO pode
    permitir gravar na loja de outro."""
    c = _app_com_usuario(COMUM)
    assert c.get("/x?conta_ml=YUSO").get_json()["conta"] == "M12"


def test_nao_admin_travado_tambem_pelo_corpo_do_post():
    c = _app_com_usuario(COMUM)
    r = c.post("/x", json={"conta_ml": "YUSO"})
    assert r.get_json()["conta"] == "M12"


def test_sem_conta_nos_metadados_recusa_em_vez_de_chutar():
    """Nunca cair num padrão: gravaria na loja de outro em silêncio."""
    c = _app_com_usuario({**COMUM, "conta_ml": None})
    r = c.get("/x")
    assert r.status_code == 400


def test_admin_sem_conta_na_query_usa_a_propria():
    c = _app_com_usuario(ADMIN)
    assert c.get("/x").get_json()["conta"] == "YUSO"
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd financeiro-backend && python -m pytest tests/test_contas_ml.py -v`
Esperado: FAIL com `ModuleNotFoundError: No module named 'contas_ml'`

- [ ] **Step 3: Implementar**

```python
# financeiro-backend/contas_ml.py
"""Resolução da loja (conta_ml) e a trava que impede gravar na loja de outro.

Arquivo separado de propósito: é a única fronteira de segurança desta migração.
As rotas de fechamento vieram do CRM, onde a trava usava `g.user["role"]` e
`g.user["conta_ml"]` — chaves que NÃO existiam no contexto do Painel. Portadas
sem isto, elas gravariam na loja errada sem dar erro nenhum.
"""
from flask import request, g


class SemConta(Exception):
    """Usuário sem loja nos metadados. Recusar é a resposta certa — cair num
    padrão gravaria dados de uma loja dentro de outra, em silêncio."""


def conta_do_request():
    """A loja desta requisição.

    Admin escolhe pela query ou pelo corpo; qualquer outro fica travado na
    própria loja, ignorando o que vier na requisição.
    """
    usuario = getattr(g, "user", {}) or {}
    propria = usuario.get("conta_ml")

    if not usuario.get("is_admin"):
        if not propria:
            raise SemConta()
        return propria

    corpo = request.get_json(silent=True) or {} if request.method in ("POST", "PUT") else {}
    escolhida = request.args.get("conta_ml") or corpo.get("conta_ml") or propria
    if not escolhida:
        raise SemConta()
    return escolhida
```

E em `auth.py`, dentro de `verify_jwt`, logo antes do `return`:

```python
    # conta_ml vem dos metadados do Supabase — MESMA fonte que o CRM usa, pra não
    # existir dois lugares dizendo a que loja alguém tem acesso.
    metadata = payload.get("user_metadata") or {}
    conta_ml = metadata.get("conta_ml")
    is_admin = metadata.get("role") == "admin"
    return {"user_id": user_id, "email": email, "fin_role": fin_role,
            "conta_ml": conta_ml, "is_admin": is_admin}
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd financeiro-backend && python -m pytest tests/test_contas_ml.py -v`
Esperado: 5 passed

- [ ] **Step 5: Confirmar que a suíte inteira segue verde**

Run: `cd financeiro-backend && python -m pytest tests/ -q`
Esperado: nenhuma falha nova em relação à linha de base

- [ ] **Step 6: Commit**

```bash
git add contas_ml.py auth.py tests/test_contas_ml.py
git commit -m "feat: trava por loja no Painel Financeiro

As rotas de fechamento que vao migrar do CRM travam o nao-admin na propria loja
usando g.user[role] e g.user[conta_ml] — chaves que nao existem no contexto do
Painel. Portadas sem isto, gravariam na loja errada sem dar erro nenhum.

conta_ml vem dos metadados do Supabase, a mesma fonte do CRM: mudar o acesso num
lugar vale nos dois sistemas."
```

---

### Task 2: Rotas de compras, fretes e montagem

**Files:**
- Create: `financeiro-backend/routes/fechamento.py`
- Create: `financeiro-backend/tests/test_fechamento.py`
- Modify: `financeiro-backend/app.py:11-25`

**Interfaces:**
- Consome: `contas_ml.conta_do_request()`, `contas_ml.SemConta`, `auth.require_auth`.
- Produz: blueprint `bp` registrado em `/api/fechamento`, servindo
  `GET|POST /compras`, `PUT|DELETE /compras/<id>` e o mesmo para `/fretes` e
  `/montagem`. Todos aceitam `?mes_ano=AAAA-MM`.

**Tabelas e colunas (do CRM, inalteradas):**
- `fechamento_compras (conta_ml, mes_ano, data, fornecedor, nota_fiscal, produto, quantidade, valor_unitario, valor_total, status, nota)`
- `fechamento_fretes (conta_ml, mes_ano, data, motorista, coleta_sp, frete_full, total, status)`
- `fechamento_montagem (conta_ml, mes_ano, montador, valor, data)`

- [ ] **Step 1: Escrever o teste que falha**

```python
# financeiro-backend/tests/test_fechamento.py
from unittest.mock import patch

COMPRA = {"id": 1, "conta_ml": "YUSO", "mes_ano": "2026-08", "data": "2026-08-05",
          "fornecedor": "Fornecedor X", "nota_fiscal": "123", "produto": "Cabo",
          "quantidade": 10, "valor_unitario": 5.0, "valor_total": 50.0,
          "status": "pago", "nota": None}


def test_lista_compras_do_mes(client, admin_headers):
    with patch("routes.fechamento.db.query", return_value=[COMPRA]) as q:
        r = client.get("/api/fechamento/compras?mes_ano=2026-08", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()[0]["fornecedor"] == "Fornecedor X"
    assert "2026-08" in q.call_args[0][1]


def test_mes_ano_invalido_recusa(client, admin_headers):
    r = client.get("/api/fechamento/compras?mes_ano=agosto", headers=admin_headers)
    assert r.status_code == 400


def test_viewer_grava_na_propria_loja_mesmo_pedindo_outra(client, viewer_headers):
    """Regressão da fronteira: o viewer da fixture é da M12; pedir YUSO na query
    não pode gravar na YUSO."""
    with patch("routes.fechamento.db.execute", return_value=COMPRA) as ex:
        r = client.post("/api/fechamento/compras?mes_ano=2026-08&conta_ml=YUSO",
                        json={"produto": "Cabo", "quantidade": 1, "valor_unitario": 5.0},
                        headers=viewer_headers)
    assert r.status_code == 201
    assert ex.call_args[0][1][0] == "M12"


def test_cria_compra_calcula_o_total(client, admin_headers):
    with patch("routes.fechamento.db.execute", return_value=COMPRA) as ex:
        client.post("/api/fechamento/compras?mes_ano=2026-08",
                    json={"produto": "Cabo", "quantidade": 10, "valor_unitario": 5.0},
                    headers=admin_headers)
    params = ex.call_args[0][1]
    assert params[8] == 50.0   # valor_total = quantidade * valor_unitario
```

O `conftest.py` precisa de uma linha a mais para os dois usuários da fixture terem loja:

```python
# em tests/conftest.py, nas constantes existentes
ADMIN_USER = {"user_id": "fd3a3d59-727f-40e2-bbea-c91187d2f0a7",
              "email": "cibellypeitl63@gmail.com", "fin_role": "fin_admin",
              "conta_ml": "YUSO", "is_admin": True}
VIEWER_USER = {"user_id": "aaaabbbb-0000-0000-0000-000000000001",
               "email": "socio@test.com", "fin_role": "fin_viewer",
               "conta_ml": "M12", "is_admin": False}
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd financeiro-backend && python -m pytest tests/test_fechamento.py -v`
Esperado: FAIL com 404 (blueprint não registrado)

- [ ] **Step 3: Implementar**

```python
# financeiro-backend/routes/fechamento.py
"""Fechamento mensal: compras, fretes e montagem.

Portado do CRM (ml-seller-api/routes/fechamento.py) em 19/08/2026. Duas
diferenças em relação ao original, ambas obrigatórias:
  - acesso ao banco pelos helpers db.query/db.execute, não por cursor cru;
  - a loja vem de contas_ml.conta_do_request(), que é onde mora a trava.
"""
from flask import Blueprint, request, jsonify

import contas_ml
import db
from auth import require_auth

bp = Blueprint("fechamento", __name__)


def _mes_ano_valido(mes_ano):
    try:
        ano, mes = str(mes_ano).split("-")
        int(ano)
        assert 1 <= int(mes) <= 12
        return True
    except Exception:
        return False


def _mes_ano():
    """(mes_ano, erro). Erro é uma resposta pronta, não uma exceção."""
    mes_ano = request.args.get("mes_ano", "")
    if not _mes_ano_valido(mes_ano):
        return None, (jsonify({"error": "mes_ano inválido; use AAAA-MM"}), 400)
    return mes_ano, None


@bp.get("/compras")
@require_auth
def listar_compras():
    mes_ano, erro = _mes_ano()
    if erro:
        return erro
    try:
        conta = contas_ml.conta_do_request()
    except contas_ml.SemConta:
        return jsonify({"error": "usuário sem loja definida"}), 400
    linhas = db.query(
        "SELECT * FROM fechamento_compras WHERE conta_ml = %s AND mes_ano = %s"
        " ORDER BY data, id",
        (conta, mes_ano),
    )
    return jsonify(linhas)


@bp.post("/compras")
@require_auth
def criar_compra():
    mes_ano, erro = _mes_ano()
    if erro:
        return erro
    try:
        conta = contas_ml.conta_do_request()
    except contas_ml.SemConta:
        return jsonify({"error": "usuário sem loja definida"}), 400

    d = request.get_json(silent=True) or {}
    quantidade = int(d.get("quantidade") or 0)
    valor_unitario = float(d.get("valor_unitario") or 0)
    linha = db.execute(
        """INSERT INTO fechamento_compras
             (conta_ml, mes_ano, data, fornecedor, nota_fiscal, produto,
              quantidade, valor_unitario, valor_total, status, nota)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (conta, mes_ano, d.get("data") or None, d.get("fornecedor") or None,
         d.get("nota_fiscal") or None, d.get("produto") or None,
         quantidade, valor_unitario, quantidade * valor_unitario,
         d.get("status") or "pendente", d.get("nota") or None),
    )
    return jsonify(linha), 201
```

`PUT` e `DELETE` de compras seguem a mesma forma, sempre com `conta_ml = %s` no
`WHERE` além do `id` — sem isso, um id de outra loja seria editável:

```python
@bp.put("/compras/<int:id>")
@require_auth
def editar_compra(id):
    try:
        conta = contas_ml.conta_do_request()
    except contas_ml.SemConta:
        return jsonify({"error": "usuário sem loja definida"}), 400
    d = request.get_json(silent=True) or {}
    quantidade = int(d.get("quantidade") or 0)
    valor_unitario = float(d.get("valor_unitario") or 0)
    linha = db.execute(
        """UPDATE fechamento_compras
              SET data=%s, fornecedor=%s, nota_fiscal=%s, produto=%s,
                  quantidade=%s, valor_unitario=%s, valor_total=%s,
                  status=%s, nota=%s
            WHERE id=%s AND conta_ml=%s RETURNING *""",
        (d.get("data") or None, d.get("fornecedor") or None,
         d.get("nota_fiscal") or None, d.get("produto") or None,
         quantidade, valor_unitario, quantidade * valor_unitario,
         d.get("status") or "pendente", d.get("nota") or None, id, conta),
    )
    if not linha:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify(linha)


@bp.delete("/compras/<int:id>")
@require_auth
def excluir_compra(id):
    try:
        conta = contas_ml.conta_do_request()
    except contas_ml.SemConta:
        return jsonify({"error": "usuário sem loja definida"}), 400
    linha = db.execute(
        "DELETE FROM fechamento_compras WHERE id=%s AND conta_ml=%s RETURNING id",
        (id, conta),
    )
    if not linha:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify({"ok": True})
```

**Fretes** repetem exatamente essa estrutura sobre
`fechamento_fretes (data, motorista, coleta_sp, frete_full, total, status)`, com
`total = coleta_sp + frete_full` calculado no servidor — o CRM calcula lá, e deixar o
cliente mandar o total abriria espaço para divergência entre o que aparece e o que soma.

**Montagem** repete sobre `fechamento_montagem (montador, valor, data)`, sem cálculo
derivado.

Registrar em `app.py`:

```python
    from routes.fechamento import bp as fechamento_bp
    app.register_blueprint(fechamento_bp, url_prefix="/api/fechamento")
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd financeiro-backend && python -m pytest tests/test_fechamento.py -v`
Esperado: 4 passed

- [ ] **Step 5: Commit**

```bash
git add routes/fechamento.py tests/test_fechamento.py tests/conftest.py app.py
git commit -m "feat: compras, fretes e montagem no backend financeiro

Portado do CRM. Acesso ao banco pelos helpers do Painel e loja resolvida por
contas_ml, que e onde mora a trava. Todo UPDATE e DELETE filtra por conta_ml
alem do id — sem isso, um id de outra loja seria editavel."
```

---

### Task 3: Rotas de despesas

**Files:**
- Modify: `financeiro-backend/routes/fechamento.py`
- Modify: `financeiro-backend/tests/test_fechamento.py`

**Interfaces:**
- Consome: o mesmo blueprint da Task 2.
- Produz: `GET|POST /despesas`, `PUT|DELETE /despesas/<id>`.

**Tabela:** `fechamento_despesas (conta_ml, mes_ano, data, categoria, descricao, valor, status)`

**Atenção — não portar junto:** o CRM tem também
`GET /api/fechamento/despesas-unificadas`, que junta as despesas do fechamento com as
importadas da Conta Simples e marca cada uma com `origem` e `editavel`. A integração
com a Conta Simples fica no CRM e não faz parte desta migração; portar a rota
unificada sem ela devolveria lista pela metade, sem avisar. Esta rota **fica no CRM**
até a Conta Simples ser tratada em trabalho próprio.

- [ ] **Step 1: Escrever o teste que falha**

```python
DESPESA = {"id": 7, "conta_ml": "YUSO", "mes_ano": "2026-08", "data": "2026-08-03",
           "categoria": "Aluguel", "descricao": "Galpão", "valor": 4200.0,
           "status": "pago"}


def test_lista_despesas_do_mes(client, admin_headers):
    with patch("routes.fechamento.db.query", return_value=[DESPESA]):
        r = client.get("/api/fechamento/despesas?mes_ano=2026-08", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()[0]["categoria"] == "Aluguel"


def test_viewer_nao_apaga_despesa_de_outra_loja(client, viewer_headers):
    with patch("routes.fechamento.db.execute", return_value=None) as ex:
        r = client.delete("/api/fechamento/despesas/7?conta_ml=YUSO",
                          headers=viewer_headers)
    assert r.status_code == 404
    assert ex.call_args[0][1] == (7, "M12")
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd financeiro-backend && python -m pytest tests/test_fechamento.py -k despesa -v`
Esperado: FAIL com 404

- [ ] **Step 3: Implementar**

```python
@bp.get("/despesas")
@require_auth
def listar_despesas():
    mes_ano, erro = _mes_ano()
    if erro:
        return erro
    try:
        conta = contas_ml.conta_do_request()
    except contas_ml.SemConta:
        return jsonify({"error": "usuário sem loja definida"}), 400
    return jsonify(db.query(
        "SELECT * FROM fechamento_despesas WHERE conta_ml=%s AND mes_ano=%s"
        " ORDER BY data, id",
        (conta, mes_ano),
    ))


@bp.post("/despesas")
@require_auth
def criar_despesa():
    mes_ano, erro = _mes_ano()
    if erro:
        return erro
    try:
        conta = contas_ml.conta_do_request()
    except contas_ml.SemConta:
        return jsonify({"error": "usuário sem loja definida"}), 400
    d = request.get_json(silent=True) or {}
    linha = db.execute(
        """INSERT INTO fechamento_despesas
             (conta_ml, mes_ano, data, categoria, descricao, valor, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (conta, mes_ano, d.get("data") or None, d.get("categoria") or None,
         d.get("descricao") or None, float(d.get("valor") or 0),
         d.get("status") or "pendente"),
    )
    return jsonify(linha), 201


@bp.delete("/despesas/<int:id>")
@require_auth
def excluir_despesa(id):
    try:
        conta = contas_ml.conta_do_request()
    except contas_ml.SemConta:
        return jsonify({"error": "usuário sem loja definida"}), 400
    linha = db.execute(
        "DELETE FROM fechamento_despesas WHERE id=%s AND conta_ml=%s RETURNING id",
        (id, conta),
    )
    if not linha:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify({"ok": True})
```

`PUT /despesas/<id>` segue a forma do `PUT` de compras, atualizando
`data, categoria, descricao, valor, status` e filtrando por `id` e `conta_ml`.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd financeiro-backend && python -m pytest tests/test_fechamento.py -v`
Esperado: todos passam

- [ ] **Step 5: Commit**

```bash
git add routes/fechamento.py tests/test_fechamento.py
git commit -m "feat: despesas do fechamento no backend financeiro

A rota despesas-unificadas NAO vem junto: ela mistura as despesas do fechamento
com as importadas da Conta Simples, cuja integracao fica no CRM. Portada sem
isso, devolveria lista pela metade sem avisar."
```

---

### Task 4: Estoque mensal e contagem de galpão

**Files:**
- Create: `financeiro-backend/routes/estoque_mensal.py`
- Modify: `financeiro-backend/tests/test_fechamento.py`
- Modify: `financeiro-backend/app.py`

**Interfaces:**
- Consome: `contas_ml.conta_do_request()`.
- Produz: `GET|POST /api/fechamento/estoque`, `GET|PUT /api/fechamento/galpao`.

**Regra que não pode se perder na tradução:** `fechamento_galpao_mensal` tem a coluna
`galpao_registrado`. Ela existe para distinguir "contagem ainda não feita" de "contei e
deu zero" — duas situações que significam coisas opostas no fechamento e que um
`valor = 0` sozinho confundiria. A tabela é chaveada por `owner_user_id` e `mes_ano`
(não por `conta_ml`): a contagem do galpão é física e única, não por loja.

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_galpao_nao_contado_e_diferente_de_contado_zero(client, admin_headers):
    """Duas situações opostas no fechamento; um zero sozinho as confundiria."""
    with patch("routes.estoque_mensal.db.query", return_value=[]):
        r = client.get("/api/fechamento/galpao?mes_ano=2026-08", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json()["registrado"] is False

    with patch("routes.estoque_mensal.db.query",
               return_value=[{"valor": 0, "galpao_registrado": True}]):
        r = client.get("/api/fechamento/galpao?mes_ano=2026-08", headers=admin_headers)
    assert r.get_json()["registrado"] is True
    assert r.get_json()["valor"] == 0
```

- [ ] **Step 2: Rodar e confirmar que falha**

Run: `cd financeiro-backend && python -m pytest tests/test_fechamento.py -k galpao -v`
Esperado: FAIL com 404

- [ ] **Step 3: Implementar**

```python
# financeiro-backend/routes/estoque_mensal.py
"""Estoque mensal por loja e a contagem física do galpão.

Portado do CRM em 19/08/2026. A contagem do galpão é chaveada por usuário e mês,
não por loja: o galpão é físico e único.
"""
from flask import Blueprint, request, jsonify, g

import contas_ml
import db
from auth import require_auth

bp = Blueprint("estoque_mensal", __name__)


@bp.get("/galpao")
@require_auth
def ler_galpao():
    mes_ano = request.args.get("mes_ano", "")
    linhas = db.query(
        "SELECT valor, galpao_registrado FROM fechamento_galpao_mensal"
        " WHERE owner_user_id = %s AND mes_ano = %s",
        (g.user["user_id"], mes_ano),
    )
    if not linhas:
        # Nunca devolver valor 0 aqui: "não contei" e "contei e deu zero" são
        # coisas diferentes, e quem lê precisa conseguir distinguir.
        return jsonify({"registrado": False, "valor": None})
    linha = linhas[0]
    return jsonify({"registrado": bool(linha["galpao_registrado"]),
                    "valor": linha["valor"]})
```

O `PUT /galpao` grava `valor` e marca `galpao_registrado = true`; `GET|POST /estoque`
leem e gravam `fechamento_estoque_mensal` filtrando por `conta_ml` de
`contas_ml.conta_do_request()` e por `mes_ano`.

Registrar em `app.py`:

```python
    from routes.estoque_mensal import bp as estoque_bp
    app.register_blueprint(estoque_bp, url_prefix="/api/fechamento")
```

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `cd financeiro-backend && python -m pytest tests/ -q`
Esperado: todos passam, sem falha nova

- [ ] **Step 5: Commit**

```bash
git add routes/estoque_mensal.py tests/test_fechamento.py app.py
git commit -m "feat: estoque mensal e contagem de galpao no backend financeiro

galpao_registrado sobrevive ao porte: distingue 'nao contei' de 'contei e deu
zero', que significam coisas opostas no fechamento."
```

---

### Task 5: Tela de Fechamento no Painel

**Files:**
- Create: `financeiro-frontend/src/pages/Fechamento.jsx`
- Modify: `financeiro-frontend/src/App.jsx`

**Interfaces:**
- Consome: as rotas das Tasks 2–4, em `/api/fechamento/*` do backend financeiro.
- Produz: rota `/fechamento` no Painel.

- [ ] **Step 1: Portar a tela**

Copiar `ml-seller-app/src/pages/Fechamento.jsx` e adaptar:
- trocar o cliente HTTP pelo `api` do Painel — `import api from '../services/api'`,
  o mesmo que `ContasPagar.jsx:4` usa;
- trocar o seletor global de loja do CRM por um `<select>` local, no padrão de
  `RepasesML.jsx:106` — o Painel não tem seletor global, e trazer um seria mudança
  maior que a migração;
- manter o seletor de mês (`<input type="month">`) como está.

- [ ] **Step 2: Ver a tela funcionando**

Run: `cd financeiro-frontend && npm run dev`
Abrir `/fechamento`, criar uma compra de teste, conferir que aparece na lista e que o
mês filtra.

- [ ] **Step 3: Conferir loja errada pelo navegador**

Com um usuário não-admin, editar a query string para `?conta_ml=` de outra loja e
confirmar que os dados continuam sendo os da própria loja. É a mesma trava da Task 1,
agora vista de ponta a ponta.

- [ ] **Step 4: Commit**

```bash
git add src/pages/Fechamento.jsx src/App.jsx
git commit -m "feat: tela de Fechamento no Painel Financeiro"
```

---

### Task 6: CORS do CRM e tela de Lucro Real

**Files:**
- Modify: `ml-seller-api/app.py:11-28`
- Create: `financeiro-frontend/src/pages/LucroReal.jsx`
- Modify: `financeiro-frontend/src/App.jsx`

**Interfaces:**
- Consome: `GET /api/fechamento/lucro-real` do **backend do CRM** (não do financeiro).
- Produz: rota `/lucro-real` no Painel.

- [ ] **Step 1: Liberar o domínio do Painel no CORS do CRM**

Em `ml-seller-api/app.py`, junto dos origins já permitidos:

```python
    # O Painel Financeiro passou a servir a tela de Lucro Real, mas o cálculo
    # ficou aqui: depende da integração com o ML, que só existe neste backend.
    _painel = "https://financeiro.cravelli.com.br"
    if _painel not in origins:
        origins.append(_painel)
```

- [ ] **Step 2: Portar a tela**

Copiar `ml-seller-app/src/pages/FechamentoLucroReal.jsx`, apontando as chamadas para a
URL do backend do CRM (variável de ambiente nova no Painel, ex. `VITE_CRM_API_URL`), com
o mesmo token do Supabase que o Painel já usa.

- [ ] **Step 3: Tratar o CRM fora do ar**

A tela precisa dizer que o CRM não respondeu, em vez de mostrar tela vazia — é a
dependência nova que a spec registra como risco:

```jsx
if (erro) return (
  <p>Não foi possível carregar o Lucro Real: o sistema de vendas não respondeu.
     Os lançamentos do fechamento continuam disponíveis.</p>
)
```

- [ ] **Step 4: Conferir número por número**

Abrir a mesma loja e o mesmo mês nas duas telas — a do CRM e a do Painel — e comparar
linha a linha. Devem ser idênticas; qualquer diferença é erro de porte, não de cálculo.

- [ ] **Step 5: Commit**

```bash
git add src/pages/LucroReal.jsx src/App.jsx   # no financeiro-frontend
git commit -m "feat: tela de Lucro Real no Painel, consumindo o CRM"
```

---

### Task 7: Corte

**Files:**
- Modify: `ml-seller-app/src/App.jsx`
- Modify: `ml-seller-app/src/components/Sidebar.jsx`

- [ ] **Step 1: Redirecionar as rotas antigas**

```jsx
<Route path="/fechamento" element={<Navigate to="https://financeiro.cravelli.com.br/fechamento" replace />} />
```

Como `Navigate` não sai do domínio, usar um componente pequeno que faz
`window.location.replace(...)` — e manter o redirecionamento, não apagar a rota: a
equipe tem o link salvo, e "página não encontrada" sem explicação foi o erro que a
gente evitou no Quadro de Tarefas.

- [ ] **Step 2: Menu do CRM aponta pro Painel**

Em `Sidebar.jsx`, os itens de Fechamento e Lucro Real passam a levar ao Painel, com o
ícone de link externo.

- [ ] **Step 3: Conferir**

Abrir o CRM, clicar em Fechamento, confirmar que chega no Painel logada — sem novo
login, porque o token é o mesmo.

- [ ] **Step 4: Commit**

```bash
git add src/App.jsx src/components/Sidebar.jsx
git commit -m "chore: Fechamento e Lucro Real passam a viver no Painel Financeiro

Rotas antigas redirecionam em vez de sumir: a equipe tem os links salvos."
```

---

## Autorrevisão

**Cobertura da spec:** os seis passos da ordem de execução da spec estão cobertos —
permissão (Task 1), fechamento no backend (Tasks 2–4), tela (Task 5), CORS e Lucro Real
(Task 6), corte (Task 7). Os quatro testes exigidos pela spec aparecem: trava por loja
(Tasks 1, 2, 3), usuário sem conta (Task 1), comparação lado a lado do Lucro Real
(Task 6, passo 4) e redirecionamento (Task 7, passo 3).

**Achado durante a escrita, registrado aqui porque muda o escopo:** a rota
`despesas-unificadas` do CRM depende da integração com a Conta Simples e **não migra**
(Task 3). A spec não previa isso. Fica no CRM até a Conta Simples ser tratada.

**Consistência de nomes:** `contas_ml.conta_do_request()` e `contas_ml.SemConta` são
usados com o mesmo nome nas Tasks 1 a 4; o blueprint `bp` de `routes/fechamento.py`
recebe as rotas das Tasks 2 e 3; `db.query`/`db.execute` são os helpers do Painel em
todas as tarefas de backend.
