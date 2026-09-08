# Upload do pedido de compra com leitura automática

**Data:** 2026-09-08
**Repos afetados:** `financeiro-backend`, `financeiro-frontend`
**Decidido com a Cibelly em:** 08/09/2026, na mesma conversa em que a conta da Flavia foi conciliada à mão

## Contexto

Hoje, lançar um pedido de compra na tela de Fornecedores é digitar produto por
produto. Um pedido da Flavia tem de 2 a 10 itens; em agosto foram 9 pedidos, 43
itens. Na conciliação de 08/09 apareceram, só na Flavia: uma nota inteira que
faltava (R$ 30.150), dois Pix que faltavam (R$ 62.000) e duas datas erradas —
todos erros de digitação ou de esquecimento, não de cálculo.

Ela pediu, com as próprias palavras:

> "quero que o painel tenha um campo pra eu fazer upload dos pedidos de compra e
> ele preenche automático. Eu abro o fornecedor e subo o pedido dentro dele. Depois
> o sistema me pede confirmação se o pedido é do fornecedor X mesmo ou é do Y, e me
> pergunta se já foi pago. Se foi pago, já lança o pagamento lá no pé da página."

Decisões tomadas na conversa (uma pergunta por vez):

| Pergunta | Resposta dela |
|---|---|
| Formato dos pedidos | **foto ou PDF** — layouts variam por fornecedor |
| Quando diz "já paguei", o que lança? | **sobe o comprovante do Pix junto**; valor e data vêm de lá |
| Pix diferente do total do pedido | **lança o valor do Pix como está**; o saldo devedor cuida do resto |
| Como ler o arquivo | **IA de visão (Claude) no backend do Painel** — não OCR+regras, não o agente do CRM |

## Escopo

**Dentro:** botão de upload dentro do fornecedor; leitura do pedido (PDF/foto)
por IA; cartão de conferência editável; detecção de pedido repetido; pergunta
"já foi pago?"; leitura do comprovante Pix; lançamento do pagamento; anexo dos
dois arquivos no pedido e no pagamento.

**Fora:** ler extrato bancário; ler vários pedidos num arquivo só; cadastrar
fornecedor novo a partir do documento; qualquer mudança no cálculo de saldo. O
fluxo manual ("+ Novo pedido", "+ Registrar pagamento") continua igual e é o
fallback quando a leitura falha.

## O que já existe (levantado, não suposto)

- `fin_pedidos_fornecedor` (data, valor_total, descricao_produtos, status…) e
  `fin_pedido_itens` (produto, quantidade, valor_unitario, valor_total gerado).
- `fin_pagamentos_fornecedor` (valor, data_pagamento) — pagamento é **por
  fornecedor**, não por pedido; saldo = Σ pedidos − Σ pagamentos.
- Endpoints em `routes/fornecedores.py`: criar pedido com itens, editar, excluir,
  registrar/editar/excluir pagamento. Guardas `require_auth` / `require_admin`.
- Frontend `src/pages/Fornecedores.jsx`: formulário de novo pedido com N itens
  (`ITEM_VAZIO`, `totalDoPedido`), painel de pagamentos no pé, filtro por mês,
  PDF com subtotal por pedido.
- Não há cliente da Anthropic nem de Supabase Storage no `financeiro-backend`
  hoje. `requirements.txt` tem `requests`, `psycopg2`, `PyJWT`, `pytest`.
- Comprovantes Sicredi trazem o ID da transação no formato
  `E81099491` + `AAAAMMDDHHMMSS` — a data/hora do Pix está ali, mesmo quando o
  layout muda.

## Fluxo (o que ela vê)

Dentro do fornecedor, ao lado de "+ Novo pedido": **"📎 Subir pedido de compra"**.
Aceita PDF, JPG, PNG (um arquivo por vez; limite 10 MB).

