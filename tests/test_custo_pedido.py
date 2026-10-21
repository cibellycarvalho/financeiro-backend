from unittest.mock import MagicMock, patch

import custo_pedido
from tests.test_fornecedores import FORNECEDOR_FIXTURE, PEDIDO_FIXTURE, _mock_transaction_cursor

F, P = FORNECEDOR_FIXTURE["id"], PEDIDO_FIXTURE["id"]


def test_custo_soma_os_2_porcento_da_nf():
    assert custo_pedido.custo_com_nf(105) == 107.10
    assert custo_pedido.custo_com_nf(6.5) == 6.63


def _sqls(cur):
    return [c.args for c in cur.execute.call_args_list]


class Banco:
    """Cursor falso que responde pela consulta, não pela ordem das chamadas."""
    def __init__(self, anuncios=None, kits=None, mais_novo=False, historico_existe=False):
        self.anuncios = anuncios or {}       # sku -> [títulos]
        self.kits = kits or {}               # sku -> (unidades, sku_base)
        self.mais_novo, self.historico_existe = mais_novo, historico_existe
        self.execute = MagicMock(side_effect=self._exec)
        self._um, self._todos = None, []

    def _exec(self, sql, params=()):
        self._um, self._todos = None, []
        if "FROM fin_pedido_itens" in sql:
            self._um = (1,) if self.mais_novo else None
        elif "FROM sku_kits WHERE sku_base" in sql:
            self._todos = [{"sku": k, "unidades": u} for k, (u, b) in sorted(self.kits.items()) if b == params[0]]
        elif "FROM sku_kits WHERE sku =" in sql:
            k = self.kits.get(params[0]); self._um = {"unidades": k[0]} if k else None
        elif "SELECT ml_item_id" in sql:
            self._todos = [{"ml_item_id": f"{params[0]}-{n}", "conta_ml": "YUSO", "titulo": t}
                           for n, t in enumerate(self.anuncios.get(params[0], []))]
        elif "SELECT titulo FROM ml_anuncios" in sql:
            self._todos = [{"titulo": t} for t in self.anuncios.get(params[0], [])]
        elif "AS vigente" in sql:
            self._um = {"vigente": "2026-10-19"}
        elif "UPDATE custos_historico" in sql:
            self._um = {"id": 1} if self.historico_existe else None

    def fetchone(self):
        return self._um

    def fetchall(self):
        return self._todos

    def custos(self):
        return {p[1]: p[3] for s, p in _sqls(self) if "INSERT INTO custos_produtos" in s}


def _rodar(banco, sku, valor):
    ctx = MagicMock()
    ctx.__enter__.return_value = banco
    ctx.__exit__.return_value = False
    with patch("custo_pedido.db.transaction", MagicMock(return_value=ctx)):
        return custo_pedido.aplicar("i1", sku, valor, "2026-10-19")


def test_aplica_em_todos_os_anuncios_do_sku():
    b = Banco(anuncios={"FV0001": ["Cabo A", "Cabo A republicado"]})
    r = _rodar(b, "FV0001", 105)
    assert r["status"] == "atualizado" and r["custo"] == 107.10 and r["anuncios"] == 2
    assert b.custos() == {"FV0001-0": 107.10, "FV0001-1": 107.10}
    assert sum("INSERT INTO custos_historico" in s for s, _ in _sqls(b)) == 2


def test_mesma_data_altera_a_linha_do_historico_em_vez_de_duplicar():
    b = Banco(anuncios={"FV0001": ["Cabo A"]}, historico_existe=True)
    _rodar(b, "FV0001", 10)
    assert not any("INSERT INTO custos_historico" in s for s, _ in _sqls(b))


def test_pedido_mais_antigo_nao_volta_o_custo():
    b = Banco(anuncios={"FV0001": ["Cabo A"]}, mais_novo=True)
    assert _rodar(b, "FV0001", 10)["status"] == "pedido_mais_novo"
    assert b.custos() == {}


def test_sku_que_nao_existe_no_crm_e_contado():
    assert _rodar(Banco(), "XX9", 10)["status"] == "sku_desconhecido"


