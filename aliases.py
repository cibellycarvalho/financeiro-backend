"""Quem é o fornecedor deste documento?

Um alias liga o texto que aparece no documento ("Flavia" no pedido, "Multivale
Montagem E Estruturas Ltda" no Pix) a um fornecedor do painel. A lista aprende
sozinha: cada vez que ela salva, o texto lido vira alias do fornecedor escolhido.
Sem tela de administração — se um alias ficar errado, corrige-se no banco.
"""
import unicodedata

import db


def normalizar(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return " ".join(sem_acento.lower().split())


def sugerir_fornecedor(texto, origem):
    if not texto or not texto.strip():
        return None
    rows = db.query(
        "SELECT fornecedor_id FROM fin_fornecedor_aliases WHERE origem = %s AND alias_norm = %s",
        (origem, normalizar(texto)),
    )
    return rows[0]["fornecedor_id"] if rows else None


def aprender_alias(fornecedor_id, texto, origem):
    if not texto or not texto.strip():
        return
    db.execute(
        """INSERT INTO fin_fornecedor_aliases (fornecedor_id, alias, alias_norm, origem)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (origem, alias_norm) DO UPDATE SET fornecedor_id = EXCLUDED.fornecedor_id""",
        (fornecedor_id, texto.strip(), normalizar(texto), origem),
    )
