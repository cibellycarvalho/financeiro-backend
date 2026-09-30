import calendar
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, request, jsonify, g
import anexos
import db
import storage
from auth import require_auth, require_admin

bp = Blueprint("contas", __name__)

FUSO = ZoneInfo("America/Sao_Paulo")

COLUNA_ANEXO = {"nf": "nf_path", "comprovante": "comprovante_path"}


def _hoje():
    # O servidor roda em UTC: depois das 21h ele ja esta no dia seguinte.
    return datetime.now(FUSO).date()

CATEGORIAS_VALIDAS = {"FORNECEDOR", "CONTABILIDADE", "IMPOSTO_DAS", "SISTEMA", "OUTRO"}
MARCAS_VALIDAS = {"YUSO", "M12", "GERAL"}
STATUS_VALIDOS = {"pendente", "a_confirmar", "pago", "vencido"}

@bp.get("")
@require_auth
def listar():
    periodo = request.args.get("periodo")
    status = request.args.get("status")
    marca = request.args.get("marca")

    conditions = ["1=1"]
    params = []

    # Periodo = o que vence dentro dele MAIS o que ja venceu e continua em aberto.
    # Antes "semana" era hoje ate hoje+7: na quinta o boleto de segunda sumia da
    # lista, ela achava que nao tinha salvo e lancava de novo (17/09/2026).
    if periodo in ("semana", "mes"):
        hoje = _hoje()
        if periodo == "semana":
            inicio = hoje - timedelta(days=hoje.weekday())
            fim = inicio + timedelta(days=6)
        else:
            inicio = hoje.replace(day=1)
            fim = hoje.replace(day=calendar.monthrange(hoje.year, hoje.month)[1])
        conditions.append("(vencimento BETWEEN %s AND %s OR (status <> 'pago' AND vencimento < %s))")
        params += [inicio.isoformat(), fim.isoformat(), inicio.isoformat()]

    if status:
        conditions.append("status = %s")
        params.append(status)
    if marca:
        conditions.append("marca = %s")
        params.append(marca)

    where = " AND ".join(conditions)
    rows = db.query(
        f"SELECT * FROM fin_contas_pagar WHERE {where} ORDER BY vencimento ASC",
        tuple(params)
    )
    return jsonify(rows)

@bp.post("")
@require_auth
@require_admin
def criar():
    data = request.get_json()
    descricao = data.get("descricao", "").strip()
    categoria = data.get("categoria", "")
    try:
        valor = float(data.get("valor", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "valor inválido"}), 400
    vencimento = data.get("vencimento")
    marca = data.get("marca", "GERAL")
    observacao = data.get("observacao")

    if not descricao:
        return jsonify({"error": "descricao obrigatória"}), 400
    if categoria not in CATEGORIAS_VALIDAS:
        return jsonify({"error": f"categoria inválida. Valores: {sorted(CATEGORIAS_VALIDAS)}"}), 400
    if marca not in MARCAS_VALIDAS:
        return jsonify({"error": f"marca inválida. Valores: {sorted(MARCAS_VALIDAS)}"}), 400
    if not vencimento:
        return jsonify({"error": "vencimento obrigatório"}), 400

    row = db.execute(
        """INSERT INTO fin_contas_pagar
           (descricao, categoria, valor, vencimento, marca, observacao, criado_por)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           RETURNING *""",
        (descricao, categoria, valor, vencimento, marca, observacao, g.user["user_id"])
    )
    return jsonify(row), 201

@bp.put("/<conta_id>")
@require_auth
@require_admin
def atualizar(conta_id):
    data = request.get_json()
    campos = []
    params = []

    if "status" in data:
        if data["status"] not in STATUS_VALIDOS:
            return jsonify({"error": "status inválido"}), 400
        campos.append("status = %s")
        params.append(data["status"])
    if "data_pagamento" in data:
        campos.append("data_pagamento = %s")
        params.append(data["data_pagamento"])
    if "observacao" in data:
        campos.append("observacao = %s")
        params.append(data["observacao"])
    if "valor" in data:
        campos.append("valor = %s")
        params.append(float(data["valor"]))
    if "vencimento" in data:
        campos.append("vencimento = %s")
        params.append(data["vencimento"])

    if not campos:
        return jsonify({"error": "nenhum campo para atualizar"}), 400

    params.append(conta_id)
    row = db.execute(
        f"UPDATE fin_contas_pagar SET {', '.join(campos)} WHERE id = %s RETURNING *",
        tuple(params)
    )
    if not row:
        return jsonify({"error": "Conta não encontrada"}), 404
    return jsonify(row)

@bp.delete("/<conta_id>")
@require_auth
@require_admin
def deletar(conta_id):
    db.execute("DELETE FROM fin_contas_pagar WHERE id = %s", (conta_id,))
    return "", 204


@bp.post("/<conta_id>/anexo/<tipo>")
@require_auth
@require_admin
def subir_anexo_conta(conta_id, tipo):
    coluna = COLUNA_ANEXO.get(tipo)
    if not coluna:
        return jsonify({"error": "tipo deve ser nf ou comprovante"}), 400

    if not db.query("SELECT id FROM fin_contas_pagar WHERE id = %s", (conta_id,)):
        return jsonify({"error": "Conta não encontrada"}), 404

    dados, mime, erro = anexos.ler_arquivo_enviado()
    if erro:
        return erro

    try:
        token = anexos.subir_pendente(dados, mime)
        destino = anexos.destino_anexo("contas", tipo, conta_id, token)
        storage.mover(token, destino)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao guardar {tipo} da conta: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": "Não consegui guardar o arquivo. Tente de novo."}), 500

    row = db.execute(
        f"UPDATE fin_contas_pagar SET {coluna} = %s WHERE id = %s RETURNING {coluna}",
        (destino, conta_id),
    )
    return jsonify({coluna: row[coluna]})


@bp.get("/<conta_id>/anexo/<tipo>")
@require_auth
def url_anexo_conta(conta_id, tipo):
    coluna = COLUNA_ANEXO.get(tipo)
    if not coluna:
        return jsonify({"error": "tipo deve ser nf ou comprovante"}), 400
    rows = db.query(f"SELECT {coluna} FROM fin_contas_pagar WHERE id = %s", (conta_id,))
    if not rows or not rows[0][coluna]:
        return jsonify({"error": "Sem anexo"}), 404
    try:
        return jsonify({"url": storage.url_assinada(rows[0][coluna])})
    except storage.StorageErro as e:
        print(f"[storage] falhou ao assinar URL da conta: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": "Não consegui abrir o anexo agora."}), 502
