"""Contas bancárias: qualquer banco, uma principal (26/10/2026).

O saldo da principal entra no "Pode gastar hoje"; as outras aparecem só como
informação. O saldo pode ser digitado ou vir do extrato OFX (27/10/2026), que
também traz os movimentos para conciliar.
"""
from datetime import timedelta

import re

from flask import Blueprint, request, jsonify, g

import aliases
import db
import conciliacao
import leitura_documento
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


_MAX_OFX = 5 * 1024 * 1024


def _candidatos(de, ate):
    """O que já está lançado no sistema e pode ser a saída do extrato."""
    contas = db.query(
        """SELECT id, valor, COALESCE(data_pagamento, vencimento) AS data, descricao, status
             FROM fin_contas_pagar
            WHERE COALESCE(data_pagamento, vencimento) BETWEEN %s AND %s""", (de, ate))
    fornec = db.query(
        """SELECT pg.id, pg.valor, pg.data_pagamento AS data, COALESCE(f.apelido, f.nome) AS nome
             FROM fin_pagamentos_fornecedor pg JOIN fin_fornecedores f ON f.id = pg.fornecedor_id
            WHERE pg.data_pagamento BETWEEN %s AND %s""", (de, ate))
    func = db.query(
        """SELECT l.id, l.valor, l.pago_em AS data, l.tipo, f.nome
             FROM fin_funcionario_lancamentos l JOIN fin_funcionarios f ON f.id = l.funcionario_id
            WHERE l.tipo IN ('pagamento', 'das') AND l.pago_em BETWEEN %s AND %s""", (de, ate))
    return (
        [{"tipo": "conta", "id": c["id"], "valor": c["valor"], "data": c["data"], "pago": c["status"] == "pago",
          "texto": f"Conta: {c['descricao']}"} for c in contas]
        + [{"tipo": "fornecedor", "id": p["id"], "valor": p["valor"], "data": p["data"], "pago": True,
            "texto": f"Pagamento a {p['nome']}"} for p in fornec]
        + [{"tipo": "funcionario", "id": l["id"], "valor": l["valor"], "data": l["data"], "pago": True,
            "texto": f"{'DAS' if l['tipo'] == 'das' else 'Pagamento'} de {l['nome']}"} for l in func]
    )


@bp.post("/<conta_id>/extrato")
@require_auth
def importar_extrato(conta_id):
    arq = request.files.get("arquivo")
    if not arq:
        return jsonify({"error": "envie o extrato (OFX ou PDF) no campo 'arquivo'"}), 400
    bruto = arq.read(_MAX_OFX + 1)
    if len(bruto) > _MAX_OFX:
        return jsonify({"error": "arquivo maior que 5 MB"}), 400
    # PDF (27/10/2026): nem todo banco dá OFX fácil; o PDF é lido pela IA,
    # como os comprovantes. O resto do caminho é o mesmo.
    if bruto[:5] == b"%PDF-":
        try:
            lido = leitura_documento.ler_extrato(bruto, "application/pdf")
        except leitura_documento.LeituraIndisponivel:
            return jsonify({"error": "a leitura de PDF está fora do ar agora. Tente de novo ou envie em OFX."}), 503
        except leitura_documento.LeituraFalhou as e:
            return jsonify({"error": f"não consegui ler o PDF: {e}. Tente o OFX."}), 422
    else:
        try:
            lido = conciliacao.ler_ofx(bruto)
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"não consegui ler o extrato: {e}. Envie em OFX ou PDF."}), 400
    if not db.query("SELECT id FROM fin_contas_bancarias WHERE id = %s", (conta_id,)):
        return jsonify({"error": "conta não encontrada"}), 404
    movs = lido["movimentos"]
    novos = 0
    if movs:
        de = min(m["data"] for m in movs) - timedelta(days=3)
        ate = max(m["data"] for m in movs) + timedelta(days=3)
        cands = _candidatos(de.isoformat(), ate.isoformat())
        with db.transaction() as cur:
            for m in movs:
                s = conciliacao.sugerir(m, cands)
                # ON CONFLICT: o mesmo extrato enviado duas vezes não duplica nada
                # nem desfaz o que ela já confirmou.
                cur.execute(
                    """INSERT INTO fin_extrato_movimentos
                         (conta_bancaria_id, fitid, data, valor, descricao, status, casado_tipo, casado_id, casado_texto)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (conta_bancaria_id, fitid) DO NOTHING RETURNING id""",
                    (conta_id, m["fitid"], m["data"], m["valor"], m["descricao"],
                     s["status"], s["casado_tipo"], s["casado_id"], s["casado_texto"]))
                if cur.fetchone():
                    novos += 1
            if lido["saldo"] is not None:
                cur.execute("UPDATE fin_contas_bancarias SET saldo = %s, saldo_em = now() WHERE id = %s",
                            (lido["saldo"], conta_id))
    elif lido["saldo"] is not None:
        db.execute("UPDATE fin_contas_bancarias SET saldo = %s, saldo_em = now() WHERE id = %s",
                   (lido["saldo"], conta_id))
    return jsonify({"lidos": len(movs), "novos": novos, "saldo": lido["saldo"]}), 201


