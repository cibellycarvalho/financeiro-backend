-- Planejamento da Caixa da Semana no banco.
-- Saldo em conta, reserva aplicada, agenda do Mercado Pago e as escolhas de
-- "Descontar / Não descontar" moravam no localStorage: cada navegador via um
-- painel diferente, e em 17/09/2026 o saldo que a Cibelly colou sumiu da tela
-- (estava em outro aparelho). Desenho da ordem de serviço de 14/09/2026, com
-- saldo_em e ajustes_pagamento, que a tela passou a usar depois.

CREATE TABLE IF NOT EXISTS fin_planejamento_semana (
  semana DATE PRIMARY KEY,                               -- sempre a SEGUNDA-FEIRA
  saldo_conta NUMERIC(12,2),                             -- NULL = não informado (≠ zero)
  saldo_em TIMESTAMPTZ,                                  -- quando o saldo foi digitado
  reserva_aplicada NUMERIC(12,2),
  agenda JSONB NOT NULL DEFAULT '{}'::jsonb,             -- { "2026-09-14": 2280.51 }
  ajustes_pagamento JSONB NOT NULL DEFAULT '{}'::jsonb,  -- { "<pagamento_id>": true }
  informado_por UUID REFERENCES auth.users(id),
  updated_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE fin_planejamento_semana ENABLE ROW LEVEL SECURITY;

-- Sem o filtro de fin_admin das outras tabelas: o planejamento é preenchido
-- pelos dois donos do negócio (decisão da Cibelly, 14/09/2026).
DROP POLICY IF EXISTS "fin_select" ON fin_planejamento_semana;
CREATE POLICY "fin_select" ON fin_planejamento_semana FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
DROP POLICY IF EXISTS "fin_write" ON fin_planejamento_semana;
CREATE POLICY "fin_write" ON fin_planejamento_semana FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
