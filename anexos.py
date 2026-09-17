"""Helpers de anexo compartilhados pelas rotas de fornecedores e funcionários.

Viviam dentro de routes/fornecedores.py; saíram de lá em 17/09/2026 quando a
aba Funcionários passou a subir documento pelo mesmo caminho (pendentes/ no
bucket → leitura → salvar move). Nada aqui grava no banco: quem grava é a rota.
"""
import re
import sys

from flask import request, jsonify

import db
import storage

_TAMANHO_MAX = 10 * 1024 * 1024
MSG_LEITURA_INDISPONIVEL = "Leitura automática indisponível agora. Lance à mão."
MSG_ANEXO_NAO_GUARDADO = "Não consegui guardar o arquivo; dá para lançar assim mesmo, só sem o anexo."

# Tokens legítimos sempre vêm de storage.enviar_pendente (uuid4().hex + ext
# aceita). Qualquer outra forma é entrada forjada — sem isso, um token como
# "outro-fornecedor/pedidos/x.pdf" moveria o anexo de outro registro.
_RE_ARQUIVO_TOKEN = re.compile(r"^pendentes/[0-9a-f]{32}\.(pdf|jpg|png)$")


def ler_arquivo_enviado():
    """Valida o multipart 'arquivo'. Devolve (dados, mime, None) ou (None, None, (resposta, status))."""
    arquivo = request.files.get("arquivo")
    if arquivo is None or not arquivo.filename:
        return None, None, (jsonify({"error": "arquivo obrigatório"}), 400)
    mime = arquivo.mimetype
    if mime not in storage.EXTENSOES:
        return None, None, (jsonify({"error": "Só PDF, JPG ou PNG"}), 400)
    dados = arquivo.read()
    if len(dados) > _TAMANHO_MAX:
        return None, None, (jsonify({"error": "Arquivo maior que 10 MB"}), 400)
    return dados, mime, None


def subir_pendente(dados, mime):
    """Limpa pendentes velhos e sobe o arquivo. Falha de limpeza não impede a leitura."""
    try:
        storage.limpar_pendentes()
    except Exception as e:
        print(f"[storage] limpeza de pendentes falhou: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
    return storage.enviar_pendente(dados, mime)


def arquivo_token_valido(token):
    return bool(token) and _RE_ARQUIVO_TOKEN.match(token) is not None


def destino_anexo(prefixo, pasta, registro_id, token):
    """Caminho definitivo do anexo: <prefixo>/<pasta>/<registro_id>.<ext>.

    Fornecedores: prefixo = id do fornecedor, pasta 'pedidos'/'pagamentos'.
    Funcionários: prefixo = 'funcionarios/<id>', pasta = competência 'AAAA-MM',
    registro_id = '<tipo>[-boleto|-comprovante]-<id>'.
    """
    if not arquivo_token_valido(token):
        raise ValueError("arquivo_token inválido")
    ext = token.rsplit(".", 1)[-1]
    return f"{prefixo}/{pasta}/{registro_id}.{ext}"


def url_anexo(tabela, coluna_dono, dono_id, registro_id, coluna_arquivo="arquivo_path"):
    """URL assinada (1 h) do anexo de um registro, conferindo o dono.

    `tabela`, `coluna_dono` e `coluna_arquivo` são constantes escritas no código
    das rotas — nunca vêm da request.
    """
    rows = db.query(
        f"SELECT {coluna_arquivo} FROM {tabela} WHERE id = %s AND {coluna_dono} = %s",
        (registro_id, dono_id)
    )
    if not rows or not rows[0][coluna_arquivo]:
        return jsonify({"error": "Sem anexo"}), 404
    try:
        return jsonify({"url": storage.url_assinada(rows[0][coluna_arquivo])})
    except storage.StorageErro as e:
        print(f"[storage] falhou ao assinar URL do anexo: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return jsonify({"error": "Não consegui abrir o anexo agora. Tente de novo."}), 500