def test_fonte_avulsa_recalcula_os_kits_de_5_e_de_10():
    b = Banco(anuncios={"1017": ["Fonte 5v 2a"], "1010": ["Kit 5 Fontes 5v 2a"], "FV0060": ["Kit 10 Fonte 5v 2a"]},
              kits={"1010": (5, "1017"), "FV0060": (10, "1017")})
    r = _rodar(b, "1017", 5)
    assert b.custos() == {"1017-0": 5.10, "1010-0": 25.50, "FV0060-0": 51.00}
    assert [k["sku"] for k in r["kits"]] == ["1010", "FV0060"]


def test_kit_sem_avulso_multiplica_pelas_unidades():
    b = Banco(anuncios={"FV0006": ["Kit 10 Emenda Rj45"]}, kits={"FV0006": (10, None)})
    _rodar(b, "FV0006", 0.30)
    assert b.custos() == {"FV0006-0": 3.06}


def test_kit_nao_confirmado_nao_recebe_custo_de_uma_unidade():
    b = Banco(anuncios={"FV0006": ["Kit 10 Emenda Rj45"]})
    assert _rodar(b, "FV0006", 0.30)["status"] == "kit_nao_confirmado"
    assert b.custos() == {}


def test_criar_pedido_aprende_o_sku_e_atualiza_o_custo(client, admin_headers):
    mock_tr, _ = _mock_transaction_cursor([{**PEDIDO_FIXTURE}, {"id": "a", "produto": "FIBRA 20M", "sku": "FV0001", "valor_unitario": 105},
                                           {"id": "b", "produto": "Frete", "sku": None, "valor_unitario": 5}])
    with patch("routes.fornecedores.db.transaction", mock_tr), \
         patch("routes.fornecedores._aprender_alias_silencioso"), \
         patch("routes.fornecedores.custo_pedido.aprender_sku") as aprender, \
         patch("routes.fornecedores.custo_pedido.aplicar", return_value={"sku": "FV0001", "status": "atualizado"}) as aplicar:
        r = client.post(f"/api/fornecedores/{F}/pedidos", headers=admin_headers, json={
            "data_pedido": "2026-10-19",
            "itens": [{"produto": "FIBRA 20M", "quantidade": 1, "valor_unitario": 105, "sku": "FV0001"},
                      {"produto": "Frete", "quantidade": 1, "valor_unitario": 5}]})
    assert r.status_code == 201
    aprender.assert_called_once_with(F, "FIBRA 20M", "FV0001")
    aplicar.assert_called_once_with("a", "FV0001", 105, "2026-10-19")
    assert r.get_json()["custos"] == [{"sku": "FV0001", "status": "atualizado"}]


def test_falha_no_custo_nao_derruba_o_pedido(client, admin_headers):
    mock_tr, _ = _mock_transaction_cursor([{**PEDIDO_FIXTURE}, {"id": "a", "produto": "X", "sku": "FV0001", "valor_unitario": 1}])
    with patch("routes.fornecedores.db.transaction", mock_tr), \
         patch("routes.fornecedores._aprender_alias_silencioso"), \
         patch("routes.fornecedores.custo_pedido.aprender_sku", side_effect=RuntimeError("banco")):
        r = client.post(f"/api/fornecedores/{F}/pedidos", headers=admin_headers, json={
            "data_pedido": "2026-10-19",
            "itens": [{"produto": "X", "quantidade": 1, "valor_unitario": 1, "sku": "FV0001"}]})
    assert r.status_code == 201
    assert r.get_json()["custos"] == [{"sku": "FV0001", "status": "erro"}]


def test_lista_skus_do_crm(client, admin_headers):
    with patch("routes.fornecedores.db.query", return_value=[{"sku": "FV0001", "conta_ml": "YUSO", "titulo": "Cabo"}]):
        r = client.get("/api/fornecedores/skus", headers=admin_headers)
    assert r.status_code == 200 and r.get_json()[0]["sku"] == "FV0001"
