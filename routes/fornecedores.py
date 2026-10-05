import re
import sys
from datetime import date

from flask import Blueprint, request, jsonify, g
import amarracao
import anexos
from anexos import MSG_LEITURA_INDISPONIVEL, MSG_ANEXO_NAO_GUARDADO
import db
import aliases
import leitura_documento
import storage
from auth import require_auth, require_admin

bp = Blueprint("fornecedores", __name__)


class _ErroAmarracao(Exception):
    """Erro de validação de amarração levantado dentro de uma transação, pra
    forçar o rollback do que já foi gravado antes de responder 400. A
    mensagem já é a frase pronta pra tela."""


def _saldo_aberto_fornecedor(fornecedor_id):
    row = db.query(
        """SELECT
             COALESCE((SELECT SUM(valor_total) FROM fin_pedidos_fornecedor WHERE fornecedor_id = %s), 0)
             - COALESCE((SELECT SUM(valor) FROM fin_pagamentos_fornecedor WHERE fornecedor_id = %s), 0)
             - COALESCE((SELECT SUM(valor) FROM fin_devolucoes_fornecedor WHERE fornecedor_id = %s), 0)
             AS saldo_aberto""",
        (fornecedor_id, fornecedor_id, fornecedor_id)
    )
    return float(row[0]["saldo_aberto"])


@bp.post("")
@require_auth
@require_admin
def criar_fornecedor():
    data = request.get_json()
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"error": "nome obrigatório"}), 400
    apelido = (data.get("apelido") or "").strip() or None
    tipo = data.get("tipo_pagamento", "variavel")
    if tipo not in ("variavel", "fixo"):
        tipo = "variavel"
    row = db.execute(
        "INSERT INTO fin_fornecedores (nome, apelido, tipo_pagamento) VALUES (%s, %s, %s) RETURNING *",
        (nome, apelido, tipo)
    )
    return jsonify(row), 201


@bp.put("/<fornecedor_id>")
@require_auth
@require_admin
def editar_fornecedor(fornecedor_id):
    data = request.get_json()
    campos, params = [], []
    if "nome" in data:
        nome = (data["nome"] or "").strip()
        if not nome:
            return jsonify({"error": "nome não pode ser vazio"}), 400
        campos.append("nome = %s")
        params.append(nome)
    if "apelido" in data:
        campos.append("apelido = %s")
        params.append((data["apelido"] or "").strip() or None)
    if not campos:
        return jsonify({"error": "nenhum campo para atualizar"}), 400
    params.append(fornecedor_id)
    row = db.execute(
        f"UPDATE fin_fornecedores SET {', '.join(campos)} WHERE id = %s AND ativo = true RETURNING *",
        tuple(params)
    )
    if not row:
        return jsonify({"error": "Fornecedor não encontrado"}), 404
    return jsonify(row)


@bp.delete("/<fornecedor_id>")
@require_auth
@require_admin
def excluir_fornecedor(fornecedor_id):
    fornecedores = db.query(
        "SELECT id FROM fin_fornecedores WHERE id = %s AND ativo = true",
        (fornecedor_id,)
    )
    if not fornecedores:
        return jsonify({"error": "Fornecedor não encontrado"}), 404

    if _saldo_aberto_fornecedor(fornecedor_id) > 0:
        return jsonify({"error": "Fornecedor possui saldo em aberto e não pode ser excluído"}), 400

    row = db.execute(
        "UPDATE fin_fornecedores SET ativo = false WHERE id = %s RETURNING *",
        (fornecedor_id,)
    )
    return jsonify(row)


@bp.get("")
@require_auth
def listar():
    rows = db.query("""
        SELECT f.*,
               COALESCE((SELECT SUM(p.valor_total) FROM fin_pedidos_fornecedor p WHERE p.fornecedor_id = f.id), 0)
               - COALESCE((SELECT SUM(pg.valor) FROM fin_pagamentos_fornecedor pg WHERE pg.fornecedor_id = f.id), 0)
               - COALESCE((SELECT SUM(d.valor) FROM fin_devolucoes_fornecedor d WHERE d.fornecedor_id = f.id), 0)
               AS saldo_aberto
        FROM fin_fornecedores f
        WHERE f.ativo = true
        ORDER BY f.nome
    """)
    return jsonify(rows)


@bp.get("/pagamentos")
@require_auth
def pagamentos_do_periodo():
    """Pagamentos a qualquer fornecedor entre `de` e `ate` (inclusive).

    A Caixa da Semana desconta da sobra o que foi pago a fornecedor na semana
    — a Flávia e as compras lançadas com comprovante. Por fornecedor seria uma
    chamada para cada um.
    """
    de, ate = request.args.get("de", ""), request.args.get("ate", "")
    if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", de) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ate)):
        return jsonify({"error": "de e ate obrigatórios, no formato AAAA-MM-DD"}), 400
    try:
        date.fromisoformat(de)
        date.fromisoformat(ate)
    except ValueError:
        return jsonify({"error": "de e ate obrigatórios, no formato AAAA-MM-DD"}), 400
    rows = db.query(
        """SELECT pg.*, f.nome AS fornecedor_nome, f.apelido AS fornecedor_apelido
           FROM fin_pagamentos_fornecedor pg
           JOIN fin_fornecedores f ON f.id = pg.fornecedor_id
           WHERE pg.data_pagamento BETWEEN %s AND %s
           ORDER BY pg.data_pagamento, pg.created_at""",
        (de, ate)
    )
    return jsonify(rows)


