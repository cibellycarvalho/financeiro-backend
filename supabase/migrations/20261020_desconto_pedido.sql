-- Desconto que o fornecedor deu no pedido (o Pix saiu menor que o valor do
-- pedido). Entra no saldo: o que se deve é valor_total - desconto.
ALTER TABLE fin_pedidos_fornecedor ADD COLUMN IF NOT EXISTS desconto NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (desconto >= 0);
