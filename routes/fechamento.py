"""Fechamento mensal: compras, fretes, montagem e despesas.

Portado do CRM (`ml-seller-api/routes/fechamento.py`) em 19/08/2026, com duas
diferenças obrigatórias e nenhuma opcional:

  - acesso ao banco pelos helpers `db.query`/`db.execute` do Painel, em vez do
    cursor cru que o CRM usa;
  - a loja vem de `contas_ml.conta_do_request()`, que é onde mora a trava — no
    CRM ela morava aqui dentro, apoiada em chaves que não existem neste app.

**Portado fiel de propósito.** O CRM aceita `valor_total` (compras) e `total`
(fretes) vindos da tela, sem recalcular. Passar a calcular no servidor durante
uma migração de endereço faria os números divergirem do que ela vê hoje, sem
ninguém ter pedido. Fica registrado como observação para trabalho próprio:
número derivado que o cliente manda pode divergir da soma das partes.

`coleta_sp` é um SIM/NÃO, não um valor em reais — tratar como dinheiro somaria
booleano com real.
"""
from flask import Blueprint, request, jsonify

import contas_ml
import db
from auth import require_auth

bp = Blueprint("fechamento", __name__)


def _mes_ano_valido(mes_ano):
    try:
        ano, mes = str(mes_ano).split("-")
        int(ano)
        return 1 <= int(mes) <= 12
    except Exception:
        return False


def _conta_ou_erro():
    """(conta, erro). O erro já é uma resposta pronta."""
    try:
        return contas_ml.conta_do_request(), None
    except contas_ml.SemConta:
        return None, (jsonify({"error": "usuário sem loja definida"}), 400)


def _serializar(linha):
    """Datas viram texto — o CRM faz o mesmo antes de devolver."""
    if not linha:
        return linha
    saida = dict(linha)
    for chave, valor in saida.items():
        if hasattr(valor, "isoformat"):
            saida[chave] = valor.isoformat()
    return saida


def _listar(tabela):
    mes_ano = request.args.get("mes_ano", "")
    if not _mes_ano_valido(mes_ano):
        return jsonify({"error": "mes_ano inválido (esperado AAAA-MM)"}), 400
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linhas = db.query(
        f"SELECT * FROM {tabela} WHERE conta_ml=%s AND mes_ano=%s ORDER BY id",
        (conta, mes_ano),
    )
    return jsonify([_serializar(l) for l in linhas])


def _excluir(tabela, id):
    """DELETE sempre filtra por loja ALÉM do id: sem isso, um id de outra loja
    seria apagável por quem descobrisse o número."""
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linha = db.execute(
        f"DELETE FROM {tabela} WHERE id=%s AND conta_ml=%s RETURNING id", (id, conta)
    )
    if not linha:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify({"ok": True})


# ── compras ──────────────────────────────────────────────────────────────────

@bp.get("/compras")
@require_auth
def listar_compras():
    return _listar("fechamento_compras")


