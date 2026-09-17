# Aba Funcionários — pagamento, DAS e NF por pessoa e por mês

**Data:** 2026-09-17
**Repos afetados:** `financeiro-backend`, `financeiro-frontend`
**Decidido com a Cibelly em:** 17/09/2026, na mesma conversa em que a Caixa da Semana virou fluxo da semana

## Contexto

A Cibelly paga prestadores **MEI** (Josie, Renata, Jaqueline, Fabrício, Bianca…) por
mês. Cada mês de cada pessoa gera três coisas que hoje ficam espalhadas entre
WhatsApp, Downloads e a cabeça dela:

1. o **pagamento** dos serviços do mês, por Pix — e o comprovante;
2. o **DAS** daquele mês — boleto e comprovante. **A empresa paga** o DAS deles;
3. a **NF** que a pessoa emite pelos serviços do mês.

Pedido dela, nas próprias palavras:

> "quero criar nesse painel financeiro uma aba nova de funcionários — adicionar o
> nome de cada um e dentro de cada nome eu coloco o valor, comprovante igual
> coloco nos fornecedores + boleto e comprovante do DAS de cada um deles + NF
> emitida pelos serviços daquele mês."

Decisões tomadas na conversa (uma pergunta por vez):

| Pergunta | Resposta dela |
|---|---|
| Esse dinheiro entra na Caixa da Semana? | **Entra na sobra**, como linha própria: entra − boletos − fornecedores − **funcionários** |
| Quem paga o DAS? | **A empresa** — entra na sobra junto com o pagamento |
| O "mês" de uma pessoa é o do serviço ou o do Pix? | **O do serviço (competência)**. A NF e o DAS já nascem "de setembro"; a Caixa desconta cada valor na semana em que foi pago |
| Documentos atrasados | Acontece (NF de agosto do Fabrício emitida só em setembro): **a competência é escolhida ao anexar**, com o mês atual como padrão |
| Como fazer | **Aba própria com tabela própria, reaproveitando o upload com leitura por IA** — não "cadastrar como fornecedor" (o molde de pedido/itens/saldo devedor não serve, e DAS/NF ficariam sem lugar) |

## Escopo

**Dentro:** aba Funcionários (cadastro, meses, três lançamentos por mês com upload
e leitura por IA); linha "Pago a funcionários" na Caixa da Semana; leitores de
boleto DAS e de NF; aviso do que falta no mês.

**Fora:** avisar quando o DAS está para vencer; horas/ponto dos freelas (isso é
do `ponto-digital`, não mistura com dinheiro); folha, férias, 13º ou qualquer
cálculo trabalhista — são MEI, não CLT; recibo/relatório para o contador (fica
para quando ela pedir; os dados vão estar prontos).

## O que já existe (levantado, não suposto)

- **Upload com leitura por IA** (`routes/fornecedores.py`, `leitura_documento.py`,
  `storage.py`, `aliases.py`): multipart `arquivo` → `pendentes/<hex>.<ext>` no bucket
  privado `fornecedores` → `client.messages.create` com `output_config` JSON Schema →
  rascunho → ela confere → salvar move o arquivo para o destino e grava `arquivo_path`.
  Token validado por `^pendentes/[0-9a-f]{32}\.(pdf|jpg|png)$`. Data do Pix Sicredi
  vem do E2E. Comprovante repetido barrado por índice único parcial em `id_transacao`.
- `ler_comprovante(dados, mime)` devolve `valor`, `data_pagamento`, `destinatario`,
  `id_transacao` — serve para o Pix do funcionário sem mudar nada.
- Helpers hoje **presos dentro de `routes/fornecedores.py`**: `_ler_arquivo_enviado`,
  `_subir_pendente`, `_arquivo_token_valido`, `_destino_anexo`, `_url_anexo`,
  `MSG_LEITURA_INDISPONIVEL`, `MSG_ANEXO_NAO_GUARDADO`. A rota nova precisa deles.
- Caixa da Semana (`src/pages/CaixaSemana.jsx`): `GET /api/fornecedores/pagamentos?de&ate`
  → `pagamentosDaSemana()` → card "Pago a fornecedor" → `sobra = totalRepasse −
  totalBoletos − totalPagoFornecedor`; dia a dia soma `saiPagos`; botão "Descontar /
  Não descontar" guarda em `ajustes_pagamento` (por id do pagamento).
- Menu em `src/components/Layout.jsx`; rotas em `src/App.jsx`; página modelo
  `src/pages/Fornecedores.jsx` (cartões → seleção → mês → lançamentos).
- Papéis: `fin_admin` grava; Cibelly e Valber são `fin_admin`.

## Fluxo (o que ela vê)

**Menu → Funcionários.** Cartões com o nome de cada pessoa (+ "Novo funcionário":
nome, CNPJ do MEI opcional, valor combinado por mês opcional). Editar e desativar
como em Fornecedores; desativar esconde, não apaga.

