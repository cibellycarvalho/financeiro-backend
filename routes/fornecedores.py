import re

from flask import Blueprint, request, jsonify, g
import db
import aliases
import leitura_documento
import storage
from auth import require_auth, require_admin

bp = Blueprint("fornecedores", __name__)


def _saldo_aberto_fornecedor(fornecedor_id):
    row = db.query(
        """SELECT
             COALESCE((SELECT SUM(valor_total) FROM fin_pedidos_fornecedor WHERE fornecedor_id = %s), 0)
             - COALESCE((SELECT SUM(valor) FROM fin_pagamentos_fornecedor WHERE fornecedor_id = %s), 0)
             AS saldo_aberto""",
        (fornecedor_id, fornecedor_id)
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
               AS saldo_aberto
        FROM fin_fornecedores f
        WHERE f.ativo = true
        ORDER BY f.nome
    """)
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
                   ) AS itens
            FROM fin_pedidos_fornecedor p
            WHERE p.fornecedor_id = %s
            ORDER BY p.data_pedido DESC""",
        (fornecedor_id,)
    )
    return jsonify(rows)


_TAMANHO_MAX = 10 * 1024 * 1024
MSG_LEITURA_INDISPONIVEL = "Leitura automática indisponível agora. Lance à mão."


def _ler_arquivo_enviado():
    """Valida o multipart 'arquivo'. Devolve (dados, mime, None) ou (None, None, (resposta, status))."""
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        return None, None, (jsonify({"error": "arquivo obrigatório"}), 400)
    mime = arquivo.mimetype
    if mime not in storage.EXTENSOES:
        return None, None, (jsonify({"error": "Só PDF, JPG ou PNG"}), 400)
    dados = arquivo.read()
    if len(dados) > _TAMANHO_MAX:
        return None, None, (jsonify({"error": "Arquivo maior que 10 MB"}), 400)
    return dados, mime, None


def _subir_pendente(dados, mime):
    """Limpa pendentes velhos e sobe o arquivo. Falha de limpeza não impede a leitura."""
    try:
        storage.limpar_pendentes()
    except storage.StorageErro:
        pass
    return storage.enviar_pendente(dados, mime)


# Tokens legítimos sempre vêm de storage.enviar_pendente (uuid4().hex + ext
# aceita). Qualquer outra forma é entrada forjada — sem isso, um token como
# "outro-fornecedor/pedidos/x.pdf" moveria o anexo de outro registro.
_RE_ARQUIVO_TOKEN = re.compile(r"^pendentes/[0-9a-f]{32}\.(pdf|jpg|png)$")


def _arquivo_token_valido(token):
    return bool(token) and _RE_ARQUIVO_TOKEN.match(token) is not None


def _destino_anexo(fornecedor_id, pasta, registro_id, arquivo_token):
    if not _arquivo_token_valido(arquivo_token):
        raise ValueError("arquivo_token inválido")
    ext = arquivo_token.rsplit(".", 1)[-1]
    return f"{fornecedor_id}/{pasta}/{registro_id}.{ext}"


