"""Fabrica da camada de LLM: a UNICA porta de entrada do produto para um cliente de LLM.

Devolve sempre um `GuardedLLM` (gate de PII + guardrail por fora de qualquer adaptador). Trocar `LLM_PROVIDER` troca o adaptador e nao
contorna nenhuma protecao. Os adaptadores continuam importaveis (os testes os exercitam), mas o produto so os obtem por aqui.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from ..facts import FactBase
from .base import LLMClient
from .claude import ClaudeLLM
from .config import ConfigError, LLMConfig
from .guarded import GuardedLLM
from .openai_compat import OpenAICompatLLM

_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


def make_adapter(cfg: LLMConfig, fact_base: FactBase, *, client: Any = None) -> LLMClient:
    if cfg.provider == "anthropic":
        return ClaudeLLM(cfg.model, fact_base, client=client, api_key=cfg.api_key, max_tokens=cfg.max_tokens, timeout_s=cfg.timeout_s,
                         base_url=cfg.base_url)
    local = (urlparse(cfg.base_url or "").hostname or "") in _LOCAL_HOSTS
    if not cfg.api_key and not local:
        raise ConfigError(cfg.missing_key_message())
    return OpenAICompatLLM(cfg.model, fact_base, base_url=cfg.base_url or "", api_key=cfg.api_key, provider=cfg.provider,
                           structured_output=cfg.structured_output, reasoning_effort=cfg.reasoning_effort, max_tokens=cfg.max_tokens,
                           timeout_s=cfg.timeout_s, temperature=cfg.temperature)


def make_llm(cfg: LLMConfig, fact_base: FactBase, *, wrap: Callable[[LLMClient], LLMClient] | None = None, client: Any = None) -> GuardedLLM:
    """`wrap`: decorador opcional ENTRE o adaptador e o guarda (ex.: `ThrottledLLM` para o free tier). O guarda e sempre o mais externo."""
    adapter = make_adapter(cfg, fact_base, client=client)
    return GuardedLLM(wrap(adapter) if wrap else adapter, fact_base)
