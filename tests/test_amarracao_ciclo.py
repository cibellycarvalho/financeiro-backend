"""O ciclo inteiro do Pix: amarrar, desamarrar, reamarrar e desmarcar.

Fix round 3 (CRITICAL 1 e IMPORTANT 4). Os outros testes de amarração usam
MagicMock e olham o SQL que saiu; estes precisam do EFEITO no banco, porque o
bug é justamente um rastro que sobra numa tabela e explode numa rota
diferente depois. Este arquivo tem um banco de mentira mínimo — só as três
tabelas e as instruções que estas rotas usam — para reproduzir o cenário da
Cibelly de ponta a ponta:

Pix de 49.310 lançado no pedido A (caixinha "Pago"), desamarrado, reamarrado a
A e B; desmarcar a caixinha de A não pode apagar o Pix nem a amarração de B.
Antes do fix, o DELETE ... WHERE pedido_id da rota de desmarcar achava o Pix
pela coluna legada e apagava tudo, levando a amarração do B por CASCADE e
deixando o comprovante órfão.
"""
import re
from contextlib import contextmanager
from unittest.mock import patch

import pytest

F_ID = "f-1"
PG_ID = "pg-49310"
A_ID = "ped-a"
B_ID = "ped-b"


class BancoFake:
    """Banco de mentira: três tabelas e as instruções destas rotas."""

    def __init__(self):
        self.pagamentos = {}
        self.pedidos = {}
        self.links = []          # {"pagamento_id", "pedido_id", "valor"}

    # --- tabelas -----------------------------------------------------
    def add_pagamento(self, id, valor, pedido_id=None):
        self.pagamentos[id] = {"id": id, "fornecedor_id": F_ID, "valor": valor,
                               "pedido_id": pedido_id}

    def add_pedido(self, id, valor_total, pago_em=None):
        self.pedidos[id] = {"id": id, "fornecedor_id": F_ID,
                            "valor_total": valor_total, "pago_em": pago_em}

    def links_do_pedido(self, pedido_id):
        return [l for l in self.links if l["pedido_id"] == pedido_id]

    def _apagar_pagamento(self, pagamento_id):
        self.pagamentos.pop(pagamento_id, None)
        # ON DELETE CASCADE da FK de fin_pagamento_pedido
        self.links = [l for l in self.links if l["pagamento_id"] != pagamento_id]

    # --- "driver" ----------------------------------------------------
    def executar(self, sql, params=()):
        s = re.sub(r"\s+", " ", sql).strip()
        p = list(params)

        if "SELECT id, pedido_id FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id" in s:
            pg = self.pagamentos.get(p[0])
            return [{"id": pg["id"], "pedido_id": pg["pedido_id"]}] if pg and pg["fornecedor_id"] == p[1] else []

        if "SELECT id FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id" in s:
            pg = self.pagamentos.get(p[0])
            return [{"id": pg["id"]}] if pg and pg["fornecedor_id"] == p[1] else []

        if "SELECT valor FROM fin_pagamentos_fornecedor WHERE id = %s" in s:
            pg = self.pagamentos.get(p[0])
            return [{"valor": pg["valor"]}] if pg else []

        if "SELECT id, valor_total, pago_em FROM fin_pedidos_fornecedor WHERE id = %s AND fornecedor_id" in s:
            ped = self.pedidos.get(p[0])
            return [dict(ped)] if ped and ped["fornecedor_id"] == p[1] else []

        if "SELECT pedido_id FROM fin_pagamento_pedido WHERE pagamento_id" in s:
            return [{"pedido_id": l["pedido_id"]} for l in self.links if l["pagamento_id"] == p[0]]

        if s.startswith("SELECT p.valor_total,"):          # amarracao.validar
            pagamento_id, pedido_id, fornecedor_id = p
            ped = self.pedidos.get(pedido_id)
            if not ped or ped["fornecedor_id"] != fornecedor_id:
                return []
            amarrado = sum(l["valor"] for l in self.links
                           if l["pedido_id"] == pedido_id and l["pagamento_id"] != pagamento_id)
            return [{"valor_total": ped["valor_total"], "amarrado": amarrado}]

        if "DELETE FROM fin_pagamento_pedido WHERE pagamento_id" in s:
            self.links = [l for l in self.links if l["pagamento_id"] != p[0]]
            return []

        if "INSERT INTO fin_pagamento_pedido" in s:
            self.links.append({"pagamento_id": p[0], "pedido_id": p[1], "valor": float(p[2])})
            return []

        if "UPDATE fin_pagamentos_fornecedor SET pedido_id = NULL" in s:
            if p[0] in self.pagamentos:
                self.pagamentos[p[0]]["pedido_id"] = None
            return []

        if "UPDATE fin_pedidos_fornecedor SET pago_em = NULL" in s and "NOT EXISTS" in s:
            pedido_id = p[0]
            ignorar = p[3] if len(p) > 3 else None
            tem_link = any(l["pedido_id"] == pedido_id for l in self.links)
            tem_legado = any(pg["pedido_id"] == pedido_id and pg["id"] != ignorar
                             for pg in self.pagamentos.values())
            if not tem_link and not tem_legado and pedido_id in self.pedidos:
                self.pedidos[pedido_id]["pago_em"] = None
            return []

        if "UPDATE fin_pedidos_fornecedor SET pago_em = NULL WHERE id = %s" in s:
            if p[0] in self.pedidos:
                self.pedidos[p[0]]["pago_em"] = None
            return []

        if "DELETE FROM fin_pagamentos_fornecedor WHERE pedido_id = %s AND fornecedor_id" in s:
            alvos = [pg["id"] for pg in self.pagamentos.values()
                     if pg["pedido_id"] == p[0] and pg["fornecedor_id"] == p[1]]
            for alvo in alvos:
                self._apagar_pagamento(alvo)
            return []

        if "DELETE FROM fin_pagamentos_fornecedor WHERE id = %s AND fornecedor_id" in s:
            pg = self.pagamentos.get(p[0])
            if pg and pg["fornecedor_id"] == p[1]:
                self._apagar_pagamento(p[0])
            return []

        raise AssertionError(f"SQL fora do banco de mentira: {s[:120]}")


