# Conciliação bancária via importação de OFX

## Contexto

O painel financeiro tentava conciliar o extrato bancário do Sicredi via integração com a
Pluggy (`routes/pluggy.py`). Investigação mostrou que isso nunca funcionou: a conta Pluggy
está em trial expirado, o acesso a produção nunca foi solicitado (falta due diligence e
registro de webhooks), e o ambiente disponível é sandbox — só conecta bancos fictícios
(`MeuPluggy`), nunca o Sicredi real. Reativar o Pluggy exigiria assinar um plano pago e
passar pelo processo de aprovação deles, então a decisão foi remover essa integração e
substituir por importação manual de extrato OFX (formato padrão que o internet banking do
Sicredi exporta), com conciliação automática assistida.

## Escopo

1. Remover completamente a integração Pluggy (backend, frontend, tabelas no banco).
2. Implementar conciliação bancária via upload de arquivo `.ofx`: casamento automático
   contra lançamentos já existentes, com uma tela de revisão antes de aplicar qualquer
   mudança no banco.

Fora de escopo: qualquer integração automática/API com banco (Pluggy, Belvo, etc.) — pode
ser revisitada depois, como projeto separado.

## Parte 1 — Remoção do Pluggy

**Backend:**
- Remover `routes/pluggy.py` e o registro do blueprint em `app.py`
- Remover `PLUGGY_CLIENT_ID`, `PLUGGY_CLIENT_SECRET`, `PLUGGY_REDIRECT_URL` de `config.py`
- Migration `005_drop_fin_pluggy_tables.sql`: `DROP TABLE fin_pluggy_items` (criada em
  produção fora de qualquer migration versionada) e `DROP TABLE fin_pluggy_connections`
  (placeholder da Fase 1, nunca usado em código). Ambas vazias, sem risco de perda de dado.
- `routes/repasses.py` usa a string literal `origem = 'pluggy'` para o sync de Mercado
  Pago — isso é um nome legado que não tem relação com a API da Pluggy (não usa
  `PLUGGY_CLIENT_ID`/API deles). **Não mexer nesse arquivo.**

**Frontend (`financeiro-frontend/src/pages/ContasPagar.jsx`):**
- Remover estado (`pluggyStatus`, `connectLoading`, `syncLoading`, `syncMsg`), os handlers
  `conectarSicredi`/`sincronizarDDA`/`carregarPluggyStatus`, e o bloco de UI do botão
  "Conectar Sicredi" / sincronizar DDA.

**Migration local órfã:** `005_fin_pluggy_items.sql` (criada nesta sessão, nunca chegou a
rodar — a tabela já existia em produção por fora do versionamento) é substituída pela
migration de remoção acima.

## Parte 2 — Importação de OFX

### Modelo de dados

Nova migration `006_fin_extrato_transacoes.sql`:

```sql
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

ALTER TABLE fin_contas_pagar ADD COLUMN ofx_transacao_id UUID REFERENCES fin_extrato_transacoes(id);
ALTER TABLE fin_pedido_pagamentos ADD COLUMN ofx_transacao_id UUID REFERENCES fin_extrato_transacoes(id);
ALTER TABLE fin_repasses_ml ADD COLUMN ofx_transacao_id UUID REFERENCES fin_extrato_transacoes(id);
```

RLS: mesmo padrão das demais tabelas `fin_` (SELECT para qualquer `fin_role`, escrita
só para `fin_admin`).

`fitid` é o identificador único de transação que todo arquivo OFX traz — usado pra nunca
importar a mesma transação duas vezes, mesmo que o período do extrato se sobreponha entre
uploads.

### Algoritmo de casamento

Ao importar, para cada transação do OFX (exceto `fitid` já existente em
`fin_extrato_transacoes`, que é pulado):

