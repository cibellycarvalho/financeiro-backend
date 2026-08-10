-- Task: Conciliação bancária via importação de OFX
-- Criado em: 2026-08-10

-- ============================================================================
-- Tabela: fin_extrato_transacoes
-- ============================================================================
CREATE TABLE fin_extrato_transacoes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lote_id UUID NOT NULL,
  fitid TEXT NOT NULL UNIQUE,
  tipo TEXT NOT NULL CHECK (tipo IN ('DEBIT','CREDIT')),
  valor NUMERIC(12,2) NOT NULL,
  data DATE NOT NULL,
  descricao TEXT,
  status TEXT NOT NULL DEFAULT 'pendente'
    CHECK (status IN ('pendente','conciliado','ignorado','nova_conta')),
  match_tabela TEXT CHECK (match_tabela IN ('fin_contas_pagar','fin_pedido_pagamentos','fin_repasses_ml')),
  match_id UUID,
  criado_por UUID REFERENCES auth.users(id),
  criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_extrato_lote ON fin_extrato_transacoes(lote_id);

-- ============================================================================
-- Colunas de link nas tabelas existentes
-- ============================================================================
ALTER TABLE fin_contas_pagar ADD COLUMN ofx_transacao_id UUID REFERENCES fin_extrato_transacoes(id);
ALTER TABLE fin_pedido_pagamentos ADD COLUMN ofx_transacao_id UUID REFERENCES fin_extrato_transacoes(id);
ALTER TABLE fin_repasses_ml ADD COLUMN ofx_transacao_id UUID REFERENCES fin_extrato_transacoes(id);

-- Permite origem = 'ofx' em fin_contas_pagar (contas criadas a partir da conciliação)
ALTER TABLE fin_contas_pagar DROP CONSTRAINT fin_contas_pagar_origem_check;
ALTER TABLE fin_contas_pagar ADD CONSTRAINT fin_contas_pagar_origem_check
  CHECK (origem IN ('manual','pluggy','dda','ofx'));

-- ============================================================================
-- Row Level Security (RLS) — mesmo padrão das demais tabelas fin_
-- ============================================================================
ALTER TABLE fin_extrato_transacoes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "fin_select" ON fin_extrato_transacoes FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
CREATE POLICY "fin_write" ON fin_extrato_transacoes FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