@bp.get("/<fornecedor_id>/pedidos")
@require_auth
def listar_pedidos(fornecedor_id):
    rows = db.query(
        """SELECT p.*,
                   COALESCE(
                     (SELECT json_agg(
                        json_build_object(
                          'id', i.id, 'produto', i.produto, 'quantidade', i.quantidade,
                          'valor_unitario', i.valor_unitario, 'valor_total', i.valor_total
                        ) ORDER BY i.created_at
                      ) FROM fin_pedido_itens i WHERE i.pedido_id = p.id), '[]'
                   ) AS itens,
                   -- Fix round 1 (item 8 da revisão): a tela de "Pix sem compra"
                   -- precisa saber quanto já está amarrado a cada pedido, para
                   -- não propor amarrar de novo o que outro Pix já cobriu.
                   COALESCE(
                     (SELECT SUM(lig.valor) FROM fin_pagamento_pedido lig WHERE lig.pedido_id = p.id), 0
                   ) AS amarrado
            FROM fin_pedidos_fornecedor p
            WHERE p.fornecedor_id = %s
            ORDER BY p.data_pedido DESC""",
        (fornecedor_id,)
    )
    return jsonify(rows)


def _aprender_alias_silencioso(fornecedor_id, texto, origem):
    """O registro já está gravado: aprender o alias nunca vale um 500 que a
    faria salvar de novo e duplicar."""
    if not isinstance(texto, str) or not texto.strip():
        return
    try:
        aliases.aprender_alias(fornecedor_id, texto, origem)
    except Exception as e:
        print(f"[aliases] falhou ao aprender '{texto[:60]}' ({origem}): {type(e).__name__}: {e}", file=sys.stderr, flush=True)


