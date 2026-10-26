"""Contas bancárias: qualquer banco, uma principal (26/10/2026).

O saldo da principal entra no "Pode gastar hoje"; as outras aparecem só como
informação. O saldo ainda é digitado — conciliação por extrato vem depois.
"""
from flask import Blueprint, request, jsonify

import db
from auth import require_auth

bp = Blueprint("bancos", __name__)


def _numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@bp.get("")
@require_auth
def listar():
    return jsonify(db.query(
        "SELECT * FROM fin_contas_bancarias WHERE ativo ORDER BY principal DESC, nome"))


@bp.post("")
@require_auth
def criar():
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    if not nome:
        return jsonify({"error": "nome é obrigatório"}), 400
    principal = bool(data.get("principal"))
    with db.transaction() as cur:
        if principal:
            cur.execute("UPDATE fin_contas_bancarias SET principal = false WHERE principal")
        cur.execute(
            "INSERT INTO fin_contas_bancarias (nome, principal) VALUES (%s, %s) RETURNING *",
            (nome, principal))
        row = cur.fetchone()
    return jsonify(dict(row)), 201


@bp.put("/<conta_id>")
@require_auth
def atualizar(conta_id):
    data = request.get_json(silent=True) or {}
    sets, params = [], []
    if "nome" in data:
        nome = (data.get("nome") or "").strip()
        if not nome:
            return jsonify({"error": "nome não pode ficar vazio"}), 400
        sets.append("nome = %s"); params.append(nome)
    if "saldo" in data:
        saldo = data["saldo"]
        if saldo is not None and not _numero(saldo):
            return jsonify({"error": "saldo inválido"}), 400
        # A hora do saldo é a de agora: é quando ela olhou o banco.
        sets.append("saldo = %s, saldo_em = now()"); params.append(saldo)
    if "ativo" in data:
        sets.append("ativo = %s"); params.append(bool(data["ativo"]))
    principal = data.get("principal") is True
    if principal:
        sets.append("principal = true")
    if not sets:
        return jsonify({"error": "nada para atualizar"}), 400
    with db.transaction() as cur:
        if principal:
            cur.execute("UPDATE fin_contas_bancarias SET principal = false WHERE principal AND id <> %s",
                        (conta_id,))
        cur.execute(f"UPDATE fin_contas_bancarias SET {', '.join(sets)} WHERE id = %s RETURNING *",
                    (*params, conta_id))
        row = cur.fetchone()
    if not row:
        return jsonify({"error": "conta não encontrada"}), 404
    return jsonify(dict(row))
