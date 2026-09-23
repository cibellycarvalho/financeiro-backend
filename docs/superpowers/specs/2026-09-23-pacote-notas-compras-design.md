# Pacote de notas e comprovantes da compra

Desenho validado com a Cibelly em 23/09/2026.

## O problema

Quando a contabilidade pede os documentos do mês, ela precisa garimpar: a nota
fiscal não tem onde ficar no painel, e o comprovante do Pix quase nunca diz qual
compra pagou. Dos ~30 pagamentos a fornecedor lançados desde agosto/2026, só 4
estão amarrados a um pedido.

O jeito como ela compra também não é o mesmo do calendário do banco: **o
pagamento é sempre referente a um pedido**, e a Flávia tem 30 dias de prazo — o
Pix de setembro paga a compra de 17/08. Um pacote organizado pela data do Pix
separaria a nota do comprovante dela.

## O que vamos construir

1. Clipe para anexar a **nota fiscal** na compra (Fornecedores e Contas a Pagar).
2. Tela para **amarrar os Pix antigos** à compra que eles pagaram.
3. Botão **"Baixar mês"**: um .zip com uma pasta por compra, contendo nota,
   pedido e comprovante, mais um `resumo.xlsx`.

Fora de escopo: vendas. Ela pediu explicitamente só compras. O relatório de
vendas continua no CRM.

## 1. Onde os arquivos ficam

**Fornecedores › compra (pedido):** ganha um segundo clipe, 📎 Nota fiscal, ao
lado do clipe do pedido que já existe. Coluna nova `nf_path` em
`fin_pedidos_fornecedor`, gravada pelo mesmo caminho dos anexos de hoje
(`pendentes/` no Storage → mover no salvar). Uma nota por compra; subir outra
pergunta "substituir?", como o DAS da aba Funcionários.

**Contas a Pagar:** ganha dois clipes por conta — nota fiscal e comprovante.
Colunas novas `nf_path` e `comprovante_path` em `fin_contas_pagar`.

**Nada é obrigatório.** Regra dela: *"às vezes não vou ter eles em mãos"*. Nota,
comprovante e amarração são opcionais em qualquer tela; a falta aparece como
informação no `resumo.xlsx` ("sem nota", "sem comprovante"), nunca como
impedimento de salvar.

## 2. Amarrar o Pix à compra

Hoje `fin_pagamentos_fornecedor.pedido_id` aceita **um** pedido por pagamento, e
foi criado para a caixinha "Pago" do pedido. Mas um Pix pode cobrir mais de uma
compra — o de R$ 49.310 de 14/09 pagou os pedidos de 10/08 e 11/08.

**Estrutura:** tabela de ligação `fin_pagamento_pedido (pagamento_id, pedido_id,
valor)`. O `pedido_id` que já existe é migrado para ela e deixa de ser lido — uma
fonte de verdade só. A caixinha "Pago" do pedido passa a gravar na tabela nova.

Regra: a soma dos valores amarrados a um pagamento não pode passar do valor do
pagamento, nem a soma amarrada a uma compra passar do valor da compra. Amarração
parcial é permitida (adiantamento).

**Tela "Pix sem compra"**, em Fornecedores: lista os pagamentos que ainda não
têm compra amarrada e, ao lado, as compras em aberto do mesmo fornecedor. Ela
marca uma ou mais compras e confirma; o valor é distribuído da mais antiga para
a mais nova, e ela pode editar cada valor. Desfazer é um clique.

A tela existe para acertar o histórico de agosto/setembro, mas continua
disponível depois — Pix solto vai acontecer de novo.

## 3. Baixar o mês

Botão **"Baixar mês"** em Fornecedores, com seletor de mês. O backend monta o
.zip lendo os arquivos do Storage e devolve em streaming.

```
2026-08/
  FLAVIA/
    17-08 pedido 1234/
      nota-fiscal.pdf
      pedido.pdf
      comprovante 22-09 R$ 40.000,00.pdf
  ALTOMEX/
    23-09 pedido 7/
      ...
  CONTAS A PAGAR/
    21-09 Embalagens/
      nota-fiscal.pdf
      comprovante.pdf
  resumo.xlsx
```

**O mês é o da compra, não o do Pix.** O comprovante entra na pasta da compra
mesmo tendo sido pago no mês seguinte. É a tradução do prazo de 30 dias: o mês
de agosto vem inteiro, com os pagamentos que só aconteceram em setembro.

Um comprovante que pagou duas compras aparece nas duas pastas, com o valor que
coube a cada uma no nome do arquivo — a pasta da compra é a unidade, e repetir o
arquivo custa menos que mandar a contabilidade procurar.

**resumo.xlsx** — uma linha por compra: fornecedor, data da compra, número do
pedido, valor, valor pago, data(s) do pagamento, em aberto, tem nota (sim/não),
tem comprovante (sim/não). É por ele que ela vê o que falta antes de mandar.

Pasta de compra sem arquivo nenhum entra assim mesmo, vazia, porque a linha no
resumo precisa ter um lugar correspondente no zip.

## Erros e limites

- Arquivo que falha ao baixar do Storage não derruba o zip: entra um
  `FALTOU <nome>.txt` na pasta, com o motivo, e o resumo marca a linha.
- Mês sem compra nenhuma: o botão responde com aviso na tela, não com zip vazio.
- O zip é montado por mês. Se um mês ficar grande demais para a memória do
  serviço, o arquivo é escrito em disco temporário antes de sair — decidir na
  implementação, medindo com agosto/2026.

## Testes

- Backend: o mês traz a compra de agosto paga em setembro; comprovante em duas
  compras aparece nas duas pastas; falha de Storage vira `FALTOU`; soma amarrada
  maior que o pagamento é recusada; migração do `pedido_id` antigo preserva as 4
  amarrações existentes.
- Frontend: subir nota não exige comprovante e vice-versa; amarrar e desfazer;
  a caixinha "Pago" continua funcionando depois da mudança de estrutura.
