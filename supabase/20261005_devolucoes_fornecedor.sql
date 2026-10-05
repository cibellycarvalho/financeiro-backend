-- supabase/20261005_devolucoes_fornecedor.sql
-- Devolução ao fornecedor: abate o "Ainda devo" sem ser um pagamento (não sai
-- dinheiro, então não entra na Caixa da Semana nem em "Pago no mês").

CREATE TABLE IF NOT EXISTS fin_devolucoes_fornecedor (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  fornecedor_id   uuid NOT NULL REFERENCES fin_fornecedores(id),
  pedido_id       uuid REFERENCES fin_pedidos_fornecedor(id) ON DELETE SET NULL,
  valor           numeric(12,2) NOT NULL CHECK (valor > 0),
  data_devolucao  date NOT NULL,
  descricao       text,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_devolucoes_fornecedor ON fin_devolucoes_fornecedor(fornecedor_id);

ALTER TABLE fin_devolucoes_fornecedor ENABLE ROW LEVEL SECURITY;

CREATE POLICY fin_select ON fin_devolucoes_fornecedor FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
