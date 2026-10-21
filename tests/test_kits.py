import kits
import leitura_documento


def test_unidades_vem_do_kit_no_titulo():
    assert kits.unidades_no_titulo("Kit 10 Fonte 5v 2a Bivolt") == 10
    assert kits.unidades_no_titulo("Kit Conversor De Audio Digital") is None
    assert kits.unidades_no_titulo("Fonte 5v 2a") is None


def test_kit_de_fonte_sugere_a_fonte_avulsa():
    cat = {"1017": ["Fonte De Alimentação 5v 2a Bivolt 110/220v Estabilizada P4"],
           "1010": ["Kit 5 Fontes De Alimentação 5v 2a Bivolt 110/220v Plug P4"],
           "FV0044": ["Fonte Carregador Para Notebook Acer 19v 3.42a 65w"]}
    assert kits._sugerir_base("1010", cat["1010"], cat) == "1017"


def test_kit_sem_avulso_nao_inventa_base():
    cat = {"FV0006": ["Kit 10 Emenda Cabo Rede Rj45 Fêmea"], "FV0090": ["Cabo Hdmi 15m 8k"]}
    assert kits._sugerir_base("FV0006", cat["FV0006"], cat) is None


def test_casar_skus_descarta_metragem_diferente(mocker):
    mocker.patch("leitura_documento._chamar", return_value={"itens": [
        {"indice": 0, "sku": "FV10M"}, {"indice": 1, "sku": "1017"}, {"indice": 2, "sku": "NAOEXISTE"}]})
    cat = {"FV10M": ["Cabo Hdmi Fibra 10m 8k"], "1017": ["Fonte 5v 2a Bivolt"]}
    achados = leitura_documento.casar_skus(["FIBRA HDMI 20M 8K", "FONTE 5V 2A", "OUTRA"], cat)
    assert achados == {1: "1017"}


def test_confirmar_kit_recusa_sku_avulso_que_nao_existe(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.db.query", return_value=[])
    confirmar = mocker.patch("routes.fornecedores.kits.confirmar")
    r = client.put("/api/fornecedores/kits/00002", headers=admin_headers, json={"unidades": 2, "sku_base": "0.01"})
    assert r.status_code == 400 and "0.01" in r.get_json()["error"]
    confirmar.assert_not_called()


def test_confirmar_kit_com_sku_avulso_que_existe(client, admin_headers, mocker):
    mocker.patch("routes.fornecedores.db.query", return_value=[(1,)])
    mocker.patch("routes.fornecedores.kits.confirmar", return_value={"sku": "FV0060"})
    r = client.put("/api/fornecedores/kits/FV0060", headers=admin_headers, json={"unidades": 10, "sku_base": "1017"})
    assert r.status_code == 200
