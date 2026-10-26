-- Contas bancárias genéricas (26/10/2026): qualquer banco, quantas quiser, uma
-- marcada como principal. Nada de banco escrito no código — o sistema vai ser
-- vendido para outras lojas. Por enquanto o saldo é digitado; depois cada conta
-- ganha uma fonte (extrato OFX ou Open Finance).
CREATE TABLE IF NOT EXISTS fin_contas_bancarias (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nome       text NOT NULL,
  principal  boolean NOT NULL DEFAULT false,
  saldo      numeric(12,2),
  saldo_em   timestamptz,
  ativo      boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
-- No máximo uma principal entre as ativas.
CREATE UNIQUE INDEX IF NOT EXISTS fin_contas_bancarias_uma_principal
  ON fin_contas_bancarias (principal) WHERE principal AND ativo;
ALTER TABLE fin_contas_bancarias ENABLE ROW LEVEL SECURITY;
