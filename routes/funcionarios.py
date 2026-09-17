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


def _corpo():
    """JSON do request como dict, ou None se não veio um objeto JSON."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


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
    data = _corpo()
    if data is None:
        return _erro("corpo inválido: envie um objeto JSON")
    nome, cnpj, valor, erro = _campos_cadastro(data)
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
    data = _corpo()
    if data is None:
        return _erro("corpo inválido: envie um objeto JSON")
    nome, cnpj, valor, erro = _campos_cadastro(data)
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


# --- lançamentos --------------------------------------------------------------

def _mes_anterior(d, n):
    ano, mes = d.year, d.month - n
    while mes <= 0:
        mes += 12
        ano -= 1
    return date(ano, mes, 1)


def _data_ou_erro(texto):
    """'AAAA-MM-DD' → o texto; vazio → None; inválido → ValueError."""
    if texto in (None, ""):
        return None
    if not isinstance(texto, str) or not _RE_DATA.match(texto):
        raise ValueError(texto)
    date.fromisoformat(texto)
    return texto


def _campos_lancamento(tipo, data, atual=None):
    """Mescla o corpo com a linha atual (PUT) e aplica as regras do tipo.
    Devolve (campos, erro). `campos['competencia']` é date."""
    base = {k: (atual or {}).get(k) for k in
            ("competencia", "valor", "vencimento", "pago_em", "numero_nf", "id_transacao", "observacao")}
    for k in base:
        if k in data:
            base[k] = data[k]

    comp = _competencia(base["competencia"])
    if comp is None:
        return None, "competencia inválida (use AAAA-MM)"
    if base["valor"] in (None, ""):
        valor = None
    else:
        try:
            valor = float(base["valor"])
        except (TypeError, ValueError):
            return None, "valor inválido"
    try:
        vencimento = _data_ou_erro(base["vencimento"])
        pago_em = _data_ou_erro(base["pago_em"])
    except ValueError:
        return None, "data inválida (use AAAA-MM-DD)"
    texto = lambda v: (v.strip() or None) if isinstance(v, str) else None

    if tipo in ("pagamento", "das") and (valor is None or valor <= 0):
        return None, "valor deve ser maior que zero"
    if tipo == "pagamento" and not pago_em:
        return None, "pago_em obrigatório"
    if tipo == "nf" and valor is not None and valor < 0:
        return None, "valor inválido"

    return {
        "competencia": comp, "valor": valor, "vencimento": vencimento, "pago_em": pago_em,
        "numero_nf": texto(base["numero_nf"]), "id_transacao": texto(base["id_transacao"]),
        "observacao": texto(base["observacao"]),
    }, None


def _tokens(data):
    """Devolve ({campo: token}, erro) só com os tokens presentes e válidos."""
    tokens = {}
    for campo, _, _ in ANEXOS:
        t = (data.get(campo) or "").strip() if isinstance(data.get(campo), str) else None
        if t:
            if not anexos.arquivo_token_valido(t):
                return None, f"{campo} inválido"
            tokens[campo] = t
    return tokens, None


def _pix_ja_lancado(id_transacao, ignorar_id=None):
    """O mesmo E2E em fornecedores OU funcionários. Índice não atravessa tabela."""
    sql = """SELECT id, data_pagamento, valor, 'fornecedor' AS onde
               FROM fin_pagamentos_fornecedor WHERE id_transacao = %s
             UNION ALL
             SELECT id, pago_em AS data_pagamento, valor, 'funcionário' AS onde
               FROM fin_funcionario_lancamentos WHERE id_transacao = %s"""
    params = [id_transacao, id_transacao]
    if ignorar_id:
        sql += " AND id <> %s"
        params.append(ignorar_id)
    rows = db.query(sql, tuple(params))
    if not rows:
        return None
    r = rows[0]
    return {"id": r["id"], "data_pagamento": _iso(r["data_pagamento"]), "valor": float(r["valor"] or 0), "onde": r["onde"]}


def _msg_pix_repetido(existente):
    quando = existente["data_pagamento"]
    try:
        quando = date.fromisoformat(quando).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        pass
    return f"Esse comprovante já foi lançado em {quando} (R$ {existente['valor']:.2f}) — em {existente['onde']}"


def _um_por_mes(fid, competencia_iso, tipo, ignorar_id=None):
    sql = """SELECT * FROM fin_funcionario_lancamentos
             WHERE funcionario_id = %s AND competencia = %s AND tipo = %s"""
    params = [fid, competencia_iso, tipo]
    if ignorar_id:
        sql += " AND id <> %s"
        params.append(ignorar_id)
    rows = db.query(sql + " LIMIT 1", tuple(params))
    return _linha(rows[0]) if rows else None


def _mover_anexos(cur, fid, tipo, row, tokens):
    """Dentro da transação: move cada token para o destino e grava a coluna."""
    pasta = row["competencia"].strftime("%Y-%m") if isinstance(row["competencia"], date) else str(row["competencia"])[:7]
    for campo, coluna, sufixo in ANEXOS:
        token = tokens.get(campo)
        if not token:
            continue
        destino = anexos.destino_anexo(f"funcionarios/{fid}", pasta, f"{tipo}{sufixo}-{row['id']}", token)
        storage.mover(token, destino)
        cur.execute(f"UPDATE fin_funcionario_lancamentos SET {coluna} = %s WHERE id = %s", (destino, row["id"]))
        row[coluna] = destino


@bp.get("/<fid>/lancamentos")
@require_auth
def listar_lancamentos(fid):
    comp = _competencia(request.args.get("competencia"))
    if comp is None:
        return _erro("competencia obrigatória, no formato AAAA-MM")
    rows = db.query(
        """SELECT * FROM fin_funcionario_lancamentos
           WHERE funcionario_id = %s AND competencia = %s
           ORDER BY CASE tipo WHEN 'pagamento' THEN 1 WHEN 'das' THEN 2 ELSE 3 END, pago_em, created_at""",
        (fid, comp.isoformat())
    )
    return jsonify([_linha(r) for r in rows])


@bp.get("/<fid>/meses")
@require_auth
def meses(fid):
    ate = _competencia(request.args.get("ate")) or _hoje().replace(day=1)
    try:
        n = max(1, min(36, int(request.args.get("n", 12))))
    except ValueError:
        n = 12
    lista = [_mes_anterior(ate, i) for i in range(n)]
    rows = db.query(
        """SELECT * FROM fin_funcionario_lancamentos
           WHERE funcionario_id = %s AND competencia BETWEEN %s AND %s""",
        (fid, lista[-1].isoformat(), ate.isoformat())
    )
    por_mes = {}
    for r in rows:
        por_mes.setdefault(_iso(r["competencia"]), []).append(dict(r))
    return jsonify([{"competencia": m.isoformat(), **_resumo(por_mes.get(m.isoformat(), []))} for m in lista])


@bp.post("/<fid>/lancamentos")
@require_auth
@require_admin
def criar_lancamento(fid):
    data = _corpo()
    if data is None:
        return _erro("corpo inválido: envie um objeto JSON")
    tipo = data.get("tipo")
    if tipo not in TIPOS:
        return _erro("tipo deve ser pagamento, das ou nf")
    if _funcionario(fid) is None:
        return _erro("Funcionário não encontrado", 404)
    campos, erro = _campos_lancamento(tipo, data)
    if erro:
        return _erro(erro)
    tokens, erro = _tokens(data)
    if erro:
        return _erro(erro)
    if tipo == "nf" and not campos["numero_nf"] and "arquivo_token" not in tokens:
        return _erro("Informe o número da nota ou suba o arquivo")

    comp_iso = campos["competencia"].isoformat()
    if campos["id_transacao"]:
        existente = _pix_ja_lancado(campos["id_transacao"])
        if existente:
            return _erro(_msg_pix_repetido(existente), 409)
    if tipo in ("das", "nf"):
        existente = _um_por_mes(fid, comp_iso, tipo)
        if existente:
            return jsonify({"error": f"Já existe {ROTULO_TIPO[tipo]} em {campos['competencia'].strftime('%m/%Y')}",
                            "existente_id": existente["id"]}), 409

    try:
        with db.transaction() as cur:
            cur.execute(
                """INSERT INTO fin_funcionario_lancamentos
                   (funcionario_id, tipo, competencia, valor, vencimento, pago_em, numero_nf, id_transacao, observacao, criado_por)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (fid, tipo, comp_iso, campos["valor"], campos["vencimento"], campos["pago_em"],
                 campos["numero_nf"], campos["id_transacao"], campos["observacao"], g.user["user_id"])
            )
            row = dict(cur.fetchone())
            _mover_anexos(cur, fid, tipo, row, tokens)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao mover anexo de funcionário: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return _erro("Não consegui guardar o anexo; nada foi salvo. Tente de novo.", 500)
    return jsonify(_linha(row)), 201


