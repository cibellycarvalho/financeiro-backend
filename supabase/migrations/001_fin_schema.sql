-- Task 1: Schema Supabase - Tabelas fin_ (Painel Financeiro Cravelli)
-- Criado em: 2026-08-04

-- ============================================================================
-- Tabela: fin_user_roles
-- ============================================================================
CREATE TABLE fin_user_roles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('fin_admin', 'fin_viewer')),
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id)
);

-- ============================================================================
-- Tabela: fin_contas_pagar
-- ============================================================================
CREATE TABLE fin_contas_pagar (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  descricao TEXT NOT NULL,
  categoria TEXT NOT NULL CHECK (categoria IN ('FORNECEDOR','CONTABILIDADE','IMPOSTO_DAS','SISTEMA','OUTRO')),
  valor NUMERIC(12,2) NOT NULL,
  vencimento DATE NOT NULL,
  marca TEXT NOT NULL DEFAULT 'GERAL' CHECK (marca IN ('YUSO','M12','GERAL')),
  status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','a_confirmar','pago','vencido')),
  data_pagamento DATE,
  origem TEXT NOT NULL DEFAULT 'manual' CHECK (origem IN ('manual','pluggy','dda')),
  pluggy_item_id TEXT,
  observacao TEXT,
  criado_por UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- Tabela: fin_repasses_ml
-- ============================================================================
CREATE TABLE fin_repasses_ml (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tipo TEXT NOT NULL CHECK (tipo IN ('repasse','cobranca','tarifa')),
  valor NUMERIC(12,2) NOT NULL,
  data_referencia DATE NOT NULL,
  descricao TEXT,
  conta_ml TEXT NOT NULL CHECK (conta_ml IN ('YUSO','M12')),
  origem TEXT NOT NULL DEFAULT 'manual' CHECK (origem IN ('manual','pluggy')),
  pluggy_transaction_id TEXT,
  confirmado BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- Tabela: fin_fornecedores
-- ============================================================================
CREATE TABLE fin_fornecedores (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nome TEXT NOT NULL,
  apelido TEXT,
  tipo_pagamento TEXT NOT NULL DEFAULT 'variavel' CHECK (tipo_pagamento IN ('variavel','fixo')),
  ativo BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- Tabela: fin_pedidos_fornecedor
-- ============================================================================
CREATE TABLE fin_pedidos_fornecedor (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  fornecedor_id UUID NOT NULL REFERENCES fin_fornecedores(id) ON DELETE CASCADE,
  data_pedido DATE NOT NULL,
  descricao_produtos TEXT,
  valor_total NUMERIC(12,2) NOT NULL,
  prazo_combinado DATE,
  status TEXT NOT NULL DEFAULT 'pendente' CHECK (status IN ('pendente','pago','parcial')),
  valor_pago NUMERIC(12,2) DEFAULT 0,
  data_pagamento DATE,
  observacao TEXT,
  criado_por UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- Tabela: fin_pluggy_connections (placeholder para Fase 2)
-- ============================================================================
CREATE TABLE fin_pluggy_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  institution_name TEXT NOT NULL CHECK (institution_name IN ('mercadopago','sicredi')),
  item_id TEXT,
  status TEXT DEFAULT 'pending',
  last_sync TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ============================================================================
-- Triggers: updated_at
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_contas_updated_at
  BEFORE UPDATE ON fin_contas_pagar
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_pedidos_updated_at
  BEFORE UPDATE ON fin_pedidos_fornecedor
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================================
-- Dados Iniciais
-- ============================================================================
INSERT INTO fin_fornecedores (nome, apelido, tipo_pagamento) VALUES
  ('Flávia', 'FL', 'variavel'),
  ('Luana', 'LUANA', 'variavel'),
  ('Gleide', 'GLEIDE', 'variavel'),
  ('Lehmox', 'LEHMOX', 'variavel');

INSERT INTO fin_user_roles (user_id, role) VALUES
  ('fd3a3d59-727f-40e2-bbea-c91187d2f0a7', 'fin_admin');

-- ============================================================================
-- Row Level Security (RLS)
-- ============================================================================
ALTER TABLE fin_user_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_contas_pagar ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_repasses_ml ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_fornecedores ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_pedidos_fornecedor ENABLE ROW LEVEL SECURITY;
ALTER TABLE fin_pluggy_connections ENABLE ROW LEVEL SECURITY;

-- SELECT: qualquer usuário com fin_role
CREATE POLICY "fin_select" ON fin_contas_pagar FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
CREATE POLICY "fin_select" ON fin_repasses_ml FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
CREATE POLICY "fin_select" ON fin_fornecedores FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
CREATE POLICY "fin_select" ON fin_pedidos_fornecedor FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));

-- SELECT: cada usuário vê apenas sua própria role (evita recursão nas policies de outras tabelas)
CREATE POLICY "fin_select" ON fin_user_roles FOR SELECT
  USING (auth.uid() = user_id);

-- ALL (INSERT/UPDATE/DELETE): apenas fin_admin
CREATE POLICY "fin_write" ON fin_contas_pagar FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
CREATE POLICY "fin_write" ON fin_repasses_ml FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
CREATE POLICY "fin_write" ON fin_pedidos_fornecedor FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
CREATE POLICY "fin_write" ON fin_fornecedores FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));

-- fin_pluggy_connections: SELECT para qualquer usuário fin_, write apenas fin_admin
CREATE POLICY "fin_select" ON fin_pluggy_connections FOR SELECT
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles));
CREATE POLICY "fin_write" ON fin_pluggy_connections FOR ALL
  USING (auth.uid() IN (SELECT user_id FROM fin_user_roles WHERE role = 'fin_admin'));
