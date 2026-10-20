-- Entradas fora do Mercado Pago na semana (ex.: empréstimo do ML). Soma ao
-- "Disponível para comprar" da Caixa da Semana. NULL = não informado.
ALTER TABLE fin_planejamento_semana ADD COLUMN IF NOT EXISTS entradas_extras NUMERIC(12,2);
