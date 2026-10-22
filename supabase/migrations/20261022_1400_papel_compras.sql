-- Papel só de compras (Valber): fornecedores e pedidos, sem pagamentos, caixa nem funcionários.
ALTER TABLE fin_user_roles DROP CONSTRAINT fin_user_roles_role_check;
ALTER TABLE fin_user_roles ADD CONSTRAINT fin_user_roles_role_check
  CHECK (role = ANY (ARRAY['fin_admin'::text, 'fin_viewer'::text, 'fin_compras'::text]));