1. Sobe o arquivo → spinner "Lendo o pedido…" (3–8 s).
2. Aparece o **cartão de conferência**, sem nada salvo ainda:
   - "Esse pedido é da **[Flavia ▾]**?" — dropdown com todos os fornecedores
     ativos, pré-selecionado com a sugestão da IA; se a IA não reconheceu, vem o
     fornecedor que está aberto.
   - Nº do pedido, data do pedido — editáveis.
   - Tabela de itens (produto, qtd, unit., total) — a **mesma** tabela do "Novo
     pedido", já preenchida, com "+ Adicionar produto" e ✕ por linha.
   - Total do pedido calculado a partir dos itens (não o que a IA disse).
   - Se o nº do pedido já existe **nesse fornecedor**: faixa amarela "Esse pedido
     já está lançado em DD/MM/AAAA. Lançar de novo?" — salvar continua possível.
   - Se a soma dos itens difere do total que a IA leu no documento em mais de
     R$ 0,05: faixa amarela "A soma dos itens (R$ X) não bate com o total do
     documento (R$ Y). Confira."
   - "Já foi pago?" ( ) Não ( ) Sim
3. **Não** → botão "Salvar pedido". Fim.
4. **Sim** → aparece "📎 Subir comprovante do Pix". Sobe → spinner → bloco:
   > Pix de **R$ 30.000,00** em **24/08/2026** para **MIAO ATACADISTA**
   > → cobre R$ 30.000,00 de R$ 30.150,00 deste pedido
   - Valor e data editáveis.
   - Se o destinatário do Pix não bate com o fornecedor escolhido (pelo cadastro
     de "contas conhecidas", ver abaixo): faixa amarela "Esse Pix foi para X, que
     não está associado a Flavia. É isso mesmo?"
   - Se o E2E já existe em `fin_pagamentos_fornecedor.id_transacao`: faixa
     vermelha "Esse comprovante já foi lançado em DD/MM (R$ X)". Salvar segue
     possível, mas o botão muda para "Salvar mesmo assim".
   - Botão "Salvar pedido e pagamento".
5. Ao salvar: pedido criado, pagamento criado (aparece no painel do pé como se
   fosse manual), os dois arquivos anexados (clipe 📎 na linha do pedido e na
   linha do pagamento; abre em nova aba).
6. A tela pula para o mês do pedido (comportamento já existente do filtro).

Se a leitura falhar (ver "Quando dá errado"), o cartão abre **vazio**, com a
imagem/PDF em preview ao lado, e ela preenche à mão. O arquivo continua sendo
anexado ao salvar.

## Backend

### Endpoints novos (só leem, nunca gravam)

`POST /api/fornecedores/<id>/pedidos/ler` — `multipart/form-data`, campo
`arquivo`. Requer `fin_admin`. Devolve:

```json
{
  "fornecedor_sugerido_id": "uuid ou null",
  "texto_vendedor": "Flavia",
  "numero_pedido": "2026/5999",
  "data_pedido": "2026-08-24",
  "itens": [{"produto": "CABO HDMI FIBRA 8K 20M", "quantidade": 150, "valor_unitario": 100.0}],
  "total_documento": 30150.0,
  "pedido_existente": {"id": "uuid", "data_pedido": "2026-08-24"} | null,
  "arquivo_token": "token opaco"
}
```

`POST /api/fornecedores/<id>/pagamentos/ler` — mesmo formato de entrada. Devolve:

```json
{
  "valor": 30000.0,
  "data_pagamento": "2026-08-24",
  "destinatario": "MIAO ATACADISTA E REPRESENTACOES LTDA",
  "id_transacao": "E8109949120260824004025qquKDYh56",
  "fornecedor_sugerido_id": "uuid ou null",
  "pagamento_existente": {"id": "uuid", "data_pagamento": "…", "valor": 0} | null,
  "arquivo_token": "token opaco"
}
```

`arquivo_token`: o backend já subiu o arquivo para o Storage durante a leitura
(pasta `pendentes/`); o token identifica esse objeto. Ao salvar, o backend move
o objeto para a pasta definitiva e grava o caminho. Objetos em `pendentes/` com
mais de 24 h são apagados **no início da próxima chamada a `/ler`** — sem cron,
sem job; o custo é uma listagem por leitura. Isso evita subir o arquivo duas vezes
e evita gravar anexo de pedido que ela cancelou.

