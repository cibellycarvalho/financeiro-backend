-- supabase/migrations/20260917_funcionarios.sql
-- Aba Funcionários: pagamento, DAS e NF por pessoa e por mês de competência.
-- Desenho em docs/superpowers/specs/2026-09-17-funcionarios-design.md.
-- Uma tabela para os três tipos: o mês de uma pessoa é "as linhas com aquela
-- competência", e "o que falta?" é um GROUP BY tipo.

CREATE TABLE IF NOT EXISTS fin_funcionarios (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nome TEXT NOT NULL,
  cnpj TEXT,                              -- só dígitos; opcional
  valor_combinado NUMERIC(12,2),          -- pré-preenche o pagamento; opcional
  ativo BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fin_funcionario_lancamentos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  funcionario_id UUID NOT NULL REFERENCES fin_funcionarios(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL CHECK (tipo IN ('pagamento', 'das', 'nf')),
  competencia DATE NOT NULL,              -- sempre dia 1 do mês do serviço
  valor NUMERIC(12,2),                    -- NF pode vir sem valor lido; DAS/pagamento exigem (regra na rota)
  vencimento DATE,                        -- DAS
  pago_em DATE,                           -- pagamento e DAS; NULL = em aberto
  numero_nf TEXT,                         -- NF
  id_transacao TEXT,                      -- E2E do Pix (pagamento e comprovante do DAS)
  arquivo_path TEXT,                      -- Pix do pagamento / arquivo da NF
  boleto_path TEXT,                       -- DAS: o boleto
  comprovante_path TEXT,                  -- DAS: o comprovante
  observacao TEXT,
  criado_por UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_func_lanc_func_comp
  ON fin_funcionario_lancamentos(funcionario_id, competencia);
CREATE INDEX IF NOT EXISTS idx_func_lanc_pago_em
  ON fin_funcionario_lancamentos(pago_em) WHERE pago_em IS NOT NULL;
-- O mesmo Pix não entra duas vezes aqui. Entre esta tabela e a de fornecedores
-- a checagem é na rota (consulta as duas) — índice não atravessa tabela.
CREATE UNIQUE INDEX IF NOT EXISTS idx_func_lanc_id_transacao
  ON fin_funcionario_lancamentos(id_transacao) WHERE id_transacao IS NOT NULL;
-- Um DAS e uma NF por competência; pagamento pode repetir (adiantamento + saldo).
CREATE UNIQUE INDEX IF NOT EXISTS idx_func_lanc_um_por_mes
  ON fin_funcionario_lancamentos(funcionario_id, competencia, tipo) WHERE tipo IN ('das', 'nf');

ALTER TABLE fin_funcionarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_funcionario_lancamentos ENABLE ROW LEVEL SECURITY;

-- Mesmas policies das outras fin_* (005_fin_pagamentos_fornecedor.sql).
DROP POLICY IF EXISTS "fin_select" ON fin_funcionarios;
CREATE POLICY "fin_select" ON fin_funcionarios FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
DROP POLICY IF EXISTS "fin_write" ON fin_funcionarios;
CREATE POLICY "fin_write" ON fin_funcionarios FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));

DROP POLICY IF EXISTS "fin_select" ON fin_funcionario_lancamentos;
CREATE POLICY "fin_select" ON fin_funcionario_lancamentos FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
DROP POLICY IF EXISTS "fin_write" ON fin_funcionario_lancamentos;
CREATE POLICY "fin_write" ON fin_funcionario_lancamentos FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
