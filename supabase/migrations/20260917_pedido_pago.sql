-- Caixinha "pago" no pedido (pedido da Cibelly, 17/09/2026).
--
-- Pagamento a fornecedor era só um registro corrido de valores e datas
-- (migração 005), e a Caixa da Semana distribuía do pedido mais antigo para o
-- mais novo. Mas ela paga pedido específico — o Pix de 49.310 de 14/09 é o de
-- 10/08 mais o de 11/08. Com a distribuição automática o vencido saía errado.
--
-- pago_em: o pedido foi marcado como pago nesse dia. Pedido marcado consome o
-- próprio valor do total pago; o que sobra continua descendo do mais antigo.
-- pedido_id: o pagamento que a caixinha lançou para aquele pedido.
ALTER TABLE fin_pedidos_fornecedor ADD COLUMN IF NOT EXISTS pago_em DATE;

ALTER TABLE fin_pagamentos_fornecedor
  ADD COLUMN IF NOT EXISTS pedido_id UUID REFERENCES fin_pedidos_fornecedor(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_pagamentos_fornecedor_pedido_id ON fin_pagamentos_fornecedor(pedido_id);