**Clica no nome → seletor de mês (competência)**, abrindo no mês atual. Abaixo,
três blocos, sempre os três, mesmo vazios:

```
Josie · Setembro 2026                                   falta: NF

PAGAMENTO   R$ 2.500,00 · pago em 05/10 · 📎        [📎 Subir comprovante do Pix]  [+ lançar à mão]
DAS         R$ 75,90 · vence 20/10 · pago em 18/10 · 📎 boleto · 📎 comprovante
                                                    [📎 Subir boleto]  [📎 Subir comprovante]
NF          — nada ainda —                          [📎 Subir NF]  [+ lançar à mão]
```

- **Pagamento**: pode haver mais de um no mês (adiantamento + saldo); o bloco soma.
  "Subir comprovante do Pix" lê valor, data e ID do Pix; competência vem do seletor;
  valor combinado do cadastro pré-preenche quando não há leitura.
- **DAS**: um por mês. "Subir boleto" lê valor, vencimento e competência (Período de
  Apuração); ao salvar, o DAS fica **em aberto**. "Subir comprovante" lê valor/data/ID
  e, ao salvar, marca **pago em** no DAS do mês (ou cria o DAS já pago, se não havia
  boleto). Também dá para marcar pago à mão.
- **NF**: uma por mês. "Subir NF" lê número, valor, prestador e competência.
- Cada bloco tem ✏️ (editar valor/datas/competência) e 🗑️; 📎 abre o arquivo em
  nova aba (URL assinada, 1 h, no clique — mesmo padrão dos fornecedores).
- **Cabeçalho do mês** diz o que falta: "falta: DAS, NF" / "DAS em aberto, vence 20/10"
  / "mês completo ✓". Completo = pelo menos um pagamento, DAS pago, NF lançada.
- **Lista de meses** abaixo do mês aberto: os 12 últimos, cada um com o mesmo resumo,
  para achar o que ficou para trás (a NF de agosto do Fabrício).

**Cartão de conferência** (igual ao dos fornecedores): sobe o arquivo → spinner → campos
lidos e editáveis → faixas de aviso → Salvar. Nunca grava sem ela clicar.

Faixas:
- leitura falhou → cartão vazio com o arquivo em preview, preenche à mão;
- arquivo não guardado → lança sem anexo, com aviso;
- **comprovante já usado** (mesmo ID de Pix, em qualquer funcionário ou fornecedor) → vermelha;
- **CNPJ do documento ≠ CNPJ cadastrado** (DAS/NF de outra pessoa) → amarela;
- **competência lida ≠ mês aberto** → amarela, e o campo competência já vem com a lida,
  para ela decidir (é assim que a NF de agosto entra em agosto estando setembro aberto);
- já existe DAS/NF nessa competência → amarela "vai substituir? / lançar outro?".

## Backend

### Migração `20260917_funcionarios.sql`

```sql
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
  valor NUMERIC(12,2),                    -- NF pode vir sem valor lido; DAS/pagamento exigem
  vencimento DATE,                        -- DAS
  pago_em DATE,                           -- pagamento e DAS; NULL = em aberto
  numero_nf TEXT,                         -- NF
  id_transacao TEXT,                      -- E2E do Pix (pagamento e comprovante do DAS)
  arquivo_path TEXT,                      -- Pix do pagamento / NF
  boleto_path TEXT,                       -- DAS: o boleto
  comprovante_path TEXT,                  -- DAS: o comprovante
  observacao TEXT,
  criado_por UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_func_lanc_func_comp ON fin_funcionario_lancamentos(funcionario_id, competencia);
CREATE INDEX IF NOT EXISTS idx_func_lanc_pago_em ON fin_funcionario_lancamentos(pago_em) WHERE pago_em IS NOT NULL;
-- O mesmo Pix não entra duas vezes aqui. Entre esta tabela e a de fornecedores a
-- checagem é na rota (consulta as duas) — índice não atravessa tabela.
CREATE UNIQUE INDEX IF NOT EXISTS idx_func_lanc_id_transacao
  ON fin_funcionario_lancamentos(id_transacao) WHERE id_transacao IS NOT NULL;
-- Um DAS e uma NF por competência; pagamento pode repetir.
CREATE UNIQUE INDEX IF NOT EXISTS idx_func_lanc_um_por_mes
  ON fin_funcionario_lancamentos(funcionario_id, competencia, tipo) WHERE tipo IN ('das', 'nf');

ALTER TABLE fin_funcionarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_funcionario_lancamentos ENABLE ROW LEVEL SECURITY;
-- Mesmas policies das outras fin_* (copiadas de 005_fin_pagamentos_fornecedor.sql).
CREATE POLICY "fin_select" ON fin_funcionarios FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
CREATE POLICY "fin_write" ON fin_funcionarios FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
CREATE POLICY "fin_select" ON fin_funcionario_lancamentos FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
CREATE POLICY "fin_write" ON fin_funcionario_lancamentos FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
```

