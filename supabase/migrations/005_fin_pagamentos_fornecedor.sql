-- Task: Pagamentos deixam de ser vinculados a um pedido específico e passam
-- a ser um registro único por fornecedor (não existe regra de pagar pedido
-- por pedido). Cria a nova tabela e migra o histórico existente preservando
-- valor e data.
-- Criado em: 2026-08-07

CREATE TABLE fin_pagamentos_fornecedor (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fornecedor_id UUID NOT NULL REFERENCES fin_fornecedores(id) ON DELETE CASCADE,
  valor NUMERIC(12,2) NOT NULL CHECK (valor > 0),
  data_pagamento DATE NOT NULL,
  criado_por UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_pagamentos_fornecedor_fornecedor_id ON fin_pagamentos_fornecedor(fornecedor_id);

ALTER TABLE fin_pagamentos_fornecedor ENABLE ROW LEVEL SECURITY;

CREATE POLICY "fin_select" ON fin_pagamentos_fornecedor FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));

CREATE POLICY "fin_write" ON fin_pagamentos_fornecedor FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));

-- Backfill: cada pagamento que já existia vinculado a um pedido vira um
-- pagamento geral do fornecedor daquele pedido, com o mesmo valor e data.
INSERT INTO fin_pagamentos_fornecedor (fornecedor_id, valor, data_pagamento, criado_por, created_at)
SELECT p.fornecedor_id, pg.valor, pg.data_pagamento, pg.criado_por, pg.created_at
FROM fin_pedido_pagamentos pg
JOIN fin_pedidos_fornecedor p ON p.id = pg.pedido_id;
