"""Funcionários (prestadores MEI): pagamento, DAS e NF por mês de competência.

Uma tabela para os três tipos (fin_funcionario_lancamentos, coluna `tipo`).
O mês de uma pessoa é o das linhas com aquela competência; "o que falta?" é
olhar quais tipos não têm linha. Os endpoints /ler só leem — nada grava sem o
Salvar dela. Desenho: docs/superpowers/specs/2026-09-17-funcionarios-design.md.
"""
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, request, jsonify, g

import anexos
import db
import leitura_documento
import storage
from auth import require_auth, require_admin

bp = Blueprint("funcionarios", __name__)

FUSO = ZoneInfo("America/Sao_Paulo")
TIPOS = ("pagamento", "das", "nf")
ROTULO_TIPO = {"pagamento": "pagamento", "das": "DAS", "nf": "NF"}
_RE_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# (campo no JSON, coluna no banco, sufixo no nome do arquivo)
ANEXOS = (
    ("arquivo_token", "arquivo_path", ""),
    ("boleto_token", "boleto_path", "-boleto"),
    ("comprovante_token", "comprovante_path", "-comprovante"),
)
COLUNAS_ANEXO = {"arquivo": "arquivo_path", "boleto": "boleto_path", "comprovante": "comprovante_path"}


def _hoje():
    return datetime.now(FUSO).date()


def _erro(msg, status=400):
    return jsonify({"error": msg}), status


def _competencia(texto):
    """'2026-09' ou '2026-09-15' → date(2026, 9, 1); qualquer outra coisa → None."""
    if not isinstance(texto, str):
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})(?:-\d{2})?", texto.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:
        return None


def _iso(v):
    return v.isoformat() if isinstance(v, date) else v


def _linha(row):
    """Datas viram texto 'AAAA-MM-DD': a tela compara e mostra sem parsear RFC-1123."""
    if row is None:
        return None
    r = dict(row)
    for k in ("competencia", "vencimento", "pago_em"):
        if k in r:
            r[k] = _iso(r[k])
    if r.get("valor") is not None:
        r["valor"] = float(r["valor"])
    return r


def _resumo(linhas):
    """O que o mês tem e o que falta. Completo = ≥1 pagamento, DAS pago, NF lançada."""
    pagamentos = [l for l in linhas if l["tipo"] == "pagamento"]
    das = next((l for l in linhas if l["tipo"] == "das"), None)
    nf = next((l for l in linhas if l["tipo"] == "nf"), None)
    falta = [t for t, tem in (("pagamento", bool(pagamentos)), ("das", das is not None), ("nf", nf is not None)) if not tem]
    das_em_aberto = das is not None and not das.get("pago_em")
    return {
        "falta": falta,
        "das_em_aberto": das_em_aberto,
        "das_vencimento": _iso(das.get("vencimento")) if das else None,
        "completo": not falta and not das_em_aberto,
        "total_pago": sum(float(p["valor"] or 0) for p in pagamentos),
        "das_valor": float(das["valor"]) if das and das.get("valor") is not None else None,
        "nf_valor": float(nf["valor"]) if nf and nf.get("valor") is not None else None,
        "nf_numero": nf.get("numero_nf") if nf else None,
    }


def _funcionario(fid):
    rows = db.query("SELECT * FROM fin_funcionarios WHERE id = %s AND ativo = true", (fid,))
    return rows[0] if rows else None


def _campos_cadastro(data):
    """Devolve (nome, cnpj, valor_combinado, erro)."""
    nome_bruto = data.get("nome")
    nome = nome_bruto.strip() if isinstance(nome_bruto, str) else ""
    if not nome:
        return None, None, None, "nome obrigatório"
    cnpj_bruto = data.get("cnpj")
    cnpj = None
    if cnpj_bruto not in (None, ""):
        # str() antes do regex: um CNPJ pode chegar como número do JSON
        # (12345678000195), e um valor solto (lista/objeto) precisa virar
        # "lixo" que falha na checagem de tamanho em vez de estourar aqui.
        cnpj = re.sub(r"\D", "", str(cnpj_bruto))
        if len(cnpj) != 14:
            return None, None, None, "CNPJ precisa ter 14 dígitos"
    valor = data.get("valor_combinado")
    if valor in (None, ""):
        valor = None
    else:
        try:
            valor = float(valor)
        except (TypeError, ValueError):
            return None, None, None, "valor_combinado inválido"
        if valor < 0:
            return None, None, None, "valor_combinado não pode ser negativo"
    return nome, cnpj, valor, None


