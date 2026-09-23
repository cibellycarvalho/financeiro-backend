"""Baixar o mês: um .zip por mês de COMPRA, com nota, pedido e comprovantes."""
import calendar
import re
from datetime import date

from flask import Blueprint, jsonify, Response

import db
import pacote_zip
from auth import require_auth

bp = Blueprint("pacote", __name__)


def _compras_do_mes(inicio, fim):
    """Compras de fornecedor do mês + as contas a pagar de categoria FORNECEDOR."""
    pedidos = db.query(
        """SELECT COALESCE(f.apelido, f.nome) AS fornecedor,
                  p.data_pedido AS data_compra, p.numero_pedido,
                  p.valor_total AS valor, p.nf_path, p.arquivo_path AS pedido_path,
                  COALESCE((
                    SELECT json_agg(json_build_object(
                             'path', pg.arquivo_path, 'data', pg.data_pagamento, 'valor', lig.valor)
                           ORDER BY pg.data_pagamento)
                    FROM fin_pagamento_pedido lig
                    JOIN fin_pagamentos_fornecedor pg ON pg.id = lig.pagamento_id
                    WHERE lig.pedido_id = p.id
                  ), '[]') AS comprovantes
           FROM fin_pedidos_fornecedor p
           JOIN fin_fornecedores f ON f.id = p.fornecedor_id
           WHERE p.data_pedido BETWEEN %s AND %s
           ORDER BY f.nome, p.data_pedido""",
        (inicio, fim),
    )
    contas = db.query(
        """SELECT 'CONTAS A PAGAR' AS fornecedor, c.vencimento AS data_compra,
                  c.descricao AS numero_pedido, c.valor, c.nf_path,
                  NULL AS pedido_path,
                  CASE WHEN c.status = 'pago' AND c.comprovante_path IS NOT NULL
                       THEN json_build_array(json_build_object(
                              'path', c.comprovante_path,
                              'data', COALESCE(c.data_pagamento, c.vencimento),
                              'valor', c.valor))
                       ELSE '[]' END AS comprovantes
           FROM fin_contas_pagar c
           WHERE c.categoria = 'FORNECEDOR' AND c.vencimento BETWEEN %s AND %s
           ORDER BY c.vencimento""",
        (inicio, fim),
    )
    return list(pedidos) + list(contas)


@bp.get("/compras/<mes>")
@require_auth
def baixar_compras(mes):
    if not re.fullmatch(r"\d{4}-\d{2}", mes):
        return jsonify({"error": "mês no formato AAAA-MM"}), 400
    ano, m = int(mes[:4]), int(mes[5:])
    if not 1 <= m <= 12:
        return jsonify({"error": "mês no formato AAAA-MM"}), 400
    inicio = date(ano, m, 1)
    fim = date(ano, m, calendar.monthrange(ano, m)[1])

    compras = _compras_do_mes(inicio.isoformat(), fim.isoformat())
    if not compras:
        return jsonify({"error": f"Nenhuma compra em {mes}."}), 404

    conteudo = pacote_zip.montar(compras)
    return Response(
        conteudo,
        mimetype="application/zip",
        headers={"Content-Disposition": f'attachment; filename="compras-{mes}.zip"'},
    )