No banco fica `arquivo_path` (caminho no bucket). A URL assinada só é gerada
pelo endpoint `/anexo`, no clique.

### Endpoints existentes, campos novos

- `POST /pedidos` ganha `numero_pedido` (opcional) e `arquivo_token` (opcional).
- `POST /pagamentos` ganha `id_transacao` (opcional) e `arquivo_token` (opcional).
- `GET /pedidos` e `GET /pagamentos` passam a devolver `numero_pedido`,
  `id_transacao`, `arquivo_path` (a tela só usa para saber se mostra o 📎).
- `GET /pedidos/<pedido_id>/anexo` e `GET /pagamentos/<pagamento_id>/anexo`
  devolvem `{"url": "<URL assinada, 1 h>"}`. A tela chama **no clique** do 📎 e
  abre em nova aba — assinar cada anexo em toda listagem custaria uma chamada
  ao Storage por linha.

### Módulo `leitura_documento.py` (novo)

Uma função por tipo: `ler_pedido(bytes, mime) -> dict` e
`ler_comprovante(bytes, mime) -> dict`. Cada uma monta a mensagem para a API da
Anthropic (documento como bloco `document` para PDF ou `image` para foto), pede
JSON com esquema fixo (via tool use com `input_schema`, para não depender de
parse de texto), valida o JSON e devolve. Modelo: o mais capaz disponível para
visão de documento no momento da implementação (consultar a skill `claude-api`
antes de escrever; a escolha fica em `config.LEITURA_MODEL` para trocar sem
deploy de código).

**Pós-processamento fora da IA** (regra de ouro: tudo que dá para calcular, não
se pergunta ao modelo):
- `data_pagamento` de comprovante Sicredi: se `id_transacao` casa com
  `^E\d{8}(\d{14})`, a data vem **dali**, não do que a IA leu.
- `total_documento` só serve para a faixa de aviso; o `valor_total` gravado é
  Σ itens, como hoje.
- Normalização de números: a IA devolve número, não string; o backend rejeita
  item sem `quantidade > 0`.

### Sugestão de fornecedor

Tabela nova `fin_fornecedor_aliases` (`fornecedor_id`, `alias TEXT`,
`alias_norm TEXT`, `origem TEXT CHECK (origem IN ('vendedor','destinatario'))`).
`alias_norm` é o alias em minúsculas, sem acento e com espaços colapsados,
calculado **em Python** (`unicodedata`) — não com `unaccent()` do Postgres, que
não é imutável e por isso não entra em índice único. Match por
`alias_norm = normalizar(texto)`. Semeada na migração com o que
já se sabe: Flavia ← `Flavia` (vendedor), `Multivale Montagem E Estruturas Ltda`
e `MIAO Atacadista e Representacoes Ltda` (destinatário). **Aprende sozinha**: ao
salvar com um fornecedor diferente da sugestão (ou sem sugestão), o vendedor /
destinatário lido vira alias daquele fornecedor. Sem tela de administração —
YAGNI; se um alias ficar errado, corrige-se no banco.

### Armazenamento dos arquivos

Supabase Storage, bucket **privado** `fornecedores`. Caminho
`<fornecedor_id>/pedidos/<pedido_id>.<ext>` e
`<fornecedor_id>/pagamentos/<pagamento_id>.<ext>`. O backend gera URL assinada
(1 h) quando a lista é pedida — o link da tela nunca é público. Cliente HTTP
simples com `requests` contra a API REST do Storage usando
`SUPABASE_SERVICE_KEY` (já existe em `config.py`); sem SDK novo.

### Migração `20260908_upload_pedido_compra.sql`

```sql
ALTER TABLE fin_pedidos_fornecedor
  ADD COLUMN numero_pedido TEXT,
  ADD COLUMN arquivo_path TEXT;
CREATE INDEX idx_pedidos_fornecedor_numero
  ON fin_pedidos_fornecedor(fornecedor_id, numero_pedido);

ALTER TABLE fin_pagamentos_fornecedor
  ADD COLUMN id_transacao TEXT,
  ADD COLUMN arquivo_path TEXT;
CREATE UNIQUE INDEX idx_pagamentos_fornecedor_id_transacao
  ON fin_pagamentos_fornecedor(id_transacao) WHERE id_transacao IS NOT NULL;

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

INSERT INTO storage.buckets (id, name, public) VALUES ('fornecedores', 'fornecedores', false);
```

