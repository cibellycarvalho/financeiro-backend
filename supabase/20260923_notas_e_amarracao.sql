-- supabase/20260923_notas_e_amarracao.sql
-- Nota fiscal da compra e amarração de um Pix a várias compras (23/09/2026).

ALTER TABLE fin_pedidos_fornecedor ADD COLUMN IF NOT EXISTS nf_path text;
ALTER TABLE fin_contas_pagar ADD COLUMN IF NOT EXISTS nf_path text;
ALTER TABLE fin_contas_pagar ADD COLUMN IF NOT EXISTS comprovante_path text;

-- Um Pix pode pagar mais de uma compra: o de R$ 49.310 de 14/09 pagou os
-- pedidos de 10/08 e 11/08. A coluna pedido_id só aceitava uma.
CREATE TABLE IF NOT EXISTS fin_pagamento_pedido (
  pagamento_id uuid NOT NULL REFERENCES fin_pagamentos_fornecedor(id) ON DELETE CASCADE,
  pedido_id    uuid NOT NULL REFERENCES fin_pedidos_fornecedor(id) ON DELETE CASCADE,
  valor        numeric(12,2) NOT NULL CHECK (valor > 0),
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (pagamento_id, pedido_id)
);

CREATE INDEX IF NOT EXISTS idx_pagamento_pedido_pedido ON fin_pagamento_pedido(pedido_id);

-- As amarrações que já existem na coluna antiga passam para a tabela.
INSERT INTO fin_pagamento_pedido (pagamento_id, pedido_id, valor)
SELECT pg.id, pg.pedido_id, pg.valor
FROM fin_pagamentos_fornecedor pg
WHERE pg.pedido_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- A coluna pedido_id FICA, sem ser lida, até o código novo estar no ar uma
-- semana. Remover junto com o deploy deixaria a versão antiga da tela quebrada
-- no navegador de quem não recarregou.

ALTER TABLE fin_pagamento_pedido ENABLE ROW LEVEL SECURITY;
