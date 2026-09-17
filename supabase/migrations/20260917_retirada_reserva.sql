-- Quanto ela tirou da reserva na semana. É informação, não entra na sobra:
-- decisão dela em 17/09/2026 (a sobra responde "as vendas cobriram a semana?").
ALTER TABLE fin_planejamento_semana ADD COLUMN IF NOT EXISTS retirada_reserva NUMERIC(12,2);
