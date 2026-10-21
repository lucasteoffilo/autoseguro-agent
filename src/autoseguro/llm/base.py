"""Tipos comuns da camada de LLM, que NAO dependem de provedor.

Contrato: um adaptador (Anthropic, OpenRouter, qualquer endpoint compativel com OpenAI) so sabe falar com o seu provedor e devolver texto.
Tudo que importa para a seguranca fica ACIMA dele:
  - a validacao LOCAL do formato (`result_from_text`): nao se confia em "saida estruturada garantida" de provedor nenhum;
  - o gate de PII e o guardrail do `reply` (`llm/guarded.py`), aplicados a qualquer adaptador pela fabrica (`llm/factory.py`).
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from .schema import OutputError, TurnOutput, parse_turn_output


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0   # ja incluidos em output_tokens quando o provedor informa


@dataclass(frozen=True)
class LLMResult:
    output: TurnOutput | None
    # "timeout" | "connection" | "http_<status>" | "refusal" | "max_tokens" | "content_filter" | "no_text" | "no_choices"
    # | "provider_error:<code>" | "invalid_output:<motivo>"
    error: str | None
    latency_s: float
    usage: Usage | None
    stop_reason: str | None
    request_id: str | None = None
    http_status: int | None = None
    retry_after_s: float | None = None   # dica do provedor num 429
    quota_kind: str | None = None        # num 429: "daily" (esgotou o dia) | "rate" (limite por minuto ou do provedor)
    detail: str | None = None            # explicacao curta do provedor, JA sem segredos
    served_model: str | None = None      # o modelo que de fato respondeu (o roteador pode trocar)
    wait_s: float = 0.0                  # tempo PARADO antes de a resposta chegar: espera do limitador de taxa e sleeps do backoff de 429. Nao e tempo do provedor nem do sistema


class LLMClient(Protocol):
    provider: str
    model: str
    system_prompt: str

    def turn(self, user_message: str) -> LLMResult: ...


def outcome_class(error: str | None) -> str:
    """Quem falhou. "answered": o provedor entregou uma resposta (boa ou ruim: saida fora do schema, truncada ou vazia e falha do MODELO). "blocked": o provedor
    bloqueou (`content_filter`), que nao e erro de formato do modelo. "service": timeout, conexao, 429, 5xx e erro de protocolo: falha do servico, nao da conversa."""
    if error is None or error.startswith("invalid_output") or error in ("max_tokens", "no_text", "no_choices"):
        return "answered"
    return "blocked" if error == "content_filter" else "service"


def result_from_text(text: str, fact_ids: Sequence[str], *, latency_s: float, usage: Usage | None, stop_reason: str | None,
                     request_id: str | None = None, http_status: int | None = None, served_model: str | None = None) -> LLMResult:
    """Validacao LOCAL e unica, igual para todo provedor. Saida que nao casa com o esquema NUNCA vira dado: vira erro, e o orquestrador
    cai no template ou escala. Sem 'conserto': JSON dentro de cerca de markdown, por exemplo, e invalido."""
    common = dict(latency_s=latency_s, usage=usage, stop_reason=stop_reason, request_id=request_id, http_status=http_status,
                  served_model=served_model)
    try:
        obj = json.loads(text)
    except ValueError as exc:
        return LLMResult(None, f"invalid_output:{type(exc).__name__}", **common)
    try:
        return LLMResult(parse_turn_output(obj, fact_ids), None, **common)
    except OutputError as exc:
        return LLMResult(None, f"invalid_output:{type(exc).__name__}", **common)
