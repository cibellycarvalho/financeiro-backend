"""A trava por loja do Painel Financeiro.

Existe porque as rotas de fechamento vieram do CRM, onde a trava usava
g.user["role"] e g.user["conta_ml"] — chaves que NÃO existiam aqui. Portadas
sem isto, gravariam na loja errada sem dar erro nenhum.
"""
from flask import Flask, g

import contas_ml


def _app_com_usuario(user):
    app = Flask(__name__)

    @app.route("/x", methods=["GET", "POST"])
    def x():
        g.user = user
        try:
            return {"conta": contas_ml.conta_do_request()}
        except contas_ml.SemConta:
            return {"erro": "sem conta"}, 400

    return app.test_client()


ADMIN = {"user_id": "u1", "email": "a@b.c", "fin_role": "fin_admin",
         "conta_ml": "YUSO", "is_admin": True}
COMUM = {"user_id": "u2", "email": "d@e.f", "fin_role": "fin_viewer",
         "conta_ml": "M12", "is_admin": False}


def test_admin_pode_escolher_a_loja_pela_query():
    c = _app_com_usuario(ADMIN)
    assert c.get("/x?conta_ml=LOCITECH").get_json()["conta"] == "LOCITECH"


def test_nao_admin_fica_travado_na_propria_loja():
    """A fronteira de segurança: passar conta_ml na query NÃO pode permitir
    gravar na loja de outro."""
    c = _app_com_usuario(COMUM)
    assert c.get("/x?conta_ml=YUSO").get_json()["conta"] == "M12"


def test_nao_admin_travado_tambem_pelo_corpo_do_post():
    c = _app_com_usuario(COMUM)
    assert c.post("/x", json={"conta_ml": "YUSO"}).get_json()["conta"] == "M12"


def test_sem_conta_nos_metadados_recusa_em_vez_de_chutar():
    """Nunca cair num padrão: gravaria na loja de outro em silêncio."""
    c = _app_com_usuario({**COMUM, "conta_ml": None})
    assert c.get("/x").status_code == 400


def test_admin_sem_conta_na_query_usa_a_propria():
    c = _app_com_usuario(ADMIN)
    assert c.get("/x").get_json()["conta"] == "YUSO"


def test_admin_sem_loja_nenhuma_tambem_recusa():
    c = _app_com_usuario({**ADMIN, "conta_ml": None})
    assert c.get("/x").status_code == 400