class CursorFake:
    def __init__(self, banco):
        self.banco = banco
        self._linhas = []

    def execute(self, sql, params=()):
        self._linhas = self.banco.executar(sql, params)

    def fetchone(self):
        return self._linhas[0] if self._linhas else None

    def fetchall(self):
        return self._linhas


@pytest.fixture
def banco():
    b = BancoFake()

    def query(sql, params=()):
        return b.executar(sql, params)

    def execute(sql, params=()):
        linhas = b.executar(sql, params)
        return linhas[0] if linhas else None

    @contextmanager
    def transaction():
        yield CursorFake(b)

    with patch("db.query", query), patch("db.execute", execute), \
         patch("db.transaction", transaction):
        yield b


def _cenario(banco):
    """Pix de 49.310 lançado na compra A pela caixinha "Pago"."""
    banco.add_pedido(A_ID, 30000.0, pago_em="2026-09-14")
    banco.add_pedido(B_ID, 19310.0)
    banco.add_pagamento(PG_ID, 49310.0, pedido_id=A_ID)   # coluna legada preenchida
    banco.links.append({"pagamento_id": PG_ID, "pedido_id": A_ID, "valor": 30000.0})


def test_desamarrar_limpa_a_coluna_legada_e_o_pago_em(banco, client, admin_headers):
    _cenario(banco)
    resp = client.delete(f"/api/fornecedores/{F_ID}/pagamentos/{PG_ID}/pedidos", headers=admin_headers)
    assert resp.status_code == 204
    assert banco.links == []
    assert banco.pagamentos[PG_ID]["pedido_id"] is None      # coluna legada limpa
    assert banco.pedidos[A_ID]["pago_em"] is None            # compra voltou a estar em aberto


def test_ciclo_completo_desmarcar_a_caixinha_de_a_nao_apaga_o_pix_nem_a_amarracao_de_b(
        banco, client, admin_headers):
    """O cenário exato da revisão (CRITICAL 1)."""
    _cenario(banco)

    # 1. desamarrar
    assert client.delete(f"/api/fornecedores/{F_ID}/pagamentos/{PG_ID}/pedidos",
                         headers=admin_headers).status_code == 204

    # 2. reamarrar o mesmo Pix às duas compras, pela tela "Pix sem compra"
    resp = client.post(
        f"/api/fornecedores/{F_ID}/pagamentos/{PG_ID}/pedidos",
        json={"itens": [{"pedido_id": A_ID, "valor": 30000.0},
                        {"pedido_id": B_ID, "valor": 19310.0}]},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert len(banco.links) == 2

    # 3. desmarcar a caixinha "Pago" da compra A
    resp = client.delete(f"/api/fornecedores/{F_ID}/pedidos/{A_ID}/pago", headers=admin_headers)
    assert resp.status_code == 204

    # O Pix continua existindo, com o comprovante dele...
    assert PG_ID in banco.pagamentos
    # ...e a amarração da compra B não foi levada por CASCADE.
    assert banco.links_do_pedido(B_ID) == [{"pagamento_id": PG_ID, "pedido_id": B_ID, "valor": 19310.0}]


def test_excluir_pix_amarrado_a_duas_compras_tira_a_baixa_das_duas(banco, client, admin_headers):
    """IMPORTANT 4: a limpeza saía da coluna legada, então só uma das duas
    compras voltava a estar em aberto — a outra ficava paga sem pagamento."""
    banco.add_pedido(A_ID, 30000.0, pago_em="2026-09-14")
    banco.add_pedido(B_ID, 19310.0, pago_em="2026-09-14")
    banco.add_pagamento(PG_ID, 49310.0)
    banco.links.append({"pagamento_id": PG_ID, "pedido_id": A_ID, "valor": 30000.0})
    banco.links.append({"pagamento_id": PG_ID, "pedido_id": B_ID, "valor": 19310.0})

    resp = client.delete(f"/api/fornecedores/{F_ID}/pagamentos/{PG_ID}", headers=admin_headers)
    assert resp.status_code == 204
    assert banco.pedidos[A_ID]["pago_em"] is None
    assert banco.pedidos[B_ID]["pago_em"] is None


def test_excluir_pix_legado_nao_tira_a_baixa_de_compra_quitada_por_outro_pix(
        banco, client, admin_headers):
    """IMPORTANT 4: a compra A está quitada por OUTRO Pix (link vivo). Apagar
    o Pix legado que apontava para ela pela coluna antiga não pode marcá-la
    como em aberto de novo."""
    banco.add_pedido(A_ID, 30000.0, pago_em="2026-09-14")
    banco.add_pagamento("pg-legado", 1000.0, pedido_id=A_ID)
    banco.add_pagamento("pg-outro", 30000.0)
    banco.links.append({"pagamento_id": "pg-outro", "pedido_id": A_ID, "valor": 30000.0})

    resp = client.delete(f"/api/fornecedores/{F_ID}/pagamentos/pg-legado", headers=admin_headers)
    assert resp.status_code == 204
    assert banco.pedidos[A_ID]["pago_em"] == "2026-09-14"
    assert "pg-outro" in banco.pagamentos