- **DEBIT** → procura candidato em `fin_contas_pagar` (`status = 'pago'`,
  `ofx_transacao_id IS NULL`) e em `fin_pedido_pagamentos`
  (`ofx_transacao_id IS NULL`), mesmo `valor`, `data`/`data_pagamento` dentro de ±3 dias.
  - Achou → sugestão de match salva em `match_tabela`/`match_id`, `status` continua
    `pendente` (só vira `conciliado` na confirmação).
  - Não achou → sugestão implícita é "criar conta nova"; front mostra essa opção
    pré-selecionada.
- **CREDIT** → mesmo critério contra `fin_repasses_ml`. Sem match → fica listado como
  "não identificado", sem ação sugerida (fica ignorado se o usuário não agir).
- Dentro do mesmo lote, um registro candidato só pode ser sugerido para uma transação
  (marca como "reservado" em memória durante o processamento do lote, pra não sugerir a
  mesma conta paga pra duas transações de valor igual).

### Endpoints (`routes/conciliacao.py`, blueprint novo)

- `POST /api/conciliacao/importar` (`require_auth`, `require_admin`, multipart `.ofx`) —
  faz o parse (biblioteca `ofxparse`), roda o casamento, insere as linhas em
  `fin_extrato_transacoes` com status `pendente`. Retorna `{lote_id, total, casadas, sem_match}`.
- `GET /api/conciliacao/lotes/<lote_id>` (`require_auth`) — lista as transações do lote
  com o registro candidato (join pra mostrar descrição/valor do lado do sistema).
- `POST /api/conciliacao/lotes/<lote_id>/confirmar` (`require_admin`) — recebe
  `[{transacao_id, acao: 'confirmar_match'|'ignorar'|'criar_conta'}]`. Para cada item:
  - `confirmar_match`: seta `ofx_transacao_id` no registro alvo (e `confirmado = true`
    se for `fin_repasses_ml`), marca a transação como `conciliado`.
  - `criar_conta`: insere em `fin_contas_pagar`
    (`categoria='OUTRO'`, `status='a_confirmar'`, `origem='ofx'`, `vencimento=data da transação`),
    linka `ofx_transacao_id`, marca a transação como `nova_conta`.
  - `ignorar`: marca a transação como `ignorado`, sem outra alteração.
  - Tudo dentro de uma transação SQL única (`db.transaction()`), rollback se qualquer
    item falhar.

### Frontend

Página nova `src/pages/ConciliacaoBancaria.jsx`, rota `/conciliacao`, com link no menu
lateral (`Sidebar.jsx`):

1. Botão de upload (`<input type="file" accept=".ofx">`) → `POST /importar`.
2. Depois do upload, mostra resumo (`32 transações → 28 casadas, 4 sem match`) e a tabela
   de revisão: data, descrição, valor, sugestão (nome da conta/pedido casado, ou "sem
   match — criar conta nova", ou "não identificado" pra créditos sem match), com um select
   de ação por linha (aceitar sugestão / ignorar / criar conta) já pré-preenchido pela
   sugestão do backend.
3. Botão "Confirmar" → `POST /confirmar` com as ações de todas as linhas → mostra
   resultado final e limpa a tela.

### Erros e casos de borda

- Arquivo que não é OFX válido → erro 400 antes de tocar no banco.
- Reimportar um extrato com transações já importadas → `fitid` duplicado é
  silenciosamente pulado (não gera erro, só não duplica).
- Lote sem nenhuma transação nova (tudo já importado antes) → mensagem clara no front
  ("nada de novo pra revisar"), sem criar lote vazio.

### Testes

- Parser: OFX de exemplo com débitos e créditos → transações extraídas corretamente,
  `fitid` deduplicado em reimportação.
- Casamento: cenários com match exato, match fora da janela de 3 dias (não deve casar),
  dois candidatos de mesmo valor (não pode casar os dois na mesma transação).
- Confirmação: cada ação (`confirmar_match`, `ignorar`, `criar_conta`) aplicando a
  mudança esperada nas tabelas alvo; rollback em caso de erro no meio do lote.
