"""Resolução da loja (conta_ml) e a trava que impede gravar na loja de outro.

Arquivo separado de propósito: é a única fronteira de segurança da migração do
Fechamento. As rotas vieram do CRM, onde a trava usava `g.user["role"]` e
`g.user["conta_ml"]` — chaves que NÃO existem no contexto do Painel Financeiro,
que descreve o usuário como `{user_id, email, fin_role}`. Portadas sem isto,
elas gravariam na loja errada sem dar erro nenhum: nenhuma tela quebraria, e o
dado de uma loja apareceria dentro de outra.

`fin_role` responde "o que essa pessoa pode fazer no financeiro". `conta_ml`
responde "de qual loja ela é". São perguntas diferentes e ficam separadas.
"""
from flask import request, g


class SemConta(Exception):
    """Usuário sem loja definida nos metadados.

    Recusar é a resposta certa. Cair num padrão (a primeira loja, a loja
    principal) gravaria dados de uma loja dentro de outra, em silêncio — e
    ninguém descobriria até o fechamento não bater.
    """


def conta_do_request():
    """A loja desta requisição.

    Admin escolhe pela query string ou pelo corpo; qualquer outro fica travado
    na própria loja, ignorando o que vier na requisição. É essa segunda parte
    que impede alguém de gravar na loja de outro só editando a URL.
    """
    usuario = getattr(g, "user", {}) or {}
    propria = usuario.get("conta_ml")

    if not usuario.get("is_admin"):
        if not propria:
            raise SemConta()
        return propria

    corpo = request.get_json(silent=True) or {} if request.method in ("POST", "PUT") else {}
    escolhida = request.args.get("conta_ml") or corpo.get("conta_ml") or propria
    if not escolhida:
        raise SemConta()
    return escolhida
