-- Task: Preenche retroativamente o histórico de pagamentos para pedidos
-- que já tinham valor_pago > 0 antes da fin_pedido_pagamentos existir.
-- Criado em: 2026-08-07

INSERT INTO fin_pedido_pagamentos (pedido_id, valor, data_pagamento, created_at)
SELECT p.id, p.valor_pago, COALESCE(p.data_pagamento, p.data_pedido), COALESCE(p.updated_at, now())
FROM fin_pedidos_fornecedor p
WHERE p.valor_pago > 0
  AND NOT EXISTS (
    SELECT 1 FROM fin_pedido_pagamentos pg WHERE pg.pedido_id = p.id
  );
