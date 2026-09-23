from pathlib import Path

SQL = Path(__file__).resolve().parent.parent / "supabase" / "20260923_notas_e_amarracao.sql"


def test_migracao_cria_colunas_e_tabela():
    texto = SQL.read_text()
    assert "fin_pedidos_fornecedor ADD COLUMN IF NOT EXISTS nf_path" in texto
    assert "fin_contas_pagar ADD COLUMN IF NOT EXISTS nf_path" in texto
    assert "fin_contas_pagar ADD COLUMN IF NOT EXISTS comprovante_path" in texto
    assert "CREATE TABLE IF NOT EXISTS fin_pagamento_pedido" in texto


def test_migracao_leva_as_amarracoes_antigas():
    texto = SQL.read_text()
    assert "INSERT INTO fin_pagamento_pedido" in texto
    assert "WHERE pg.pedido_id IS NOT NULL" in texto