Um alias pertence a um fornecedor só (índice único por origem + texto
normalizado): se "Multivale" fosse alias de dois fornecedores, a sugestão seria
chute. Ao aprender um alias que já existe para outro fornecedor, o backend
**troca** o dono — a escolha mais recente dela vale.

`id_transacao` é único parcial: o mesmo comprovante não entra duas vezes por
acidente — a tela avisa antes, o banco garante. `numero_pedido` **não** é único:
fornecedores diferentes podem repetir numeração, e ela pode ter motivo para
lançar de novo; a tela só avisa.

### Configuração

`ANTHROPIC_API_KEY` (obrigatória para os endpoints `/ler`; sem ela, eles
respondem 503 com mensagem clara e o resto do sistema não é afetado) e
`LEITURA_MODEL` (opcional, com default no código) — as duas no EasyPanel do
`financeiro-backend`. `anthropic` entra no `requirements.txt`.

## Frontend

`src/pages/Fornecedores.jsx` já tem 1.100 linhas. O fluxo novo entra como
componente próprio, `src/components/UploadPedidoCompra.jsx`, que recebe
`fornecedores`, `fornecedorSel` e um `onSalvo()`; a página só monta o botão e o
componente. A tabela de itens do "Novo pedido" vira componente compartilhado
(`ItensPedidoForm`) usado pelos dois caminhos — mesma aparência, mesma validação,
um lugar só para manter.

Estados do componente: `ocioso → lendoPedido → conferindo → lendoComprovante →
conferindoPagamento → salvando`. Cada faixa de aviso é derivada da resposta do
backend, não recalculada na tela.

Anexos: nas linhas de pedido e de pagamento, um 📎 que abre `arquivo_url` em
nova aba quando existir.

## Quando dá errado

| Situação | O que acontece |
|---|---|
| Arquivo > 10 MB ou tipo não aceito | Recusado na tela antes de subir, com mensagem |
| IA não devolveu JSON válido / itens vazios | Cartão abre vazio com preview do arquivo; anexo preservado |
| Σ itens ≠ total do documento | Faixa amarela; salvar permitido |
| Nº do pedido já existe no fornecedor | Faixa amarela; salvar permitido |
| E2E já lançado | Faixa vermelha; botão "Salvar mesmo assim"; banco rejeita duplicata exata com 409 e a tela mostra |
| Destinatário do Pix não é alias do fornecedor | Faixa amarela; ao salvar, vira alias |
| API da Anthropic fora / sem chave | 503 → "Leitura automática indisponível agora. Lance à mão." — botão "+ Novo pedido" segue normal |
| Storage falhou no salvar | Pedido/pagamento **não** são gravados (tudo ou nada); mensagem pede tentar de novo |

## Testes

- `tests/test_leitura_documento.py`: respostas da IA **gravadas** (fixtures JSON)
  → valida pós-processamento (data pelo E2E, rejeição de item inválido, match de
  alias com/sem acento). Sem chamada real na suíte.
- `tests/test_fornecedores_upload.py`: endpoints `/ler` com a IA mockada; salvar
  com `arquivo_token`; 409 para E2E repetido; alias aprendido ao salvar com
  fornecedor diferente.
- Frontend: sem framework de teste hoje; verificação manual com o harness de
  preview já usado nesta sessão (mocks de API) + teste real no ar com o PDF da
  Flavia (24/08, 2026/5999) e um comprovante Sicredi — antes de dar por pronto.
- Fixtures **sintéticas**: nenhum PDF/comprovante real dela vai para o repositório.

## Fora deste desenho, anotado para depois

- Ler vários pedidos de uma vez (arrastar 5 PDFs).
- Conciliação automática "este Pix fecha quais pedidos".
- Tela para ver/editar aliases.