@bp.post("/<fornecedor_id>/pedidos/ler")
@require_auth
@require_admin
def ler_pedido_arquivo(fornecedor_id):
    dados, mime, erro = _ler_arquivo_enviado()
    if erro:
        return erro

    try:
        lido = leitura_documento.ler_pedido(dados, mime)
    except leitura_documento.LeituraIndisponivel:
        return jsonify({"error": MSG_LEITURA_INDISPONIVEL}), 503
    except leitura_documento.LeituraFalhou:
        lido = None

    try:
        token = _subir_pendente(dados, mime)
    except storage.StorageErro:
        return jsonify({"error": "Não consegui guardar o arquivo. Tente de novo."}), 500

    if lido is None:
        return jsonify({
            "leitura_falhou": True, "arquivo_token": token,
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

    if arquivo_token and not _arquivo_token_valido(arquivo_token):
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
                destino = _destino_anexo(fornecedor_id, "pedidos", pedido["id"], arquivo_token)
                storage.mover(arquivo_token, destino)
                cur.execute(
                    "UPDATE fin_pedidos_fornecedor SET arquivo_path = %s WHERE id = %s",
                    (destino, pedido["id"])
                )
                pedido["arquivo_path"] = destino
    except storage.StorageErro:
        return jsonify({"error": "Não consegui guardar o anexo; o pedido não foi salvo. Tente de novo."}), 500

    if alias_vendedor:
        aliases.aprender_alias(fornecedor_id, alias_vendedor, "vendedor")

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


@bp.get("/<fornecedor_id>/pagamentos")
@require_auth
def listar_pagamentos(fornecedor_id):
    rows = db.query(
        "SELECT * FROM fin_pagamentos_fornecedor WHERE fornecedor_id = %s ORDER BY data_pagamento, created_at",
        (fornecedor_id,)
    )
    return jsonify(rows)


@bp.post("/<fornecedor_id>/pagamentos/ler")
@require_auth
@require_admin
def ler_comprovante_arquivo(fornecedor_id):
    dados, mime, erro = _ler_arquivo_enviado()
    if erro:
        return erro

    try:
        lido = leitura_documento.ler_comprovante(dados, mime)
    except leitura_documento.LeituraIndisponivel:
        return jsonify({"error": MSG_LEITURA_INDISPONIVEL}), 503
    except leitura_documento.LeituraFalhou:
        lido = None

    try:
        token = _subir_pendente(dados, mime)
    except storage.StorageErro:
        return jsonify({"error": "Não consegui guardar o arquivo. Tente de novo."}), 500

    if lido is None:
        return jsonify({
            "leitura_falhou": True, "arquivo_token": token,
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
    alias_destinatario = data.get("alias_destinatario")

    if arquivo_token and not _arquivo_token_valido(arquivo_token):
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
        """INSERT INTO fin_pagamentos_fornecedor (fornecedor_id, valor, data_pagamento, id_transacao, criado_por)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING *""",
        (fornecedor_id, valor, data["data_pagamento"], id_transacao, g.user["user_id"])
    )

    # O pagamento já está gravado: o alias vale mesmo que o anexo falhe abaixo.
    if alias_destinatario:
        aliases.aprender_alias(fornecedor_id, alias_destinatario, "destinatario")

    if arquivo_token:
        destino = _destino_anexo(fornecedor_id, "pagamentos", row["id"], arquivo_token)
        try:
            storage.mover(arquivo_token, destino)
        except storage.StorageErro:
            # O pagamento já está gravado (é db.execute, não transação): não
            # desfazer — ela vê o pagamento sem clipe e pode subir de novo depois.
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
    pagamentos = db.query(
        "SELECT id FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pagamento_id, fornecedor_id)
    )
    if not pagamentos:
        return jsonify({"error": "Pagamento não encontrado"}), 404

    db.execute(
        "DELETE FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id = %s",
        (pagamento_id, fornecedor_id)
    )
    return "", 204


def _url_anexo(tabela, registro_id, fornecedor_id):
    rows = db.query(
        f"SELECT arquivo_path FROM {tabela} WHERE id = %s AND fornecedor_id = %s",
        (registro_id, fornecedor_id)
    )
    if not rows or not rows[0]["arquivo_path"]:
        return jsonify({"error": "Sem anexo"}), 404
    try:
        return jsonify({"url": storage.url_assinada(rows[0]["arquivo_path"])})
    except storage.StorageErro:
        return jsonify({"error": "Não consegui abrir o anexo agora. Tente de novo."}), 500


@bp.get("/<fornecedor_id>/pedidos/<pedido_id>/anexo")
@require_auth
def anexo_pedido(fornecedor_id, pedido_id):
    return _url_anexo("fin_pedidos_fornecedor", pedido_id, fornecedor_id)


@bp.get("/<fornecedor_id>/pagamentos/<pagamento_id>/anexo")
@require_auth
def anexo_pagamento(fornecedor_id, pagamento_id):
    return _url_anexo("fin_pagamentos_fornecedor", pagamento_id, fornecedor_id)