Uma tabela para os três tipos, não três tabelas: o mês de uma pessoa é "as linhas
com aquela competência", e a pergunta "o que falta?" é um `GROUP BY tipo`. Colunas
específicas (vencimento, numero_nf, boleto_path) ficam NULL onde não se aplicam —
mais barato que três tabelas com três rotas iguais.

Competência é `DATE` no dia 1 (não `TEXT 'YYYY-MM'`): compara, ordena e entra em
`BETWEEN` sem conversão.

### Helpers de anexo saem de `routes/fornecedores.py` → `anexos.py`

`_ler_arquivo_enviado`, `_subir_pendente`, `_arquivo_token_valido`, `_destino_anexo`,
`_url_anexo`, `MSG_LEITURA_INDISPONIVEL`, `MSG_ANEXO_NAO_GUARDADO` viram funções
públicas de um módulo `anexos.py`, importadas pelas duas rotas. `_destino_anexo`
ganha o prefixo como parâmetro: `destino_anexo(prefixo, pasta, registro_id, token)`
→ fornecedores continua `<fornecedor_id>/pedidos/<id>.<ext>`; funcionários vira
`funcionarios/<funcionario_id>/<competencia YYYY-MM>/<tipo>-<id>.<ext>`. Mesmo bucket
privado `fornecedores` (renomear bucket em produção não vale o risco; o prefixo separa).
Os testes existentes dos fornecedores continuam passando sem mudança de comportamento.

### Leitores novos em `leitura_documento.py`

Mesmo `_chamar`, esquemas próprios:

- `ler_boleto_das(dados, mime) -> {valor, vencimento, competencia, cnpj, nome}` —
  o DAS-MEI traz "Período de Apuração" (→ competência), "Data de vencimento", "Valor
  total do documento", CNPJ e nome do contribuinte. Pós-processamento: competência
  normalizada para `YYYY-MM-01`; CNPJ só dígitos; `valor <= 0` → `LeituraFalhou`.
- `ler_nota_fiscal(dados, mime) -> {numero, valor, data_emissao, competencia, cnpj_prestador, nome_prestador}` —
  NFS-e de MEI: número, valor dos serviços, data de emissão, prestador, e a competência
  pela discriminação ("serviços prestados em setembro/2026") — se a IA não achar,
  competência = mês da emissão, marcado `competencia_inferida: true` para a faixa amarela.

Fixtures sintéticas (`tests/fixtures/leitura_das.json`, `leitura_nf.json`); nenhum
documento real no repositório.

### Rotas `routes/funcionarios.py` (prefixo `/api/funcionarios`)

| Método | Rota | Quem | Faz |
|---|---|---|---|
| GET | `` | auth | lista ativos com resumo do mês atual (`falta: [...]`) |
| POST | `` | admin | cria (nome obrigatório; cnpj só dígitos, 14; valor_combinado ≥ 0) |
| PUT | `/<id>` | admin | edita nome/cnpj/valor_combinado |
| DELETE | `/<id>` | admin | `ativo = false` |
| GET | `/pagamentos?de&ate` | auth | **para a Caixa**: pagamentos e DAS com `pago_em` no período, com `funcionario_nome` e `tipo` |
| GET | `/<id>/meses?ate=YYYY-MM&n=12` | auth | resumo por competência: totais e o que falta |
| GET | `/<id>/lancamentos?competencia=YYYY-MM` | auth | as linhas do mês |
| POST | `/<id>/lancamentos` | admin | cria (tipo, competencia, valor, vencimento, pago_em, numero_nf, `arquivo_token`/`boleto_token`/`comprovante_token`, id_transacao) |
| PUT | `/<id>/lancamentos/<lid>` | admin | edita campos; aceita token novo para trocar/adicionar anexo |
| DELETE | `/<id>/lancamentos/<lid>` | admin | apaga a linha (arquivos ficam no bucket; limpeza é fora do escopo) |
| POST | `/<id>/ler/pix` | admin | `ler_comprovante` + checagem de E2E nas **duas** tabelas |
| POST | `/<id>/ler/das` | admin | `ler_boleto_das` + confere CNPJ com o cadastro |
| POST | `/<id>/ler/nf` | admin | `ler_nota_fiscal` + confere CNPJ |
| GET | `/<id>/lancamentos/<lid>/anexo?qual=arquivo\|boleto\|comprovante` | auth | URL assinada |

