-- Conciliação por extrato OFX (27/10/2026). Cada linha do extrato vira um
-- movimento; o sistema sugere com o que ele casa (conta a pagar, pagamento a
-- fornecedor, pagamento de funcionário, repasse do Mercado Pago) e ela confirma.
CREATE TABLE IF NOT EXISTS fin_extrato_movimentos (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conta_bancaria_id uuid NOT NULL REFERENCES fin_contas_bancarias(id),
  fitid             text NOT NULL,
  data              date NOT NULL,
  valor             numeric(12,2) NOT NULL,
  descricao         text,
  status            text NOT NULL DEFAULT 'novo'
                    CHECK (status IN ('casado', 'sugerido', 'novo', 'ignorado')),
  casado_tipo       text,
  casado_id         uuid,
  casado_texto      text,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (conta_bancaria_id, fitid)
);
CREATE INDEX IF NOT EXISTS fin_extrato_movimentos_data ON fin_extrato_movimentos (conta_bancaria_id, data);
ALTER TABLE fin_extrato_movimentos ENABLE ROW LEVEL SECURITY;