@bp.get("/<conta_id>/extrato")
@require_auth
def listar_extrato(conta_id):
    de, ate = request.args.get("de"), request.args.get("ate")
    cond, params = ["conta_bancaria_id = %s"], [conta_id]
    if de:
        cond.append("data >= %s"); params.append(de)
    if ate:
        cond.append("data <= %s"); params.append(ate)
    rows = db.query(
        f"SELECT * FROM fin_extrato_movimentos WHERE {' AND '.join(cond)} ORDER BY data DESC, created_at LIMIT 500",
        tuple(params))
    _sugerir_fornecedores(rows)
    return jsonify(rows)


_RE_BENEFICIARIO = re.compile(r"(?:enviado|enviada)\s+(?:para|a)\s+(.+)$", re.I)


def _beneficiario(descricao):
    """Nome de quem recebeu, como o banco escreve: "Pagamento de boleto enviado
    para MXT CENTER COMERCIO D" -> "MXT CENTER COMERCIO D"."""
    m = _RE_BENEFICIARIO.search((descricao or "").strip())
    return m.group(1).strip() if m else None


def _sugerir_fornecedores(rows):
    """Saída ainda sem destino cujo beneficiário já é alias de um fornecedor
    ganha `fornecedor_sugerido` — o painel oferece lançar como pagamento dele."""
    achados = {}
    for r in rows:
        if r.get("status") != "novo" or float(r.get("valor") or 0) >= 0:
            continue
        nome = _beneficiario(r.get("descricao"))
        if not nome:
            continue
        if nome not in achados:
            achados[nome] = aliases.sugerir_fornecedor(nome, "destinatario")
        fid = achados[nome]
        if fid:
            forn = db.query("SELECT id, COALESCE(apelido, nome) AS nome FROM fin_fornecedores WHERE id = %s", (fid,))
            if forn:
                r["fornecedor_sugerido"] = {"id": forn[0]["id"], "nome": forn[0]["nome"]}


