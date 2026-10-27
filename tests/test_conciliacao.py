from datetime import date

import conciliacao

OFX_SGML = b"""OFXHEADER:100
DATA:OFXSGML
<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261027100000[-3:BRT]<TRNAMT>6840.00<FITID>A1<MEMO>TED RECEBIDA MERCADO PAGO
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261027<TRNAMT>-1150,00<FITID>A2<MEMO>PIX ENVIADO BIANCA
</BANKTRANLIST><LEDGERBAL><BALAMT>9870.50<DTASOF>20261027</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"""


def test_le_ofx_sgml_com_virgula_e_saldo():
    r = conciliacao.ler_ofx(OFX_SGML)
    assert [m["valor"] for m in r["movimentos"]] == [6840.0, -1150.0]
    assert r["movimentos"][1]["data"] == date(2026, 10, 27)
    assert r["movimentos"][0]["fitid"] == "A1"
    assert r["saldo"] == 9870.5


def test_le_ofx_xml():
    xml = b"<OFX><STMTTRN><DTPOSTED>20261020</DTPOSTED><TRNAMT>-59.90</TRNAMT><FITID>X</FITID><NAME>TARIFA</NAME></STMTTRN></OFX>"
    m = conciliacao.ler_ofx(xml)["movimentos"]
    assert m == [{"fitid": "X", "data": date(2026, 10, 20), "valor": -59.9, "descricao": "TARIFA"}]


def test_arquivo_que_nao_e_ofx():
    import pytest
    with pytest.raises(ValueError):
        conciliacao.ler_ofx(b"nome;valor\n")


D = date(2026, 10, 27)


def test_repasse_mp_casa_sozinho():
    s = conciliacao.sugerir({"valor": 100.0, "data": D, "descricao": "TED MERCADO PAGO"}, [])
    assert s["status"] == "casado" and s["casado_tipo"] == "repasse_mp"


def test_mesmo_valor_mesma_data_ja_pago_casa_sozinho():
    c = [{"tipo": "funcionario", "id": "l1", "valor": 1150, "data": D, "pago": True, "texto": "Pagamento de Bianca"}]
    s = conciliacao.sugerir({"valor": -1150.0, "data": D, "descricao": "PIX"}, c)
    assert s == {"status": "casado", "casado_tipo": "funcionario", "casado_id": "l1", "casado_texto": "Pagamento de Bianca"}


def test_conta_em_aberto_vira_sugestao():
    c = [{"tipo": "conta", "id": "c1", "valor": 86.05, "data": date(2026, 10, 29), "pago": False, "texto": "Conta: DAS"}]
    assert conciliacao.sugerir({"valor": -86.05, "data": D}, c)["status"] == "sugerido"


def test_dois_iguais_no_mesmo_dia_so_sugere():
    c = [{"tipo": "conta", "id": i, "valor": 50, "data": D, "pago": True, "texto": i} for i in ("a", "b")]
    assert conciliacao.sugerir({"valor": -50.0, "data": D}, c)["status"] == "sugerido"


def test_sem_candidato_e_novo():
    c = [{"tipo": "conta", "id": "c", "valor": 50, "data": date(2026, 10, 1), "pago": True, "texto": "x"}]
    assert conciliacao.sugerir({"valor": -50.0, "data": D}, c)["status"] == "novo"


def test_extrato_pdf_iguais_no_mesmo_dia_tem_ids_diferentes():
    from unittest.mock import patch
    import leitura_documento
    bruto = {"movimentos": [
        {"data": "2026-10-27", "descricao": "PIX ENVIADO", "valor": -50},
        {"data": "2026-10-27", "descricao": "PIX ENVIADO", "valor": -50},
        {"data": "lixo", "descricao": "x", "valor": 1},
    ], "saldo_final": 9870.5}
    with patch("leitura_documento._chamar", return_value=bruto):
        r = leitura_documento.ler_extrato(b"%PDF", "application/pdf")
    ids = [m["fitid"] for m in r["movimentos"]]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert r["saldo"] == 9870.5 and r["movimentos"][0]["valor"] == -50.0
