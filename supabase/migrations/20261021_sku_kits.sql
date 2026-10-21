-- Kit = quantas unidades do produto vão em um anúncio daquele SKU.
-- "1010 = 5 × 1017": quando o pedido atualiza a fonte avulsa (1017), o kit de
-- 5 passa a custar 5 × o custo da unidade. Um SKU que é kit mas não tem avulso
-- (FV0006, kit 10 emendas) fica com sku_base nulo: o pedido liga direto nele e
-- o custo é unidades × valor do pedido.
-- Só entra aqui o que ela confirmou; a detecção por "Kit N" no título é só sugestão.
CREATE TABLE IF NOT EXISTS sku_kits (
  sku           TEXT PRIMARY KEY,
  unidades      NUMERIC NOT NULL CHECK (unidades > 0),
  sku_base      TEXT,
  confirmado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (sku_base IS NULL OR sku_base <> sku)
);
CREATE INDEX IF NOT EXISTS idx_sku_kits_base ON sku_kits (sku_base) WHERE sku_base IS NOT NULL;
ALTER TABLE sku_kits ENABLE ROW LEVEL SECURITY;
