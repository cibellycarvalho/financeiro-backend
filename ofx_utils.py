from datetime import date, timedelta
from ofxparse import OfxParser

JANELA_DIAS = 3


def parse_ofx(file_stream):
    ofx = OfxParser.parse(file_stream)
    account = ofx.accounts[0]
    transacoes = []
    for txn in account.statement.transactions:
        valor = float(txn.amount)
        transacoes.append({
            "fitid": txn.id,
            "tipo": "CREDIT" if valor > 0 else "DEBIT",
            "valor": round(abs(valor), 2),
            "data": txn.date.date().isoformat(),
            "descricao": (txn.memo or txn.payee or "")[:200],
        })
    return transacoes


def melhor_candidato(data_transacao: date, candidatos: list[dict], usados: set[tuple[str, str]]) -> dict | None:
    melhor = None
    menor_diff = None
    for c in candidatos:
        chave = (c["tabela"], c["id"])
        if chave in usados:
            continue
        diff = abs((c["data"] - data_transacao).days)
        if diff > JANELA_DIAS:
            continue
        if menor_diff is None or diff < menor_diff:
            menor_diff = diff
            melhor = c
    return melhor