@bp.post("/<fornecedor_id>/pedidos/ler")
@require_auth
@require_admin
def ler_pedido_arquivo(fornecedor_id):
    dados, mime, erro = anexos.ler_arquivo_enviado()
    if erro:
        return erro

    try:
        lido = leitura_documento.ler_pedido(dados, mime)
    except leitura_documento.LeituraIndisponivel as e:
        print(f"[leitura_documento] indisponível ao ler pedido: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": MSG_LEITURA_INDISPONIVEL}), 503
    except leitura_documento.LeituraFalhou as e:
        print(f"[leitura_documento] falhou ao ler pedido: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        lido = None

    # Guardar o arquivo é o acessório: se o Storage falhar, ela ainda lança o
    # que a IA leu — só sem o anexo. Bloquear aqui seria perder a leitura toda.
    aviso = None
    try:
        token = anexos.subir_pendente(dados, mime)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao guardar arquivo do pedido: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        token = None
        aviso = MSG_ANEXO_NAO_GUARDADO

    if lido is None:
        return jsonify({
            "leitura_falhou": True, "arquivo_token": token, "aviso": aviso,
            "fornecedor_sugerido_id": None, "texto_vendedor": None,
            "numero_pedido": None, "data_pedido": None, "itens": [],
            "total_documento": None, "pedido_existente": None,
        })

    existente = None
    if lido["numero_pedido"]:
        rows = db.query(
            """SELECT id, data_pedido FROM fin_pedidos_fornecedor
               WHERE fornecedor_id = %s AND numero_pedido = %s
               ORDER BY created_at DESC LIMIT 1""",
            (fornecedor_id, lido["numero_pedido"]),
        )
        if rows:
            existente = {"id": rows[0]["id"], "data_pedido": rows[0]["data_pedido"]}

    return jsonify({
        "leitura_falhou": False,
        "arquivo_token": token,
        "aviso": aviso,
        "fornecedor_sugerido_id": aliases.sugerir_fornecedor(lido["texto_vendedor"], "vendedor"),
        "texto_vendedor": lido["texto_vendedor"],
        "numero_pedido": lido["numero_pedido"],
        "data_pedido": lido["data_pedido"],
        "itens": lido["itens"],
        "total_documento": lido["total_documento"],
        "pedido_existente": existente,
    })


def _validar_itens(itens):
    """Valida a lista de itens do pedido. Retorna (itens_validados, erro)."""
    if not itens or not isinstance(itens, list):
        return None, "itens obrigatório (lista de produtos)"

    itens_validados = []
    for item in itens:
        produto = (item.get("produto") or "").strip()
        if not produto:
            return None, "produto obrigatório em cada item"
        try:
            quantidade = float(item.get("quantidade"))
            valor_unitario = float(item.get("valor_unitario"))
        except (TypeError, ValueError):
            return None, "quantidade e valor_unitario devem ser numéricos"
        if quantidade <= 0:
            return None, "quantidade deve ser maior que zero"
        if valor_unitario < 0:
            return None, "valor_unitario não pode ser negativo"
        itens_validados.append((produto, quantidade, valor_unitario))
    return itens_validados, None


@bp.post("/<fornecedor_id>/pedidos")
@require_auth
@require_admin
def criar_pedido(fornecedor_id):
    data = request.get_json()

    if not data.get("data_pedido"):
        return jsonify({"error": "data_pedido obrigatória"}), 400

    itens_validados, erro = _validar_itens(data.get("itens"))
    if erro:
        return jsonify({"error": erro}), 400

    valor_total = sum(quantidade * valor_unitario for _, quantidade, valor_unitario in itens_validados)
    numero_pedido = (data.get("numero_pedido") or "").strip() or None
    arquivo_token = (data.get("arquivo_token") or "").strip() or None
    alias_vendedor = data.get("alias_vendedor")

    if arquivo_token and not anexos.arquivo_token_valido(arquivo_token):
        return jsonify({"error": "arquivo_token inválido"}), 400

    try:
        with db.transaction() as cur:
            cur.execute(
                """INSERT INTO fin_pedidos_fornecedor
                   (fornecedor_id, data_pedido, valor_total, observacao, numero_pedido, criado_por)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (fornecedor_id, data["data_pedido"], valor_total, data.get("observacao"),
                 numero_pedido, g.user["user_id"])
            )
            pedido = dict(cur.fetchone())

            itens_criados = []
            for produto, quantidade, valor_unitario in itens_validados:
                cur.execute(
                    """INSERT INTO fin_pedido_itens (pedido_id, produto, quantidade, valor_unitario)
                       VALUES (%s, %s, %s, %s)
                       RETURNING *""",
                    (pedido["id"], produto, quantidade, valor_unitario)
                )
                itens_criados.append(dict(cur.fetchone()))

            # O anexo move dentro da transação: se o Storage falhar, nada é gravado.
            if arquivo_token:
                destino = anexos.destino_anexo(fornecedor_id, "pedidos", pedido["id"], arquivo_token)
                storage.mover(arquivo_token, destino)
                cur.execute(
                    "UPDATE fin_pedidos_fornecedor SET arquivo_path = %s WHERE id = %s",
                    (destino, pedido["id"])
                )
                pedido["arquivo_path"] = destino
    except storage.StorageErro as e:
        print(f"[storage] falhou ao mover anexo do pedido: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": "Não consegui guardar o anexo; o pedido não foi salvo. Tente de novo."}), 500

    _aprender_alias_silencioso(fornecedor_id, alias_vendedor, "vendedor")

    pedido["itens"] = itens_criados
    return jsonify(pedido), 201


@bp.put("/<fornecedor_id>/pedidos/<pedido_id>")
@require_auth
@require_admin
def atualizar_pedido(fornecedor_id, pedido_id):
    data = request.get_json()

    if "valor_total" in data:
        try:
            valor_total = float(data["valor_total"])
        except (TypeError, ValueError):
            return jsonify({"error": "valor_total inválido"}), 400
        if valor_total <= 0:
            return jsonify({"error": "valor_total deve ser maior que zero"}), 400

        itens = db.query("SELECT id FROM fin_pedido_itens WHERE pedido_id = %s", (pedido_id,))
        if itens:
            return jsonify({"error": "Este pedido tem produtos cadastrados; edite os produtos individualmente"}), 400

        row = db.execute(
            "UPDATE fin_pedidos_fornecedor SET valor_total = %s WHERE id = %s AND fornecedor_id = %s RETURNING *",
            (valor_total, pedido_id, fornecedor_id)
        )
        if not row:
            return jsonify({"error": "Pedido não encontrado"}), 404
        return jsonify(row)

    campos, params = [], []
    if "observacao" in data:
        campos.append("observacao = %s")
        params.append(data["observacao"])
    if "data_pedido" in data:
        if not data["data_pedido"]:
            return jsonify({"error": "data_pedido não pode ser vazia"}), 400
        campos.append("data_pedido = %s")
        params.append(data["data_pedido"])

    if not campos:
        return jsonify({"error": "nenhum campo para atualizar"}), 400

    params += [pedido_id, fornecedor_id]
    row = db.execute(
        f"UPDATE fin_pedidos_fornecedor SET {', '.join(campos)} WHERE id = %s AND fornecedor_id = %s RETURNING *",
        tuple(params)
    )
    if not row:
        return jsonify({"error": "Pedido não encontrado"}), 404
    return jsonify(row)


@bp.delete("/<fornecedor_id>/pedidos/<pedido_id>")
@require_auth
@require_admin
def excluir_pedido(fornecedor_id, pedido_id):
    pedidos = db.query(
        "SELECT id FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id)
    )
    if not pedidos:
        return jsonify({"error": "Pedido não encontrado"}), 404

    db.execute(
        "DELETE FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id)
    )
    return "", 204


@bp.post("/<fornecedor_id>/pedidos/<pedido_id>/itens")
@require_auth
@require_admin
def adicionar_item(fornecedor_id, pedido_id):
    data = request.get_json()
    itens_validados, erro = _validar_itens([data])
    if erro:
        return jsonify({"error": erro}), 400
    produto, quantidade, valor_unitario = itens_validados[0]

    pedidos = db.query(
        "SELECT id FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id)
    )
    if not pedidos:
        return jsonify({"error": "Pedido não encontrado"}), 404

    with db.transaction() as cur:
        cur.execute(
            """INSERT INTO fin_pedido_itens (pedido_id, produto, quantidade, valor_unitario)
               VALUES (%s, %s, %s, %s)
               RETURNING *""",
            (pedido_id, produto, quantidade, valor_unitario)
        )
        item = dict(cur.fetchone())
        cur.execute(
            """UPDATE fin_pedidos_fornecedor
               SET valor_total = (SELECT COALESCE(SUM(valor_total), 0) FROM fin_pedido_itens WHERE pedido_id = %s)
               WHERE id = %s AND fornecedor_id = %s
               RETURNING *""",
            (pedido_id, pedido_id, fornecedor_id)
        )
        pedido_atualizado = dict(cur.fetchone())

    pedido_atualizado["item"] = item
    return jsonify(pedido_atualizado), 201


@bp.put("/<fornecedor_id>/pedidos/<pedido_id>/itens/<item_id>")
@require_auth
@require_admin
def editar_item(fornecedor_id, pedido_id, item_id):
    data = request.get_json()
    itens_validados, erro = _validar_itens([data])
    if erro:
        return jsonify({"error": erro}), 400
    produto, quantidade, valor_unitario = itens_validados[0]

    pedidos = db.query(
        "SELECT id FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id)
    )
    if not pedidos:
        return jsonify({"error": "Pedido não encontrado"}), 404

    itens = db.query(
        "SELECT id FROM fin_pedido_itens WHERE id = %s AND pedido_id = %s",
        (item_id, pedido_id)
    )
    if not itens:
        return jsonify({"error": "Item não encontrado"}), 404

    with db.transaction() as cur:
        cur.execute(
            """UPDATE fin_pedido_itens SET produto = %s, quantidade = %s, valor_unitario = %s
               WHERE id = %s AND pedido_id = %s
               RETURNING *""",
            (produto, quantidade, valor_unitario, item_id, pedido_id)
        )
        item = dict(cur.fetchone())
        cur.execute(
            """UPDATE fin_pedidos_fornecedor
               SET valor_total = (SELECT COALESCE(SUM(valor_total), 0) FROM fin_pedido_itens WHERE pedido_id = %s)
               WHERE id = %s AND fornecedor_id = %s
               RETURNING *""",
            (pedido_id, pedido_id, fornecedor_id)
        )
        pedido_atualizado = dict(cur.fetchone())

    pedido_atualizado["item"] = item
    return jsonify(pedido_atualizado)


@bp.delete("/<fornecedor_id>/pedidos/<pedido_id>/itens/<item_id>")
@require_auth
@require_admin
def excluir_item(fornecedor_id, pedido_id, item_id):
    pedidos = db.query(
        "SELECT id FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id)
    )
    if not pedidos:
        return jsonify({"error": "Pedido não encontrado"}), 404

    itens = db.query("SELECT id FROM fin_pedido_itens WHERE pedido_id = %s", (pedido_id,))
    if not any(i["id"] == item_id for i in itens):
        return jsonify({"error": "Item não encontrado"}), 404
    if len(itens) <= 1:
        return jsonify({"error": "Este é o único produto do pedido; exclua o pedido inteiro se quiser removê-lo"}), 400

    with db.transaction() as cur:
        cur.execute(
            "DELETE FROM fin_pedido_itens WHERE id = %s AND pedido_id = %s",
            (item_id, pedido_id)
        )
        cur.execute(
            """UPDATE fin_pedidos_fornecedor
               SET valor_total = (SELECT COALESCE(SUM(valor_total), 0) FROM fin_pedido_itens WHERE pedido_id = %s)
               WHERE id = %s AND fornecedor_id = %s
               RETURNING *""",
            (pedido_id, pedido_id, fornecedor_id)
        )
        pedido_atualizado = dict(cur.fetchone())

    return jsonify(pedido_atualizado)


def _pedido_do_fornecedor(fornecedor_id, pedido_id):
    rows = db.query(
        "SELECT id, valor_total, pago_em FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id)
    )
    return rows[0] if rows else None


@bp.post("/<fornecedor_id>/pedidos/<pedido_id>/pago")
@require_auth
@require_admin
def marcar_pedido_pago(fornecedor_id, pedido_id):
    """Caixinha "pago" do pedido.

    modo "lancar": lança o pagamento do valor do pedido, amarrado a ele — é o
    que tira o dinheiro da Caixa da Semana.
    modo "ja_lancado": o Pix já está lançado em Fornecedores; só marca o pedido,
    sem pagamento novo. Recusa se o que já foi pago e não está preso a outro
    pedido marcado não cobre este, porque aí marcar seria inventar dinheiro.
    """
    data = request.get_json() or {}
    modo = data.get("modo")
    if modo not in ("lancar", "ja_lancado"):
        return jsonify({"error": "modo deve ser lancar ou ja_lancado"}), 400
    data_pagamento = data.get("data_pagamento")
    if not data_pagamento or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data_pagamento):
        return jsonify({"error": "data_pagamento obrigatória, no formato AAAA-MM-DD"}), 400

    pedido = _pedido_do_fornecedor(fornecedor_id, pedido_id)
    if not pedido:
        return jsonify({"error": "Pedido não encontrado"}), 404
    if pedido["pago_em"]:
        return jsonify({"error": "Esse pedido já está marcado como pago"}), 409
    valor = float(pedido["valor_total"])

    if modo == "lancar":
        saldo_aberto = _saldo_aberto_fornecedor(fornecedor_id)
        if valor > saldo_aberto + 0.005:
            return jsonify({"error": f"Os pagamentos já lançados cobrem esse pedido (em aberto: R$ {saldo_aberto:.2f}). "
                                     "Use \"Pix já lançado\"."}), 400
        try:
            with db.transaction() as cur:
                cur.execute(
                    """INSERT INTO fin_pagamentos_fornecedor (fornecedor_id, valor, data_pagamento, pedido_id, criado_por)
                       VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                    (fornecedor_id, valor, data_pagamento, pedido_id, g.user["user_id"])
                )
                pagamento = dict(cur.fetchone())
                # Confere que esse valor cabe na compra — uma compra com
                # adiantamento já amarrado pode não ter mais espaço pro valor
                # cheio que esta caixinha está lançando.
                erro = amarracao.validar(cur, pagamento["id"], fornecedor_id,
                                          [{"pedido_id": pedido_id, "valor": valor}])
                if erro:
                    raise _ErroAmarracao(erro)
                cur.execute(
                    """INSERT INTO fin_pagamento_pedido (pagamento_id, pedido_id, valor)
                       VALUES (%s, %s, %s)""",
                    (pagamento["id"], pedido_id, valor),
                )
                cur.execute("UPDATE fin_pedidos_fornecedor SET pago_em = %s WHERE id = %s RETURNING *",
                            (data_pagamento, pedido_id))
                atualizado = dict(cur.fetchone())
        except _ErroAmarracao as e:
            return jsonify({"error": str(e)}), 400
        atualizado["pagamento"] = pagamento
        return jsonify(atualizado), 201

    livre = db.query(
        """SELECT
             COALESCE((SELECT SUM(valor) FROM fin_pagamentos_fornecedor WHERE fornecedor_id = %s), 0)
             - COALESCE((SELECT SUM(valor_total) FROM fin_pedidos_fornecedor
                         WHERE fornecedor_id = %s AND pago_em IS NOT NULL), 0) AS livre""",
        (fornecedor_id, fornecedor_id)
    )
    credito = float(livre[0]["livre"])
    if valor > credito + 0.005:
        return jsonify({"error": f"Os pagamentos lançados não cobrem esse pedido (livre: R$ {max(credito, 0):.2f}). "
                                 "Lance o pagamento."}), 400
    atualizado = db.execute("UPDATE fin_pedidos_fornecedor SET pago_em = %s WHERE id = %s RETURNING *",
                            (data_pagamento, pedido_id))
    return jsonify(atualizado), 201


@bp.delete("/<fornecedor_id>/pedidos/<pedido_id>/pago")
@require_auth
@require_admin
def desmarcar_pedido_pago(fornecedor_id, pedido_id):
    """Desmarca a caixinha e apaga o pagamento amarrado ao pedido, se houver."""
    if not _pedido_do_fornecedor(fornecedor_id, pedido_id):
        return jsonify({"error": "Pedido não encontrado"}), 404
    with db.transaction() as cur:
        # Só apaga o pagamento cuja coluna legada pedido_id apontava pra este
        # pedido (o "lancar" de um pedido só). NÃO apagar direto de
        # fin_pagamento_pedido por pedido_id: isso levaria junto a amarração
        # de outros pagamentos que continuam existindo (ex.: um Pix que também
        # pagou outra compra e não deveria perder essa ligação). A FK já é
        # ON DELETE CASCADE, então o DELETE abaixo sozinho já limpa a ligação
        # do pagamento que de fato foi apagado.
        cur.execute("DELETE FROM fin_pagamentos_fornecedor WHERE pedido_id = %s AND fornecedor_id = %s",
                    (pedido_id, fornecedor_id))
        cur.execute("UPDATE fin_pedidos_fornecedor SET pago_em = NULL WHERE id = %s", (pedido_id,))
    return "", 204


@bp.get("/<fornecedor_id>/pagamentos")
@require_auth
def listar_pagamentos(fornecedor_id):
    rows = db.query(
        """SELECT pg.*,
                   -- Fix round 1 (item 2 da revisão, CRITICAL): sem isto, depois de
                   -- amarrar o Pix desaparece de "Pix sem compra" e nenhum lugar da
                   -- tela mostra a que compra ele ficou amarrado — a única saída
                   -- virava apagar o pagamento inteiro e relançar.
                   COALESCE(
                     (SELECT json_agg(
                        json_build_object(
                          'pedido_id', lig.pedido_id, 'numero_pedido', ped.numero_pedido,
                          'data_pedido', ped.data_pedido, 'valor', lig.valor
                        ) ORDER BY ped.data_pedido
                      ) FROM fin_pagamento_pedido lig
                        JOIN fin_pedidos_fornecedor ped ON ped.id = lig.pedido_id
                        WHERE lig.pagamento_id = pg.id), '[]'
                   ) AS amarracoes
            FROM fin_pagamentos_fornecedor pg
            WHERE pg.fornecedor_id = %s
            ORDER BY pg.data_pagamento, pg.created_at""",
        (fornecedor_id,)
    )
    return jsonify(rows)


@bp.get("/<fornecedor_id>/pagamentos/soltos")
@require_auth
def pagamentos_soltos(fornecedor_id):
    """Pix daquele fornecedor que ainda não dizem qual compra pagaram."""
    rows = db.query(
        """SELECT pg.id, pg.valor, pg.data_pagamento, pg.arquivo_path
           FROM fin_pagamentos_fornecedor pg
           WHERE pg.fornecedor_id = %s
             AND NOT EXISTS (SELECT 1 FROM fin_pagamento_pedido lig WHERE lig.pagamento_id = pg.id)
           ORDER BY pg.data_pagamento DESC""",
        (fornecedor_id,),
    )
    return jsonify(rows)


@bp.post("/<fornecedor_id>/pagamentos/<pagamento_id>/pedidos")
@require_auth
@require_admin
def amarrar_pagamento(fornecedor_id, pagamento_id):
    if not db.query(
        "SELECT id FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pagamento_id, fornecedor_id),
    ):
        return jsonify({"error": "Pagamento não encontrado"}), 404

    itens = (request.get_json() or {}).get("itens")
    if not isinstance(itens, list):
        return jsonify({"error": "itens obrigatório (lista)"}), 400

    with db.transaction() as cur:
        erro = amarracao.validar(cur, pagamento_id, fornecedor_id, itens)
        if erro:
            return jsonify({"error": erro}), 400
        cur.execute("DELETE FROM fin_pagamento_pedido WHERE pagamento_id = %s", (pagamento_id,))
        for item in itens:
            cur.execute(
                """INSERT INTO fin_pagamento_pedido (pagamento_id, pedido_id, valor)
                   VALUES (%s, %s, %s)""",
                (pagamento_id, item["pedido_id"], float(item["valor"])),
            )
    return jsonify({"itens": itens})


def _limpar_pago_em_orfao(cur, pedido_ids, ignorar_pagamento=None):
    """Tira o `pago_em` das compras que ficaram sem nenhuma baixa.

    "Sem baixa" é: nenhuma linha em fin_pagamento_pedido E nenhum pagamento
    legado apontando pela coluna `pedido_id`. Uma compra quitada por outro
    Pix continua paga — era o bug do IMPORTANT 4.
    """
    for pedido_id in dict.fromkeys(p for p in pedido_ids if p):
        cur.execute(
            """UPDATE fin_pedidos_fornecedor SET pago_em = NULL
               WHERE id = %s
                 AND NOT EXISTS (SELECT 1 FROM fin_pagamento_pedido lig
                                 WHERE lig.pedido_id = %s)
                 AND NOT EXISTS (SELECT 1 FROM fin_pagamentos_fornecedor pg
                                 WHERE pg.pedido_id = %s AND (%s IS NULL OR pg.id <> %s))""",
            (pedido_id, pedido_id, pedido_id, ignorar_pagamento, ignorar_pagamento),
        )


@bp.delete("/<fornecedor_id>/pagamentos/<pagamento_id>/pedidos")
@require_auth
@require_admin
def desamarrar_pagamento(fornecedor_id, pagamento_id):
    """Desfaz as amarrações do Pix — e apaga o rastro que a coluna legada deixa.

    Fix round 3 (CRITICAL 1): apagar só as linhas de fin_pagamento_pedido
    deixava `fin_pagamentos_fornecedor.pedido_id` apontando para a compra e o
    `pago_em` dela preenchido. Depois disso, desmarcar a caixinha "Pago"
    daquela compra roda DELETE ... WHERE pedido_id = ... e apaga o Pix
    INTEIRO — levando por CASCADE as amarrações de outras compras e deixando
    o comprovante órfão; a Caixa da Semana mostra a dívida de volta.

    Por isso, além de apagar os links: limpa a coluna legada do pagamento e
    tira o `pago_em` das compras que ficaram sem nenhuma amarração (e sem
    outro pagamento legado apontando para elas).
    """
    linhas = db.query(
        "SELECT id, pedido_id FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pagamento_id, fornecedor_id),
    )
    if not linhas:
        return jsonify({"error": "Pagamento não encontrado"}), 404

    with db.transaction() as cur:
        cur.execute("SELECT pedido_id FROM fin_pagamento_pedido WHERE pagamento_id = %s",
                    (pagamento_id,))
        afetados = [r["pedido_id"] for r in (cur.fetchall() or [])]
        if linhas[0].get("pedido_id"):
            afetados.append(linhas[0]["pedido_id"])
        cur.execute("DELETE FROM fin_pagamento_pedido WHERE pagamento_id = %s", (pagamento_id,))
        cur.execute("UPDATE fin_pagamentos_fornecedor SET pedido_id = NULL WHERE id = %s",
                    (pagamento_id,))
        _limpar_pago_em_orfao(cur, afetados)
    return "", 204


@bp.post("/<fornecedor_id>/pagamentos/ler")
@require_auth
@require_admin
def ler_comprovante_arquivo(fornecedor_id):
    dados, mime, erro = anexos.ler_arquivo_enviado()
    if erro:
        return erro

    try:
        lido = leitura_documento.ler_comprovante(dados, mime)
    except leitura_documento.LeituraIndisponivel as e:
        print(f"[leitura_documento] indisponível ao ler comprovante: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": MSG_LEITURA_INDISPONIVEL}), 503
    except leitura_documento.LeituraFalhou as e:
        print(f"[leitura_documento] falhou ao ler comprovante: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        lido = None

    # Guardar o arquivo é o acessório: se o Storage falhar, ela ainda lança o
    # que a IA leu — só sem o anexo. Bloquear aqui seria perder a leitura toda.
    aviso = None
    try:
        token = anexos.subir_pendente(dados, mime)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao guardar arquivo do comprovante: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        token = None
        aviso = MSG_ANEXO_NAO_GUARDADO

    if lido is None:
        return jsonify({
            "leitura_falhou": True, "arquivo_token": token, "aviso": aviso,
            "valor": None, "data_pagamento": None, "destinatario": None,
            "id_transacao": None, "fornecedor_sugerido_id": None, "pagamento_existente": None,
        })

    existente = None
    if lido["id_transacao"]:
        rows = db.query(
            "SELECT id, data_pagamento, valor FROM fin_pagamentos_fornecedor WHERE id_transacao = %s",
            (lido["id_transacao"],),
        )
        if rows:
            existente = {"id": rows[0]["id"], "data_pagamento": rows[0]["data_pagamento"],
                         "valor": float(rows[0]["valor"])}

    return jsonify({
        "leitura_falhou": False,
        "arquivo_token": token,
        "aviso": aviso,
        "valor": lido["valor"],
        "data_pagamento": lido["data_pagamento"],
        "destinatario": lido["destinatario"],
        "id_transacao": lido["id_transacao"],
        "fornecedor_sugerido_id": aliases.sugerir_fornecedor(lido["destinatario"], "destinatario"),
        "pagamento_existente": existente,
    })


@bp.post("/<fornecedor_id>/pagamentos")
@require_auth
@require_admin
def registrar_pagamento(fornecedor_id):
    data = request.get_json()
    try:
        valor = float(data.get("valor"))
    except (TypeError, ValueError):
        return jsonify({"error": "valor inválido"}), 400
    if valor <= 0:
        return jsonify({"error": "valor deve ser maior que zero"}), 400
    if not data.get("data_pagamento"):
        return jsonify({"error": "data_pagamento obrigatória"}), 400

    fornecedores = db.query("SELECT id FROM fin_fornecedores WHERE id = %s AND ativo = true", (fornecedor_id,))
    if not fornecedores:
        return jsonify({"error": "Fornecedor não encontrado"}), 404

    saldo_aberto = _saldo_aberto_fornecedor(fornecedor_id)
    if valor > saldo_aberto:
        return jsonify({"error": f"Valor maior que o saldo em aberto (R$ {saldo_aberto:.2f})"}), 400

    id_transacao = (data.get("id_transacao") or "").strip() or None
    arquivo_token = (data.get("arquivo_token") or "").strip() or None
    pedido_id = (data.get("pedido_id") or "").strip() or None
    pedido_amarrado = None
    if pedido_id:
        pedido_amarrado = _pedido_do_fornecedor(fornecedor_id, pedido_id)
        if not pedido_amarrado:
            return jsonify({"error": "Pedido não encontrado"}), 404
    alias_destinatario = data.get("alias_destinatario")

    if arquivo_token and not anexos.arquivo_token_valido(arquivo_token):
        return jsonify({"error": "arquivo_token inválido"}), 400

    # Checagem antes do INSERT para responder 409 com mensagem; o índice único
    # parcial no banco segue como garantia final.
    if id_transacao:
        repetidos = db.query(
            "SELECT id, data_pagamento, valor FROM fin_pagamentos_fornecedor WHERE id_transacao = %s",
            (id_transacao,)
        )
        if repetidos:
            quando = repetidos[0]["data_pagamento"]
            quando = quando.strftime("%d/%m/%Y") if hasattr(quando, "strftime") else quando
            return jsonify({"error": f"Esse comprovante já foi lançado em {quando} "
                                     f"(R$ {float(repetidos[0]['valor']):.2f})"}), 409

    row = db.execute(
        """INSERT INTO fin_pagamentos_fornecedor (fornecedor_id, valor, data_pagamento, id_transacao, pedido_id, criado_por)
           VALUES (%s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (fornecedor_id, valor, data["data_pagamento"], id_transacao, pedido_id, g.user["user_id"])
    )
    # Pedido subido já pago: a caixinha nasce marcada.
    if pedido_id:
        db.execute("UPDATE fin_pedidos_fornecedor SET pago_em = %s WHERE id = %s",
                   (data["data_pagamento"], pedido_id))
        # O link vale no máximo o que cabe na compra: um Pix maior que o
        # pedido não pode amarrar mais do que o valor_total dele.
        valor_link = min(valor, float(pedido_amarrado["valor_total"]))
        db.execute(
            """INSERT INTO fin_pagamento_pedido (pagamento_id, pedido_id, valor)
               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
            (row["id"], pedido_id, valor_link),
        )

    # O pagamento já está gravado: o alias vale mesmo que o anexo falhe abaixo.
    _aprender_alias_silencioso(fornecedor_id, alias_destinatario, "destinatario")

    if arquivo_token:
        destino = anexos.destino_anexo(fornecedor_id, "pagamentos", row["id"], arquivo_token)
        try:
            storage.mover(arquivo_token, destino)
        except storage.StorageErro as e:
            # O pagamento já está gravado (é db.execute, não transação): não
            # desfazer — ela vê o pagamento sem clipe e pode subir de novo depois.
            print(f"[storage] falhou ao mover anexo do pagamento: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            row["arquivo_path"] = None
            row["aviso"] = "Pagamento salvo, mas o anexo não pôde ser guardado."
            return jsonify(row), 201
        row = db.execute(
            "UPDATE fin_pagamentos_fornecedor SET arquivo_path = %s WHERE id = %s RETURNING *",
            (destino, row["id"])
        )

    return jsonify(row), 201


@bp.put("/<fornecedor_id>/pagamentos/<pagamento_id>")
@require_auth
@require_admin
def editar_pagamento(fornecedor_id, pagamento_id):
    data = request.get_json()
    try:
        valor = float(data.get("valor"))
    except (TypeError, ValueError):
        return jsonify({"error": "valor inválido"}), 400
    if valor <= 0:
        return jsonify({"error": "valor deve ser maior que zero"}), 400
    if not data.get("data_pagamento"):
        return jsonify({"error": "data_pagamento obrigatória"}), 400

    pagamentos_atuais = db.query(
        "SELECT valor FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pagamento_id, fornecedor_id)
    )
    if not pagamentos_atuais:
        return jsonify({"error": "Pagamento não encontrado"}), 404
    valor_atual = float(pagamentos_atuais[0]["valor"])

    amarrado = db.query(
        "SELECT COALESCE(SUM(valor), 0) AS amarrado FROM fin_pagamento_pedido WHERE pagamento_id = %s",
        (pagamento_id,)
    )
    total_amarrado = float(amarrado[0]["amarrado"])
    if valor < total_amarrado - amarracao.TOLERANCIA:
        return jsonify({"error": f"Esse pagamento está amarrado a R$ {total_amarrado:.2f} em compras — "
                                 "desamarre antes de baixar o valor."}), 400

    saldo_sem_este = _saldo_aberto_fornecedor(fornecedor_id) + valor_atual
    if valor > saldo_sem_este:
        return jsonify({"error": f"Valor maior que o saldo disponível (R$ {saldo_sem_este:.2f})"}), 400

    row = db.execute(
        """UPDATE fin_pagamentos_fornecedor SET valor = %s, data_pagamento = %s
           WHERE id = %s AND fornecedor_id = %s
           RETURNING *""",
        (valor, data["data_pagamento"], pagamento_id, fornecedor_id)
    )
    return jsonify(row)


@bp.delete("/<fornecedor_id>/pagamentos/<pagamento_id>")
@require_auth
@require_admin
def excluir_pagamento(fornecedor_id, pagamento_id):
    """Apaga o Pix e devolve à dívida só as compras que ficaram sem baixa.

    Fix round 3 (IMPORTANT 4): a limpeza olhava só a coluna legada
    `pedido_id`. Um Pix amarrado a duas compras deixava as duas marcadas
    como pagas sem pagamento nenhum, e um Pix legado podia limpar o
    `pago_em` de uma compra que outro Pix já tinha quitado. A limpeza agora
    sai dos links (mais a coluna legada, que ainda existe) e só zera
    `pago_em` de compra que ficou sem nenhuma amarração e sem outro
    pagamento legado apontando para ela.
    """
    pagamentos = db.query(
        "SELECT id, pedido_id FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pagamento_id, fornecedor_id)
    )
    if not pagamentos:
        return jsonify({"error": "Pagamento não encontrado"}), 404

    with db.transaction() as cur:
        cur.execute("SELECT pedido_id FROM fin_pagamento_pedido WHERE pagamento_id = %s",
                    (pagamento_id,))
        afetados = [r["pedido_id"] for r in (cur.fetchall() or [])]
        if pagamentos[0].get("pedido_id"):
            afetados.append(pagamentos[0]["pedido_id"])
        # O CASCADE da FK já leva as linhas de fin_pagamento_pedido junto.
        cur.execute("DELETE FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id = %s",
                    (pagamento_id, fornecedor_id))
        _limpar_pago_em_orfao(cur, afetados, ignorar_pagamento=pagamento_id)
    return "", 204


@bp.get("/<fornecedor_id>/pedidos/<pedido_id>/anexo")
@require_auth
def anexo_pedido(fornecedor_id, pedido_id):
    return anexos.url_anexo("fin_pedidos_fornecedor", "fornecedor_id", fornecedor_id, pedido_id)


@bp.post("/<fornecedor_id>/pedidos/<pedido_id>/nf")
@require_auth
@require_admin
def subir_nf_pedido(fornecedor_id, pedido_id):
    """Nota fiscal da compra. Sem leitura por IA: é arquivo para a contabilidade,
    não dado que a tela precise entender."""
    rows = db.query(
        "SELECT id FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pedido_id, fornecedor_id),
    )
    if not rows:
        return jsonify({"error": "Pedido não encontrado"}), 404

    dados, mime, erro = anexos.ler_arquivo_enviado()
    if erro:
        return erro

    try:
        token = anexos.subir_pendente(dados, mime)
        destino = anexos.destino_anexo(fornecedor_id, "notas", pedido_id, token)
        storage.mover(token, destino)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao guardar a nota do pedido: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": "Não consegui guardar a nota. Tente de novo."}), 500

    row = db.execute(
        "UPDATE fin_pedidos_fornecedor SET nf_path = %s WHERE id = %s RETURNING nf_path",
        (destino, pedido_id),
    )
    return jsonify({"nf_path": row["nf_path"]})


@bp.get("/<fornecedor_id>/pedidos/<pedido_id>/nf")
@require_auth
def anexo_nf_pedido(fornecedor_id, pedido_id):
    return anexos.url_anexo("fin_pedidos_fornecedor", "fornecedor_id", fornecedor_id,
                            pedido_id, coluna_arquivo="nf_path")


@bp.get("/<fornecedor_id>/pagamentos/<pagamento_id>/anexo")
@require_auth
def anexo_pagamento(fornecedor_id, pagamento_id):
    return anexos.url_anexo("fin_pagamentos_fornecedor", "fornecedor_id", fornecedor_id, pagamento_id)


@bp.get("/<fornecedor_id>/devolucoes")
@require_auth
def listar_devolucoes(fornecedor_id):
    rows = db.query(
        """SELECT d.*, p.numero_pedido
           FROM fin_devolucoes_fornecedor d
           LEFT JOIN fin_pedidos_fornecedor p ON p.id = d.pedido_id
           WHERE d.fornecedor_id = %s
           ORDER BY d.data_devolucao, d.created_at""",
        (fornecedor_id,)
    )
    return jsonify(rows)


@bp.post("/<fornecedor_id>/devolucoes")
@require_auth
@require_admin
def registrar_devolucao(fornecedor_id):
    """Abate o 'Ainda devo' sem ser pagamento. Pode passar do saldo em aberto:
    devolver mais do que se deve deixa crédito com o fornecedor."""
    data = request.get_json() or {}
    try:
        valor = float(data.get("valor"))
    except (TypeError, ValueError):
        return jsonify({"error": "valor inválido"}), 400
    if valor <= 0:
        return jsonify({"error": "valor deve ser maior que zero"}), 400
    data_devolucao = data.get("data_devolucao") or ""
    try:
        date.fromisoformat(data_devolucao)
    except ValueError:
        return jsonify({"error": "data_devolucao obrigatória, no formato AAAA-MM-DD"}), 400
    if not db.query("SELECT id FROM fin_fornecedores WHERE id = %s AND ativo = true", (fornecedor_id,)):
        return jsonify({"error": "Fornecedor não encontrado"}), 404
    pedido_id = (data.get("pedido_id") or "").strip() or None
    if pedido_id and not _pedido_do_fornecedor(fornecedor_id, pedido_id):
        return jsonify({"error": "Pedido não encontrado"}), 404
    descricao = (data.get("descricao") or "").strip() or None
    row = db.execute(
        """INSERT INTO fin_devolucoes_fornecedor (fornecedor_id, pedido_id, valor, data_devolucao, descricao)
           VALUES (%s, %s, %s, %s, %s) RETURNING *""",
        (fornecedor_id, pedido_id, valor, data_devolucao, descricao)
    )
    return jsonify(row), 201


@bp.delete("/<fornecedor_id>/devolucoes/<devolucao_id>")
@require_auth
@require_admin
def excluir_devolucao(fornecedor_id, devolucao_id):
    rows = db.query(
        "SELECT id FROM fin_devolucoes_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (devolucao_id, fornecedor_id)
    )
    if not rows:
        return jsonify({"error": "Devolução não encontrada"}), 404
    db.execute("DELETE FROM fin_devolucoes_fornecedor WHERE id = %s", (devolucao_id,))
    return "", 204
