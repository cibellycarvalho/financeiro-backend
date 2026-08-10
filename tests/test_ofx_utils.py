import os
from ofx_utils import parse_ofx

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "extrato_exemplo.ofx")


def test_parse_ofx_extrai_debito_e_credito():
    with open(FIXTURE_PATH, "rb") as f:
        transacoes = parse_ofx(f)

    assert len(transacoes) == 2

    debito = next(t for t in transacoes if t["tipo"] == "DEBIT")
    assert debito["valor"] == 450.00
    assert debito["data"] == "2026-08-05"
    assert debito["fitid"] == "2026080500001"
    assert "Flavia" in debito["descricao"]

    credito = next(t for t in transacoes if t["tipo"] == "CREDIT")
    assert credito["valor"] == 1200.50
    assert credito["data"] == "2026-08-06"
    assert credito["fitid"] == "2026080600002"