Regras nas rotas:
- `pagamento`: `valor > 0` e `pago_em` obrigatórios.
- `das`: `valor > 0`; `vencimento` opcional; `pago_em` opcional (em aberto); no máximo um por competência — segundo `POST` responde 409 com o id do existente (a tela oferece substituir via `PUT`).
- `nf`: `numero_nf` ou `arquivo_token` obrigatório; um por competência (409 idem).
- `competencia` aceita `YYYY-MM` e grava dia 1.
- Mover anexo dentro da mesma transação do INSERT (tudo ou nada), como em `criar_pedido`.
- As rotas `/ler` só leem; **nada grava sem o Salvar dela**.

### Caixa da Semana

`GET /api/funcionarios/pagamentos?de&ate` devolve pagamentos **e DAS pagos** no período
(`tipo`, `funcionario_nome`, `valor`, `data_pagamento` = `pago_em`, `created_at`, `id`).

Frontend: `pagamentosDaSemana()` recebe também esta lista; card novo **"Pago a
funcionários"** com composição por nome ("Josie R$ 2.500,00 · DAS Josie R$ 75,90");
`sobra = totalRepasse − totalBoletos − totalPagoFornecedor − totalPagoFuncionarios`;
dia a dia inclui `saiFuncionarios`; o botão "Descontar / Não descontar" vale igual
(mesmo `ajustes_pagamento`, ids são UUID e não colidem). `docs/regras-caixa-semana.md`
ganha a linha.

## Frontend

- `src/pages/Funcionarios.jsx` — cartões, cadastro, seletor de competência, os três
  blocos, lista de meses. Não copiar `Fornecedores.jsx` (1.100 linhas): a página nova
  monta blocos pequenos.
- `src/components/BlocoLancamentoFuncionario.jsx` — um bloco (título, linhas, botões).
- `src/components/UploadDocumentoFuncionario.jsx` — o cartão de conferência, genérico por
  tipo (`pix` / `das` / `nf`): campos, faixas, salvar. Reaproveita `Faixa`, preview por
  tipo de arquivo e o padrão de estados (`ocioso → lendo → conferindo → salvando`) do
  `UploadPedidoCompra`; o que for idêntico (preview, `validarArquivo`, `mensagemDe`,
  `Faixa`) sai para `src/components/upload/comum.jsx` e os dois componentes importam.
- `Layout.jsx`: item "Funcionários" depois de "Fornecedores". `App.jsx`: rota `/funcionarios`.
- `CaixaSemana.jsx`: a linha nova (acima).

## Quando dá errado

| Situação | O que acontece |
|---|---|
| Arquivo > 10 MB / tipo não aceito | 400 antes de ler; mensagem na tela |
| IA não leu | 200 com `leitura_falhou`; cartão vazio + preview; anexo preservado |
| API da IA fora / sem chave | 503 "Leitura automática indisponível agora. Lance à mão." — "+ lançar à mão" segue |
| Storage falhou ao guardar | lança sem anexo, faixa avisa |
| Pix já usado (funcionário ou fornecedor) | faixa vermelha; ao salvar, 409 |
| CNPJ do DAS/NF ≠ cadastrado | faixa amarela; salvar permitido |
| Competência lida ≠ mês aberto | faixa amarela; campo vem com a lida |
| Já existe DAS/NF no mês | faixa amarela "substituir?" → `PUT` no existente, ou cancela |
| Storage falha ao mover no salvar | nada gravado (transação), mensagem pede tentar de novo |

## Testes

- `tests/test_anexos.py`: os helpers movidos (token válido/inválido, destino com prefixo,
  limpeza tolerante) — e `tests/test_fornecedores_upload.py` passa sem mudança.
- `tests/test_leitura_documento.py`: `ler_boleto_das` e `ler_nota_fiscal` com fixtures
  gravadas — competência normalizada, CNPJ só dígitos, `competencia_inferida`, valor
  zero → `LeituraFalhou`.
- `tests/test_funcionarios.py`: CRUD; `/pagamentos` do período traz pagamento e DAS pago e
  ignora DAS em aberto; `/meses` diz o que falta; um DAS/NF por mês (409); E2E repetido
  em qualquer das duas tabelas → 409; anexo movido na transação; viewer 403 nos writes.
- Frontend (vitest já existe): `pagamentosDaSemana` com funcionários; card e sobra; página
  monta sem dado; bloco mostra "falta: NF"; cartão de conferência DAS com competência
  diferente mostra a faixa. Sem documento real nos testes.
- Smoke no ar: cadastrar uma pessoa de teste, subir um comprovante Sicredi real, um DAS
  real e uma NF real, conferir a leitura, salvar, ver a Caixa descontar, apagar o teste.

## Fora deste desenho, anotado para depois

- Aviso de DAS a vencer (a Caixa poderia listar "DAS da Josie vence quinta").
- Relatório mensal para o contador (por pessoa: NF + DAS + comprovantes, zip ou PDF).
- Reaproveitar aliases para sugerir o funcionário pelo destinatário do Pix.
