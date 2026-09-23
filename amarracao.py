"""Amarra um pagamento às compras que ele pagou.

Saiu da coluna fin_pagamentos_fornecedor.pedido_id, que só aceitava uma compra
por Pix. O Pix de R$ 49.310 de 14/09/2026 pagou os pedidos de 10/08 e 11/08.
"""
import math

TOLERANCIA = 0.005   # meio centavo, como no resto do painel


def validar(cur, pagamento_id, fornecedor_id, itens):
    """Devolve None se pode gravar, ou a frase de erro que a tela mostra."""
    if not itens:
        return "Escolha pelo menos uma compra."

    vistos = set()
    for item in itens:
        pedido_id = item.get("pedido_id") if isinstance(item, dict) else None
        if not pedido_id:
            return "pedido_id obrigatório em cada item."
        if pedido_id in vistos:
            return f"A compra {pedido_id} está repetida na lista — some tudo num item só."
        vistos.add(pedido_id)

        try:
            valor = float(item["valor"])
        except (KeyError, TypeError, ValueError):
            return "valor inválido."
        if not math.isfinite(valor):
            return "valor inválido."
        if valor <= 0:
            return "O valor de cada compra tem que ser maior que zero."

    cur.execute("SELECT valor FROM fin_pagamentos_fornecedor WHERE id = %s", (pagamento_id,))
    linha = cur.fetchone()
    if not linha:
        return "Pagamento não encontrado."
    total_pagamento = float(linha["valor"])
    total_itens = sum(float(i["valor"]) for i in itens)
    if total_itens > total_pagamento + TOLERANCIA:
        return (f"A soma das compras (R$ {total_itens:.2f}) passa do valor do "
                f"pagamento (R$ {total_pagamento:.2f}).")

    for item in itens:
        # pedido_id pode vir de fora malformado (não-UUID); o driver real
        # recusa isso com um erro de banco — tratamos como "compra não
        # encontrada" em vez de deixar estourar 500.
        try:
            cur.execute(
                """SELECT p.valor_total,
                          COALESCE((SELECT SUM(valor) FROM fin_pagamento_pedido
                                    WHERE pedido_id = p.id AND pagamento_id <> %s), 0) AS amarrado
                   FROM fin_pedidos_fornecedor p WHERE p.id = %s AND p.fornecedor_id = %s""",
                (pagamento_id, item["pedido_id"], fornecedor_id),
            )
            pedido = cur.fetchone()
        except Exception:
            return "Compra não encontrada."
        if not pedido:
            return "Compra não encontrada."
        livre = float(pedido["valor_total"]) - float(pedido["amarrado"])
        if float(item["valor"]) > livre + TOLERANCIA:
            return (f"Essa compra só tem R$ {max(livre, 0):.2f} em aberto — "
                    "o valor amarrado não pode passar disso.")
    return None
