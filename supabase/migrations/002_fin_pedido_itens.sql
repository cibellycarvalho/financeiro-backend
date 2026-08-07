-- Task: Itens por pedido de fornecedor + remoção de prazo_combinado
-- Criado em: 2026-08-07

-- ============================================================================
-- Tabela: fin_pedido_itens
-- ============================================================================
CREATE TABLE fin_pedido_itens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pedido_id UUID NOT NULL REFERENCES fin_pedidos_fornecedor(id) ON DELETE CASCADE,
  produto TEXT NOT NULL,
  quantidade NUMERIC(12,2) NOT NULL CHECK (quantidade > 0),
  valor_unitario NUMERIC(12,2) NOT NULL CHECK (valor_unitario >= 0),
  valor_total NUMERIC(12,2) GENERATED ALWAYS AS (quantidade * valor_unitario) STORED,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_pedido_itens_pedido_id ON fin_pedido_itens(pedido_id);

-- ============================================================================
-- fin_pedidos_fornecedor: remover prazo_combinado (não é mais usado —
-- só data da compra e data do pagamento)
-- ============================================================================
ALTER TABLE fin_pedidos_fornecedor DROP COLUMN IF EXISTS prazo_combinado;

-- ============================================================================
-- Row Level Security (RLS) — mesmo padrão de fin_pedidos_fornecedor
-- ============================================================================
ALTER TABLE fin_pedido_itens ENABLE ROW LEVEL SECURITY;

CREATE POLICY "fin_select" ON fin_pedido_itens FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));

CREATE POLICY "fin_write" ON fin_pedido_itens FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
