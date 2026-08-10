import os
from datetime import date
from ofx_utils import parse_ofx, melhor_candidato

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


def test_melhor_candidato_escolhe_mais_proximo_na_janela():
    candidatos = [
        {"id": "a1", "data": date(2026, 8, 2), "tabela": "fin_contas_pagar"},
        {"id": "a2", "data": date(2026, 8, 5), "tabela": "fin_contas_pagar"},
    ]
    resultado = melhor_candidato(date(2026, 8, 5), candidatos, usados=set())
    assert resultado["id"] == "a2"


def test_melhor_candidato_ignora_fora_da_janela():
    candidatos = [{"id": "a1", "data": date(2026, 7, 1), "tabela": "fin_contas_pagar"}]
    resultado = melhor_candidato(date(2026, 8, 5), candidatos, usados=set())
    assert resultado is None


def test_melhor_candidato_ignora_ids_ja_usados():
    candidatos = [{"id": "a1", "data": date(2026, 8, 5), "tabela": "fin_contas_pagar"}]
    resultado = melhor_candidato(date(2026, 8, 5), candidatos, usados={("fin_contas_pagar", "a1")})
    assert resultado is None


def test_melhor_candidato_retorna_none_sem_candidatos():
    assert melhor_candidato(date(2026, 8, 5), [], usados=set()) is None


def test_melhor_candidato_janela_inclusiva_exatamente_3_dias():
    # Boundary case: exactly JANELA_DIAS (3) away should be included
    candidatos = [{"id": "a1", "data": date(2026, 8, 2), "tabela": "fin_contas_pagar"}]
    resultado = melhor_candidato(date(2026, 8, 5), candidatos, usados=set())
    # diff = abs((2026-08-02) - (2026-08-05)).days = 3 days, should be included (not > 3)
    assert resultado is not None
    assert resultado["id"] == "a1"
