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


def test_backfill_nao_grava_link_maior_que_a_compra():
    """Fix round 3 (IMPORTANT 2): pg.valor cheio podia gravar um link maior
    que o valor_total da compra — exatamente o que amarracao.validar recusa.
    Nenhuma linha do banco está assim hoje (conferido 23/09/2026), então não
    existe migração corretiva: isto é só para quem rodar o SQL de novo."""
    texto = SQL.read_text()
    assert "LEAST(pg.valor, p.valor_total)" in texto
    assert "JOIN fin_pedidos_fornecedor p ON p.id = pg.pedido_id" in texto
    assert "SELECT pg.id, pg.pedido_id, pg.valor\n" not in texto


def test_migracao_cria_policies_rls():
    texto = SQL.read_text()
    assert "CREATE POLICY fin_select ON fin_pagamento_pedido" in texto
    assert "CREATE POLICY fin_write ON fin_pagamento_pedido" in texto
