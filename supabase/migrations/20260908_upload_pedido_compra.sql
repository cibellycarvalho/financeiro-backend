-- supabase/migrations/20260908_upload_pedido_compra.sql
-- Upload do pedido de compra com leitura por IA (spec 2026-09-08).

ALTER TABLE fin_pedidos_fornecedor
  ADD COLUMN IF NOT EXISTS numero_pedido TEXT,
  ADD COLUMN IF NOT EXISTS arquivo_path TEXT;
CREATE INDEX IF NOT EXISTS idx_pedidos_fornecedor_numero
  ON fin_pedidos_fornecedor(fornecedor_id, numero_pedido);

ALTER TABLE fin_pagamentos_fornecedor
  ADD COLUMN IF NOT EXISTS id_transacao TEXT,
  ADD COLUMN IF NOT EXISTS arquivo_path TEXT;
-- O mesmo comprovante não entra duas vezes por acidente: a tela avisa, o banco garante.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pagamentos_fornecedor_id_transacao
  ON fin_pagamentos_fornecedor(id_transacao) WHERE id_transacao IS NOT NULL;

-- alias_norm é calculado em Python (minúsculas, sem acento, espaços colapsados).
-- unaccent() do Postgres não é imutável e por isso não entra em índice único.
CREATE TABLE IF NOT EXISTS fin_fornecedor_aliases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fornecedor_id UUID NOT NULL REFERENCES fin_fornecedores(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  alias_norm TEXT NOT NULL,
  origem TEXT NOT NULL CHECK (origem IN ('vendedor', 'destinatario')),
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fornecedor_aliases_norm
  ON fin_fornecedor_aliases(origem, alias_norm);
ALTER TABLE fin_fornecedor_aliases ENABLE ROW LEVEL SECURITY;

-- Semente: o que já se sabe da Flavia (card "FL") em 08/09/2026.
INSERT INTO fin_fornecedor_aliases (fornecedor_id, alias, alias_norm, origem)
SELECT f.id, v.alias, v.alias_norm, v.origem
FROM fin_fornecedores f
JOIN (VALUES
  ('Flavia', 'flavia', 'vendedor'),
  ('Multivale Montagem E Estruturas Ltda', 'multivale montagem e estruturas ltda', 'destinatario'),
  ('MIAO ATACADISTA E REPRESENTACOES LTDA', 'miao atacadista e representacoes ltda', 'destinatario')
) AS v(alias, alias_norm, origem) ON true
WHERE f.apelido = 'FL'
ON CONFLICT (origem, alias_norm) DO NOTHING;

INSERT INTO storage.buckets (id, name, public)
VALUES ('fornecedores', 'fornecedores', false)
ON CONFLICT (id) DO NOTHING;