@bp.post("/compras")
@require_auth
def criar_compra():
    d = request.get_json(silent=True) or {}
    if not _mes_ano_valido(d.get("mes_ano", "")):
        return jsonify({"error": "mes_ano inválido"}), 400
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linha = db.execute(
        """INSERT INTO fechamento_compras
             (conta_ml, mes_ano, data, fornecedor, nota_fiscal, produto,
              quantidade, valor_unitario, valor_total, status, nota)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (conta, d["mes_ano"], d.get("data") or None, d.get("fornecedor") or None,
         d.get("nota_fiscal") or None, d.get("produto") or None,
         d.get("quantidade") or None, d.get("valor_unitario") or None,
         d.get("valor_total") or None, d.get("status") or None,
         d.get("nota") or None),
    )
    return jsonify(_serializar(linha)), 201


@bp.put("/compras/<int:id>")
@require_auth
def editar_compra(id):
    d = request.get_json(silent=True) or {}
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linha = db.execute(
        """UPDATE fechamento_compras
              SET data=%s, fornecedor=%s, nota_fiscal=%s, produto=%s,
                  quantidade=%s, valor_unitario=%s, valor_total=%s,
                  status=%s, nota=%s
            WHERE id=%s AND conta_ml=%s RETURNING *""",
        (d.get("data") or None, d.get("fornecedor") or None,
         d.get("nota_fiscal") or None, d.get("produto") or None,
         d.get("quantidade") or None, d.get("valor_unitario") or None,
         d.get("valor_total") or None, d.get("status") or None,
         d.get("nota") or None, id, conta),
    )
    if not linha:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify(_serializar(linha))


@bp.delete("/compras/<int:id>")
@require_auth
def excluir_compra(id):
    return _excluir("fechamento_compras", id)


# ── fretes ───────────────────────────────────────────────────────────────────

@bp.get("/fretes")
@require_auth
def listar_fretes():
    return _listar("fechamento_fretes")


@bp.post("/fretes")
@require_auth
def criar_frete():
    d = request.get_json(silent=True) or {}
    if not _mes_ano_valido(d.get("mes_ano", "")):
        return jsonify({"error": "mes_ano inválido"}), 400
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linha = db.execute(
        """INSERT INTO fechamento_fretes
             (conta_ml, mes_ano, data, motorista, coleta_sp, frete_full, total, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (conta, d["mes_ano"], d.get("data") or None, d.get("motorista") or None,
         bool(d.get("coleta_sp")), d.get("frete_full") or None,
         d.get("total") or None, d.get("status") or None),
    )
    return jsonify(_serializar(linha)), 201


@bp.put("/fretes/<int:id>")
@require_auth
def editar_frete(id):
    d = request.get_json(silent=True) or {}
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linha = db.execute(
        """UPDATE fechamento_fretes
              SET data=%s, motorista=%s, coleta_sp=%s, frete_full=%s,
                  total=%s, status=%s
            WHERE id=%s AND conta_ml=%s RETURNING *""",
        (d.get("data") or None, d.get("motorista") or None,
         bool(d.get("coleta_sp")), d.get("frete_full") or None,
         d.get("total") or None, d.get("status") or None, id, conta),
    )
    if not linha:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify(_serializar(linha))


@bp.delete("/fretes/<int:id>")
@require_auth
def excluir_frete(id):
    return _excluir("fechamento_fretes", id)


# ── montagem ─────────────────────────────────────────────────────────────────

@bp.get("/montagem")
@require_auth
def listar_montagem():
    return _listar("fechamento_montagem")


@bp.post("/montagem")
@require_auth
def criar_montagem():
    d = request.get_json(silent=True) or {}
    if not _mes_ano_valido(d.get("mes_ano", "")):
        return jsonify({"error": "mes_ano inválido"}), 400
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linha = db.execute(
        """INSERT INTO fechamento_montagem (conta_ml, mes_ano, montador, valor, data)
           VALUES (%s,%s,%s,%s,%s) RETURNING *""",
        (conta, d["mes_ano"], d.get("montador") or None,
         d.get("valor") or None, d.get("data") or None),
    )
    return jsonify(_serializar(linha)), 201


@bp.put("/montagem/<int:id>")
@require_auth
def editar_montagem(id):
    d = request.get_json(silent=True) or {}
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linha = db.execute(
        """UPDATE fechamento_montagem SET montador=%s, valor=%s, data=%s
            WHERE id=%s AND conta_ml=%s RETURNING *""",
        (d.get("montador") or None, d.get("valor") or None,
         d.get("data") or None, id, conta),
    )
    if not linha:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify(_serializar(linha))


@bp.delete("/montagem/<int:id>")
@require_auth
def excluir_montagem(id):
    return _excluir("fechamento_montagem", id)


# ── despesas ─────────────────────────────────────────────────────────────────
#
# CORREÇÃO (19/08): eu tinha deixado `despesas-unificadas` fora, achando que ela
# juntava estas despesas com as importadas da Conta Simples. Lendo o original,
# ela lê a MESMA tabela — as importadas sempre estiveram nela — e só acrescenta o
# total e a marca de editável. E a tela do Fechamento consome ESSA rota. Ela está
# portada no fim deste arquivo.
#
# O CRM também roda um ALTER TABLE por requisição pra garantir a coluna
# `categoria` (_ensure_categoria). Aqui isso vira migração
# (20260819_1500_fechamento_despesas_categoria.sql): comando de alteração de
# tabela a cada gravação já era demais com um serviço, e agora são dois
# escrevendo na mesma tabela.

@bp.get("/despesas")
@require_auth
def listar_despesas():
    return _listar("fechamento_despesas")


@bp.post("/despesas")
@require_auth
def criar_despesa():
    d = request.get_json(silent=True) or {}
    if not _mes_ano_valido(d.get("mes_ano", "")):
        return jsonify({"error": "mes_ano inválido"}), 400
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linha = db.execute(
        """INSERT INTO fechamento_despesas
             (conta_ml, mes_ano, data, categoria, descricao, valor, status)
           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (conta, d["mes_ano"], d.get("data") or None, d.get("categoria") or None,
         d.get("descricao") or None, d.get("valor") or None,
         d.get("status") or None),
    )
    return jsonify(_serializar(linha)), 201


@bp.put("/despesas/<int:id>")
@require_auth
def editar_despesa(id):
    d = request.get_json(silent=True) or {}
    conta, erro = _conta_ou_erro()
    if erro:
        return erro
    linha = db.execute(
        """UPDATE fechamento_despesas
              SET data=%s, categoria=%s, descricao=%s, valor=%s, status=%s
            WHERE id=%s AND conta_ml=%s RETURNING *""",
        (d.get("data") or None, d.get("categoria") or None,
         d.get("descricao") or None, d.get("valor") or None,
         d.get("status") or None, id, conta),
    )
    if not linha:
        return jsonify({"error": "não encontrado"}), 404
    return jsonify(_serializar(linha))


@bp.delete("/despesas/<int:id>")
@require_auth
def excluir_despesa(id):
    return _excluir("fechamento_despesas", id)


@bp.get("/despesas-unificadas")
@require_auth
def despesas_unificadas():
    """Despesas do mês com o total e a marca de editável.

    O nome "unificadas" é herança de quando a tela juntava lançamento manual com
    importação bancária. Lê UMA tabela — as linhas importadas sempre estiveram
    nela. A tela do Fechamento consome esta rota (não a `/despesas`), então ela
    precisa existir aqui para a tela funcionar depois de migrada.

    `editavel = false` para linha com `ext_id`: veio de sincronização bancária e
    é registro do banco, não lançamento à mão. A Conta Simples saiu de uso
    (hoje são Sicredi e Mercado Pago), mas as linhas antigas continuam lá e
    continuam sendo registro bancário.

    O parâmetro é `competencia`, não `mes_ano` — nome que veio do CRM e que a
    tela já manda assim.
    """
    competencia = request.args.get("competencia", "")
    if not _mes_ano_valido(competencia):
        return jsonify({"error": "competencia inválida (esperado AAAA-MM)"}), 400
    conta, erro = _conta_ou_erro()
    if erro:
        return erro

    linhas = db.query(
        "SELECT * FROM fechamento_despesas WHERE conta_ml=%s AND mes_ano=%s ORDER BY id",
        (conta, competencia),
    )
    despesas = [
        {**_serializar(l), "origem": "fechamento_despesas",
         "editavel": not l.get("ext_id")}
        for l in linhas
    ]
    total = sum(float(d["valor"] or 0) for d in despesas)
    return jsonify({"despesas": despesas, "total": round(total, 2)})