@bp.put("/<conta_id>/extrato/<mov_id>")
@require_auth
def decidir_movimento(conta_id, mov_id):
    """acao: 'confirmar' (aceita a sugestão), 'ignorar' ou 'reabrir'.
    Confirmar uma conta a pagar ainda em aberto a dá como paga na data do extrato."""
    corpo = request.get_json(silent=True) or {}
    acao = corpo.get("acao")
    if acao == "lancar_fornecedor":
        return _lancar_como_pagamento(conta_id, mov_id, corpo.get("fornecedor_id"))
    novo = {"confirmar": "casado", "ignorar": "ignorado", "reabrir": "novo"}.get(acao)
    if not novo:
        return jsonify({"error": "acao deve ser confirmar, ignorar, reabrir ou lancar_fornecedor"}), 400
    with db.transaction() as cur:
        cur.execute("SELECT * FROM fin_extrato_movimentos WHERE id = %s AND conta_bancaria_id = %s FOR UPDATE",
                    (mov_id, conta_id))
        mov = cur.fetchone()
        if not mov:
            return jsonify({"error": "movimento não encontrado"}), 404
        if acao == "confirmar" and not mov["casado_texto"]:
            return jsonify({"error": "nada sugerido para confirmar"}), 400
        if acao == "confirmar" and mov["casado_tipo"] == "conta":
            cur.execute("""UPDATE fin_contas_pagar SET status = 'pago', data_pagamento = COALESCE(data_pagamento, %s)
                            WHERE id = %s""", (mov["data"], mov["casado_id"]))
        if acao == "reabrir":
            cur.execute("""UPDATE fin_extrato_movimentos SET status = 'novo', casado_tipo = NULL, casado_id = NULL,
                            casado_texto = NULL WHERE id = %s RETURNING *""", (mov_id,))
        else:
            cur.execute("UPDATE fin_extrato_movimentos SET status = %s WHERE id = %s RETURNING *", (novo, mov_id))
        row = cur.fetchone()
    return jsonify(dict(row))


def _lancar_como_pagamento(conta_id, mov_id, fornecedor_id):
    """Saída do extrato que ninguém lançou (boleto pago, por exemplo) vira
    pagamento do fornecedor: o dinheiro já saiu do banco, então o "Ainda devo"
    cai na hora, como acontece com o Pix. Aceita passar do saldo em aberto —
    o banco é a prova de que o dinheiro saiu."""
    if not fornecedor_id:
        return jsonify({"error": "escolha o fornecedor"}), 400
    if not db.query("SELECT id FROM fin_fornecedores WHERE id = %s AND ativo = true", (fornecedor_id,)):
        return jsonify({"error": "fornecedor não encontrado"}), 404
    with db.transaction() as cur:
        cur.execute("SELECT * FROM fin_extrato_movimentos WHERE id = %s AND conta_bancaria_id = %s FOR UPDATE",
                    (mov_id, conta_id))
        mov = cur.fetchone()
        if not mov:
            return jsonify({"error": "movimento não encontrado"}), 404
        if float(mov["valor"]) >= 0:
            return jsonify({"error": "só uma saída do banco pode virar pagamento"}), 400
        if mov["status"] == "casado":
            return jsonify({"error": "esse movimento já está casado com outro lançamento"}), 409
        cur.execute(
            """INSERT INTO fin_pagamentos_fornecedor (fornecedor_id, valor, data_pagamento, criado_por)
               VALUES (%s, %s, %s, %s) RETURNING id""",
            (fornecedor_id, round(-float(mov["valor"]), 2), mov["data"], g.user["user_id"]))
        pagamento_id = cur.fetchone()["id"]
        cur.execute("SELECT COALESCE(apelido, nome) AS nome FROM fin_fornecedores WHERE id = %s", (fornecedor_id,))
        nome = cur.fetchone()["nome"]
        cur.execute(
            """UPDATE fin_extrato_movimentos
                  SET status = 'casado', casado_tipo = 'fornecedor', casado_id = %s, casado_texto = %s
                WHERE id = %s RETURNING *""",
            (pagamento_id, f"Pagamento a {nome}", mov_id))
        row = cur.fetchone()
    # Na próxima vez o mesmo beneficiário já vem com o fornecedor sugerido. O
    # registro está gravado: aprender o alias nunca vale um erro.
    try:
        aliases.aprender_alias(fornecedor_id, _beneficiario(mov["descricao"]), "destinatario")
    except Exception as e:
        print(f"[bancos] alias não aprendido: {type(e).__name__}: {e}", flush=True)
    return jsonify(dict(row)), 201
