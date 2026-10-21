"""Midia sem transcricao: `[audio]`, `[imagem]`, `[documento]`, `[video]`. O canal entrega so um MARCADOR (mais uma descricao ou o nome do arquivo), nunca o conteudo.

Uma mensagem que comeca com o marcador e MIDIA PURA: o agente nao a le, nao chama o LLM e nao tenta extrair nada do que vem depois do marcador (a descricao de um audio e
"mensagem de voz (12s)", e esse 12 nao e idade de ninguem). O orquestrador pede o dado em texto; a segunda vez seguida, sem nenhum dado novo no meio, vai ao humano
(`MEDIA_UNREADABLE`).

LIMITE ASSUMIDO: a legenda que o lead escreve junto de uma imagem nao e lida. Se o canal entregar a legenda como texto separado, ela chega como mensagem de texto normal.
"""
from __future__ import annotations

import re

_MARK = re.compile(r"^\s*\[\s*(áudio|audio|imagem|image|foto|documento|document|doc|vídeo|video)\s*\]", re.IGNORECASE)
_KIND = {"áudio": "audio", "audio": "audio", "imagem": "image", "image": "image", "foto": "image", "documento": "document", "document": "document",
         "doc": "document", "vídeo": "video", "video": "video"}


def media_kind(text: str) -> str | None:
    """'audio' | 'image' | 'document' | 'video' se a mensagem e uma midia sem transcricao, senao None."""
    m = _MARK.match(text)
    return _KIND[m.group(1).lower()] if m else None
