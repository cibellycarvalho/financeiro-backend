-- SKU opcional em cada item do pedido de compra (ex.: FV0073). Liga a compra ao
-- produto do CRM: o painel passa a saber o que já foi comprado e ainda não foi
-- enviado ao Full, e para de cobrar de novo.
ALTER TABLE fin_pedido_itens ADD COLUMN IF NOT EXISTS sku TEXT;
CREATE INDEX IF NOT EXISTS idx_pedido_itens_sku ON fin_pedido_itens (sku) WHERE sku IS NOT NULL;
