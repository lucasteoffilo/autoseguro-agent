"""Mensagens do lead que o PROVEDOR do modelo rejeitou (HTTP 400, 422 ou `content_filter`).

Rodada do DEMO de 2026-10-21: o cenario 7 (injecao) recebeu 400 no turno 2 e, no turno 3, o 400 veio de novo porque o pedido ainda levava a mensagem rejeitada no historico, e dois
rejeitos seguidos encerram a conversa em SAFETY_GUARD. A mensagem rejeitada continua no banco (auditoria), mas NAO volta ao modelo nos turnos seguintes: sai do historico do prompt e do
conjunto de textos do lead que o guardrail aceita ecoar. O export a marca com `REJECTED_NOTE`."""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

REJECTED_ERRORS = ("http_400", "http_422", "content_filter")
REJECTED_NOTE = "rejeitada pelo provedor, fora do contexto do modelo"


def rejected_lead_ids(messages: Iterable[Mapping[str, Any]]) -> set[str]:
    """Os ids das mensagens do lead cujo turno terminou com o provedor rejeitando o pedido (`llm_error` no meta da resposta do agente). Um content_filter que passou na repeticao
    nao deixa `llm_error`: aquela mensagem foi aceita no fim e fica no contexto."""
    out: set[str] = set()
    last: str | None = None
    for m in messages:
        if m["role"] == "lead":
            last = m["id"]
        elif last is not None and json.loads(m["meta"]).get("llm_error") in REJECTED_ERRORS:
            out.add(last)
    return out