@bp.put("/<fid>/lancamentos/<lid>")
@require_auth
@require_admin
def editar_lancamento(fid, lid):
    data = _corpo()
    if data is None:
        return _erro("corpo inválido: envie um objeto JSON")
    rows = db.query("SELECT * FROM fin_funcionario_lancamentos WHERE id = %s AND funcionario_id = %s", (lid, fid))
    if not rows:
        return _erro("Lançamento não encontrado", 404)
    atual = _linha(rows[0])
    tipo = atual["tipo"]
    campos, erro = _campos_lancamento(tipo, data, atual)
    if erro:
        return _erro(erro)
    tokens, erro = _tokens(data)
    if erro:
        return _erro(erro)
    if tipo == "nf" and not campos["numero_nf"] and "arquivo_token" not in tokens and not atual.get("arquivo_path"):
        return _erro("Informe o número da nota ou suba o arquivo")

    comp_iso = campos["competencia"].isoformat()
    if campos["id_transacao"] and campos["id_transacao"] != atual.get("id_transacao"):
        existente = _pix_ja_lancado(campos["id_transacao"], ignorar_id=lid)
        if existente:
            return _erro(_msg_pix_repetido(existente), 409)
    if tipo in ("das", "nf") and comp_iso != atual["competencia"]:
        existente = _um_por_mes(fid, comp_iso, tipo, ignorar_id=lid)
        if existente:
            return jsonify({"error": f"Já existe {ROTULO_TIPO[tipo]} em {campos['competencia'].strftime('%m/%Y')}",
                            "existente_id": existente["id"]}), 409

    try:
        with db.transaction() as cur:
            cur.execute(
                """UPDATE fin_funcionario_lancamentos
                   SET competencia = %s, valor = %s, vencimento = %s, pago_em = %s,
                       numero_nf = %s, id_transacao = %s, observacao = %s
                   WHERE id = %s AND funcionario_id = %s
                   RETURNING *""",
                (comp_iso, campos["valor"], campos["vencimento"], campos["pago_em"],
                 campos["numero_nf"], campos["id_transacao"], campos["observacao"], lid, fid)
            )
            row = dict(cur.fetchone())
            _mover_anexos(cur, fid, tipo, row, tokens)
    except storage.StorageErro as e:
        print(f"[storage] falhou ao mover anexo de funcionário: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return _erro("Não consegui guardar o anexo; nada foi alterado. Tente de novo.", 500)
    return jsonify(_linha(row))


@bp.delete("/<fid>/lancamentos/<lid>")
@require_auth
@require_admin
def apagar_lancamento(fid, lid):
    # Os arquivos ficam no bucket (limpeza é fora do escopo do desenho).
    row = db.execute("DELETE FROM fin_funcionario_lancamentos WHERE id = %s AND funcionario_id = %s RETURNING id", (lid, fid))
    if row is None:
        return _erro("Lançamento não encontrado", 404)
    return "", 204


@bp.get("/<fid>/lancamentos/<lid>/anexo")
@require_auth
def anexo_lancamento(fid, lid):
    coluna = COLUNAS_ANEXO.get(request.args.get("qual", "arquivo"))
    if coluna is None:
        return _erro("qual deve ser arquivo, boleto ou comprovante")
    return anexos.url_anexo("fin_funcionario_lancamentos", "funcionario_id", fid, lid, coluna)
