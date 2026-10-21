-- Custo do CRM atualizado pelo pedido de compra.
--
-- 1) O produto do pedido ("FIBRA HDMI 20M 8K NYLON FL-W612") quase nunca bate
--    com o SKU. Na primeira vez ela escolhe o SKU; o par (fornecedor, produto)
--    fica guardado aqui e o próximo pedido já vem com o SKU preenchido.
CREATE TABLE IF NOT EXISTS fin_produto_sku_alias (
  fornecedor_id UUID NOT NULL REFERENCES fin_fornecedores(id) ON DELETE CASCADE,
  produto_norm  TEXT NOT NULL,
  produto       TEXT NOT NULL,
  sku           TEXT NOT NULL,
  atualizado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (fornecedor_id, produto_norm)
);
ALTER TABLE fin_produto_sku_alias ENABLE ROW LEVEL SECURITY;

-- 2) Quando o VALOR do custo mudou pela última vez. Não dá para usar
--    atualizado_em: ele também muda quando se mexe em SKU ou estoque mínimo.
ALTER TABLE custos_produtos ADD COLUMN IF NOT EXISTS custo_atualizado_em TIMESTAMPTZ;

-- Passado: o último registro do histórico; sem histórico, o atualizado_em.
UPDATE custos_produtos c
   SET custo_atualizado_em = COALESCE(
         (SELECT max(h.criado_em) FROM custos_historico h
           WHERE h.item_id = c.item_id AND h.conta_ml = c.conta_ml),
         c.atualizado_em)
 WHERE c.custo_atualizado_em IS NULL;
