"""Kits: quantas unidades do produto vão num anúncio de cada SKU.

A detecção lê "Kit 5", "Kit 10" no título e sugere; nada vale antes de ela
confirmar (tabela sku_kits). Para o kit de um produto que também é vendido
avulso, sugere também o SKU avulso (sku_base), casando o título sem o "Kit N".
"""
import re

import db
import leitura_documento

_RE_KIT = re.compile(r"\bkit\s*(?:c/|com)?\s*(\d+)\b", re.IGNORECASE)
_PALAVRAS_FORA = {"kit", "de", "da", "do", "para", "p", "com", "c", "e", "yuso", "-"}


def unidades_no_titulo(titulo):
    m = _RE_KIT.search(titulo or "")
    n = int(m.group(1)) if m else None
    return n if n and n > 1 else None


def _palavras(titulo):
    sem_kit = _RE_KIT.sub(" ", titulo or "").lower()
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9à-ú,.]+", sem_kit)} - _PALAVRAS_FORA


def _catalogo():
    """{sku: [títulos]} dos anúncios que não estão encerrados."""
    rows = db.query(
        """SELECT upper(sku) AS sku, titulo FROM ml_anuncios
            WHERE sku IS NOT NULL AND sku <> '' AND coalesce(status_ml, '') <> 'closed'
            ORDER BY upper(sku), (status_ml = 'active') DESC"""
    )
    cat = {}
    for r in rows:
        cat.setdefault(r["sku"], []).append(r["titulo"])
    return cat


def _sugerir_base(sku, titulos, catalogo):
    alvo = _palavras(titulos[0])
    melhor, nota = None, 0.0
    for outro, ts in catalogo.items():
        if outro == sku or any(unidades_no_titulo(t) for t in ts):
            continue
        for t in ts:
            p = _palavras(t)
            j = len(alvo & p) / max(len(alvo | p), 1)
            if j > nota and leitura_documento.medidas_batem(titulos[0], [t]):
                melhor, nota = outro, j
    return melhor if nota >= 0.5 else None


def listar():
    """Kits confirmados + os que o título sugere e ainda não foram confirmados."""
    catalogo = _catalogo()
    confirmados = {r["sku"]: r for r in db.query("SELECT sku, unidades, sku_base, confirmado_em FROM sku_kits")}
    saida = []
    for sku, titulos in catalogo.items():
        n = next((unidades_no_titulo(t) for t in titulos if unidades_no_titulo(t)), None)
        c = confirmados.get(sku)
        if not c and not n:
            continue
        saida.append({
            "sku": sku,
            "titulo": titulos[0],
            "confirmado": bool(c),
            "unidades": float(c["unidades"]) if c else n,
            "sku_base": c["sku_base"] if c else _sugerir_base(sku, titulos, catalogo),
        })
    # O que falta confirmar vem primeiro.
    saida.sort(key=lambda k: (k["confirmado"], k["sku"]))
    return saida


def confirmar(sku, unidades, sku_base):
    return db.execute(
        """INSERT INTO sku_kits (sku, unidades, sku_base) VALUES (%s, %s, %s)
           ON CONFLICT (sku) DO UPDATE SET unidades = EXCLUDED.unidades,
                  sku_base = EXCLUDED.sku_base, confirmado_em = now()
           RETURNING sku, unidades, sku_base""",
        (sku, unidades, sku_base),
    )


def remover(sku):
    db.execute("DELETE FROM sku_kits WHERE sku = %s", (sku,))


def catalogo():
    return _catalogo()
