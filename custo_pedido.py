"""O pedido de compra atualiza o custo do produto no CRM.

O custo do CRM mora em `custos_produtos`, por ANÚNCIO (conta_ml, item_id), não
por produto. Por isso o SKU do item do pedido é aplicado a TODOS os anúncios
que têm aquele SKU em `ml_anuncios` — republicar não perde o custo, e anúncios
irmãos não ficam com valores diferentes.

Regras dela (21/10/2026):
- custo = valor unitário do pedido + 2% da nota fiscal. Os 2% não aparecem em
  tela nenhuma; só entram na conta.
- Atualiza direto, sem tela de aprovação.

E uma minha: pedido mais antigo que outro do mesmo SKU não mexe no custo.
Sem isso, lançar hoje um pedido esquecido de agosto voltaria o custo para o
preço de agosto.
"""
import aliases
import db

NF = 0.02


def custo_com_nf(valor_unitario):
    return round(float(valor_unitario) * (1 + NF), 2)


def sugerir_sku(fornecedor_id, produto):
    if not produto or not produto.strip():
        return None
    rows = db.query(
        "SELECT sku FROM fin_produto_sku_alias WHERE fornecedor_id = %s AND produto_norm = %s",
        (fornecedor_id, aliases.normalizar(produto)),
    )
    return rows[0]["sku"] if rows else None


def aprender_sku(fornecedor_id, produto, sku):
    if not sku or not produto or not produto.strip():
        return
    db.execute(
        """INSERT INTO fin_produto_sku_alias (fornecedor_id, produto_norm, produto, sku)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (fornecedor_id, produto_norm) DO UPDATE
           SET sku = EXCLUDED.sku, produto = EXCLUDED.produto, atualizado_em = now()""",
        (fornecedor_id, aliases.normalizar(produto), produto.strip(), sku),
    )


def aplicar(item_id, sku, valor_unitario, data_pedido):
    """Grava o custo do item em todos os anúncios do SKU. Devolve o que fez,
    para a tela poder contar: {sku, status, custo?, anuncios?}."""
    custo = custo_com_nf(valor_unitario)
    with db.transaction() as cur:
        cur.execute(
            """SELECT 1 FROM fin_pedido_itens i
                 JOIN fin_pedidos_fornecedor p ON p.id = i.pedido_id
                WHERE i.sku = %s AND i.id <> %s AND p.data_pedido > %s::date
                LIMIT 1""",
            (sku, item_id, data_pedido),
        )
        if cur.fetchone():
            return {"sku": sku, "status": "pedido_mais_novo"}

        cur.execute(
            "SELECT ml_item_id, conta_ml, titulo FROM ml_anuncios WHERE upper(sku) = %s",
            (sku,),
        )
        anuncios = cur.fetchall()
        if not anuncios:
            return {"sku": sku, "status": "sku_desconhecido"}

        for a in anuncios:
            cur.execute(
                """INSERT INTO custos_produtos
                     (conta_ml, item_id, titulo, custo_unitario, sku_interno, atualizado_em, custo_atualizado_em)
                   VALUES (%s, %s, %s, %s, %s, now(), now())
                   ON CONFLICT (conta_ml, item_id) DO UPDATE
                   SET custo_unitario = EXCLUDED.custo_unitario,
                       sku_interno = COALESCE(custos_produtos.sku_interno, EXCLUDED.sku_interno),
                       atualizado_em = now(),
                       custo_atualizado_em = now()""",
                (a["conta_ml"], a["ml_item_id"], a["titulo"], custo, sku),
            )
            # A Curva ABC escolhe o custo por (item_id, vigente_desde): duas
            # linhas na mesma data deixam a escolha ao acaso. Por isso altera a
            # linha da data, se já houver, em vez de inserir outra. E nunca
            # nasce antes do último registro, senão ficaria escondida por ele.
            cur.execute(
                """SELECT GREATEST(%s::date, COALESCE(max(vigente_desde), %s::date)) AS vigente
                     FROM custos_historico WHERE item_id = %s AND conta_ml = %s""",
                (data_pedido, data_pedido, a["ml_item_id"], a["conta_ml"]),
            )
            vigente = cur.fetchone()["vigente"]
            cur.execute(
                """UPDATE custos_historico SET custo_unitario = %s
                    WHERE item_id = %s AND conta_ml = %s AND vigente_desde = %s
                    RETURNING id""",
                (custo, a["ml_item_id"], a["conta_ml"], vigente),
            )
            if not cur.fetchone():
                cur.execute(
                    """INSERT INTO custos_historico (item_id, conta_ml, custo_unitario, vigente_desde)
                       VALUES (%s, %s, %s, %s)""",
                    (a["ml_item_id"], a["conta_ml"], custo, vigente),
                )
    return {"sku": sku, "status": "atualizado", "custo": custo, "anuncios": len(anuncios)}
