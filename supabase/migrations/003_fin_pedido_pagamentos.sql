-- Task: Histórico de pagamentos por pedido de fornecedor
-- Criado em: 2026-08-07

-- ============================================================================
-- Tabela: fin_pedido_pagamentos
-- ============================================================================
CREATE TABLE fin_pedido_pagamentos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pedido_id UUID NOT NULL REFERENCES fin_pedidos_fornecedor(id) ON DELETE CASCADE,
  valor NUMERIC(12,2) NOT NULL CHECK (valor > 0),
  data_pagamento DATE NOT NULL,
  criado_por UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_pedido_pagamentos_pedido_id ON fin_pedido_pagamentos(pedido_id);

-- ============================================================================
-- Row Level Security (RLS) — mesmo padrão de fin_pedido_itens
-- ============================================================================
ALTER TABLE fin_pedido_pagamentos ENABLE ROW LEVEL SECURITY;

CREATE POLICY "fin_select" ON fin_pedido_pagamentos FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));

CREATE POLICY "fin_write" ON fin_pedido_pagamentos FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
