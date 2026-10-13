-- supabase/20261013_devolucao_forma.sql
-- Devolução ganha "forma": 'dinheiro' (o fornecedor devolveu por Pix/transferência,
-- então entra na Caixa da Semana) ou 'credito' (só abate o "Ainda devo").
-- As devoluções já registradas valem como crédito, como sempre funcionaram.

ALTER TABLE fin_devolucoes_fornecedor
  ADD COLUMN IF NOT EXISTS forma text NOT NULL DEFAULT 'credito'
  CHECK (forma IN ('dinheiro', 'credito'));
