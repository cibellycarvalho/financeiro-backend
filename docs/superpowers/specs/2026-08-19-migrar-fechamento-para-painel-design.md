# Migrar o Fechamento e o Lucro Real do CRM para o Painel Financeiro

**Data:** 2026-08-19
**Repos afetados:** `financeiro-backend`, `financeiro-frontend`, `ml-seller-api`, `ml-seller-app`

## Contexto

A Cibelly pediu, mais de uma vez, que "a parte financeira saia do CRM e vá para o
Painel Financeiro". O assunto chegou a ser o tema de um brainstorm em agosto, mas a
conversa derivou para o que era mais urgente (canceladas, CMV, Lucro Real, redesenho
do Dashboard) e a migração nunca foi desenhada nem descartada.

O critério que faltava apareceu em 19/08, quando ela reclamou de excesso de
informação na tela: **o Dashboard do CRM é tela de operação diária** — o que vendeu,
o que mudou, o que precisa de ação. **O detalhamento financeiro é do Painel
Financeiro** — fechamento mensal, composição, conferência.

Vale registrar a correção que veio junto: perguntada sobre quais cards usa, ela
respondeu que usa todos os 18. A tela não estava pesada por ter muitos números.
**O Dashboard não perde nada nesta migração.**

## Escopo

**Dentro:** a tela de Fechamento (compras, fretes, montagem, despesas, estoque
mensal) e a tela de Lucro Real.

**Fora:** o Dashboard do CRM e seus cards; Custos de Produtos; qualquer mudança de
cálculo. Nenhum número muda de valor nesta migração — só de endereço.

## O que já existe (levantado, não suposto)

**No CRM:** `routes/fechamento.py` (CRUD puro sobre seis tabelas `fechamento_*`),
`routes/estoque_mensal.py`, `routes/lucro_real.py`, e as telas `Fechamento.jsx` e
`FechamentoLucroReal.jsx`.

**No Painel:** Contas a Pagar, Fornecedores, Repasses ML, Dashboard e Admin, sobre
tabelas `fin_*`.

**Os dois usam o MESMO banco Supabase** (projeto `tywirfmaosfztcmalbno`) e o **mesmo
login** (JWT ES256 do mesmo projeto). Isso é o que torna a migração barata: nenhum
dado se move, e ninguém precisa de conta nova.

## Decisões

### O Fechamento migra inteiro; do Lucro Real, só a tela

`fechamento.py` e `estoque_mensal.py` dependem apenas do banco — nada de Mercado
Livre. Vão para o backend financeiro, que é o dono natural desse tipo de dado.

`lucro_real.py` depende de `fetch_resultado`, `db_queries.get_cancelados` e do
seletor multi-loja — ou seja, da integração inteira com o ML, que só existe no CRM.
**O cálculo fica onde está.** Só a tela muda de casa e passa a chamar o CRM de lá.

A alternativa seria duplicar a integração com o ML no backend financeiro. Duas
cópias da parte mais complexa do sistema, divergindo com o tempo — descartada.

### A trava por loja é redesenhada, não copiada

Este é o ponto de risco da migração.

Os dois sistemas descrevem o usuário de formas incompatíveis:

| | CRM | Painel Financeiro |
|---|---|---|
| Contexto | `{id, email, role, conta_ml}` | `{user_id, email, fin_role}` |
| Trava por loja | `role != "admin"` força a `conta_ml` do próprio usuário | **não existe** |

As rotas de fechamento resolvem a conta com
`request.args.get("conta_ml") or g.user["conta_ml"]`, e travam o não-admin na
própria loja. Movidas como estão para o backend financeiro, **essa trava deixa de
existir** — `conta_ml` e `role` não estão no contexto de lá.

Isso não daria erro em tela nenhuma. Gravaria na loja errada, em silêncio.

**Decisão dela:** o Painel passa a ler a loja do **mesmo lugar que o CRM** — os
metadados do usuário no Supabase. Uma fonte só de verdade: mudar o acesso num lugar
vale nos dois sistemas. `fin_role` continua existindo para o que é específico do
Painel (quem administra o financeiro), sem se misturar com "de qual loja".

### Seletor de loja: seguir o padrão do Painel

O Painel não tem seletor global; `RepasesML.jsx` resolve com um seletor local. O
Fechamento segue esse padrão em vez de importar o seletor multi-loja do CRM —
trazer um mecanismo global para um app que não o tem é mudança maior que a migração.

### Transição sem janela de indisponibilidade

As telas continuam funcionando no CRM durante toda a migração. Só no fim o menu do
CRM passa a apontar para o Painel e a rota antiga redireciona — mesmo padrão usado
no Quadro de Tarefas em 18/08, que preservou os links salvos da equipe.

## Ordem de execução

1. **Permissão primeiro.** O backend financeiro passa a ler `conta_ml` dos metadados
   do Supabase e a expor a mesma trava do CRM. Sem isso, nada mais se move.
2. **Fechamento no backend financeiro** — rotas portadas, com testes cobrindo a
   trava por loja antes de qualquer tela existir.
3. **Tela de Fechamento no Painel**, com seletor local de loja.
4. **CORS do CRM** liberando `financeiro.cravelli.com.br`.
5. **Tela de Lucro Real no Painel**, chamando o endpoint do CRM.
6. **Corte:** menu do CRM aponta pro Painel, rotas antigas redirecionam.

Os passos 1–2 são os únicos que mexem em fronteira de segurança. Os demais são
mudança de endereço.

## Testes

- Não-admin não consegue gravar fechamento de outra loja, nem passando `conta_ml`
  na query — o teste que hoje protege isso no CRM (`routes/fechamento.py::_conta`)
  precisa existir do lado do Painel **antes** da porta abrir.
- Usuário sem `conta_ml` nos metadados recebe 400, não grava na loja de outro.
- Lucro Real no Painel devolve os mesmos números que devolvia no CRM, para o mesmo
  mês e a mesma loja — comparação lado a lado antes do corte.
- Redirecionamento da rota antiga leva à tela nova.

## Riscos

- **A trava de acesso é o risco real.** Uma migração de tela que silenciosamente
  remove uma fronteira de segurança é pior que não migrar. Por isso ela é o passo 1
  e tem teste antes de código de tela.
- **O Painel passa a depender do CRM** para a tela de Lucro Real. Se o CRM cair, a
  tela para de carregar — e precisa dizer isso, em vez de mostrar tela vazia.
- **Conciliação bancária: adiada, decisão tomada em 19/08.** A spec de OFX
  (`2026-08-10-conciliacao-bancaria-ofx-design.md`) segue sem implementação. A
  usuária levantou fazer via **Open Finance** em vez de importar arquivo, e a
  resposta é que o Pluggy — a tentativa que falhou — já era um agregador de Open
  Finance: a parede não foi técnica, foi contrato e habilitação (trial expirado,
  produção nunca solicitada, só sandbox). Fica registrado o argumento que importa
  para quando o assunto voltar: **o caro é o motor de conciliação** (casar
  transação com lançamento, tratar o que não casa, revisar antes de gravar), e
  ele é o mesmo vindo de OFX ou de API. Trocar a fonte depois não custa refazer.
  Ela optou por **pular o assunto por ora**, e a migração segue sem depender dele.

## Fora de escopo, registrado para não se perder

O Dashboard do CRM continua com os 18 cards. Se um dia a conversa voltar para
enxugá-lo, o critério está no começo desta spec — mas a usuária já disse que usa
todos, e essa informação vale mais que a intuição de quem olha de fora.