# --- cadastro ---------------------------------------------------------------

@bp.get("")
@require_auth
def listar():
    mes = _hoje().replace(day=1)
    rows = db.query(
        """SELECT f.*,
                  COALESCE((SELECT json_agg(json_build_object(
                              'tipo', l.tipo, 'valor', l.valor, 'pago_em', l.pago_em,
                              'vencimento', l.vencimento, 'numero_nf', l.numero_nf))
                            FROM fin_funcionario_lancamentos l
                            WHERE l.funcionario_id = f.id AND l.competencia = %s), '[]'::json) AS lancamentos_mes
           FROM fin_funcionarios f
           WHERE f.ativo = true
           ORDER BY f.nome""",
        (mes.isoformat(),)
    )
    saida = []
    for r in rows:
        r = dict(r)
        linhas = r.pop("lancamentos_mes") or []
        r["mes_atual"] = {"competencia": mes.isoformat(), **_resumo(linhas)}
        saida.append(r)
    return jsonify(saida)


@bp.post("")
@require_auth
@require_admin
def criar():
    nome, cnpj, valor, erro = _campos_cadastro(request.get_json() or {})
    if erro:
        return _erro(erro)
    row = db.execute(
        "INSERT INTO fin_funcionarios (nome, cnpj, valor_combinado) VALUES (%s, %s, %s) RETURNING *",
        (nome, cnpj, valor)
    )
    return jsonify(row), 201


@bp.put("/<fid>")
@require_auth
@require_admin
def editar(fid):
    nome, cnpj, valor, erro = _campos_cadastro(request.get_json() or {})
    if erro:
        return _erro(erro)
    row = db.execute(
        """UPDATE fin_funcionarios SET nome = %s, cnpj = %s, valor_combinado = %s
           WHERE id = %s AND ativo = true RETURNING *""",
        (nome, cnpj, valor, fid)
    )
    if row is None:
        return _erro("Funcionário não encontrado", 404)
    return jsonify(row)


@bp.delete("/<fid>")
@require_auth
@require_admin
def desativar(fid):
    row = db.execute("UPDATE fin_funcionarios SET ativo = false WHERE id = %s AND ativo = true RETURNING id", (fid,))
    if row is None:
        return _erro("Funcionário não encontrado", 404)
    return "", 204


# --- para a Caixa da Semana -------------------------------------------------

@bp.get("/pagamentos")
@require_auth
def pagamentos_do_periodo():
    """Pagamentos e DAS **pagos** entre `de` e `ate` — o que sai da sobra.
    DAS em aberto não sai de lugar nenhum ainda."""
    de, ate = request.args.get("de", ""), request.args.get("ate", "")
    if not (_RE_DATA.match(de) and _RE_DATA.match(ate)):
        return _erro("de e ate obrigatórios, no formato AAAA-MM-DD")
    rows = db.query(
        """SELECT l.id, l.tipo, l.valor, l.pago_em AS data_pagamento, l.competencia, l.created_at,
                  f.nome AS funcionario_nome
           FROM fin_funcionario_lancamentos l
           JOIN fin_funcionarios f ON f.id = l.funcionario_id
           WHERE l.tipo IN ('pagamento', 'das') AND l.pago_em IS NOT NULL
             AND l.pago_em BETWEEN %s AND %s
           ORDER BY l.pago_em, l.created_at""",
        (de, ate)
    )
    saida = []
    for r in rows:
        r = dict(r)
        r["data_pagamento"] = _iso(r["data_pagamento"])
        r["competencia"] = _iso(r["competencia"])
        r["valor"] = float(r["valor"] or 0)
        saida.append(r)
    return jsonify(saida)
