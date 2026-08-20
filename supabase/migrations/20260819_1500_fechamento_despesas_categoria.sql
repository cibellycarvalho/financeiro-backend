-- Garante a coluna `categoria` em fechamento_despesas.
--
-- A tabela nasceu sem ela no CRM, e lá o remendo era rodar este mesmo ALTER a
-- cada despesa gravada (routes/fechamento.py::_ensure_categoria). Funciona, mas
-- é comando de alteração de tabela por requisição — e agora dois serviços
-- gravariam na mesma tabela, o que multiplicaria isso sem necessidade.
--
-- A coluna já existe em produção. Esta migração é para ambientes novos e para
-- que a garantia fique registrada onde se procura por ela.
ALTER TABLE fechamento_despesas ADD COLUMN IF NOT EXISTS categoria text;
