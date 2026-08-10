from datetime import timedelta
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
