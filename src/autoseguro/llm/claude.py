"""Adaptador Anthropic (ClaudeLLM): UMA chamada por mensagem, saida estruturada {slots, intent, facts_used, reply}. OPCIONAL.

Pontos que vem da documentacao do SDK e dos modelos 5.x (ver docs/PLAN.md, secao 5.3):
  - saida estruturada por `output_config={"format": {"type": "json_schema", ...}}`; o primeiro bloco e texto com JSON valido;
  - `effort` fica DENTRO de `output_config`; sem `temperature`/`top_p` (valor fora do padrao da 400 no Haiku 5.5 e no Sonnet 5.5);
  - o SDK faz 2 retries por padrao: aqui `max_retries=0`, porque o tempo de cada chamada e orcado (budgets.LLM_CALL_TIMEOUT_S);
  - o SDK so e importado quando preciso: o mock e os testes nao dependem dele;
  - NAO recebe chave nem URL do OpenRouter (ver llm/config.py): usa parametros da Anthropic que o OpenRouter nao garante.

Este adaptador NAO faz gate de PII nem guardrail: isso fica acima, em `llm/guarded.py`, para valer igual em qualquer provedor.
"""
from __future__ import annotations

import time
from typing import Any

from .. import budgets
from ..facts import FactBase
from .base import LLMResult, Usage, result_from_text  # noqa: F401  (Usage e LLMResult reexportados por compatibilidade)
from .config import assert_anthropic_is_not_pointed_at_openrouter
from .prompt import build_system_prompt
from .schema import response_schema


def _usage(u: Any) -> Usage | None:
    if u is None:
        return None
    return Usage(int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0),
                 int(getattr(u, "cache_read_input_tokens", 0) or 0), int(getattr(u, "cache_creation_input_tokens", 0) or 0))


def _classify_exception(exc: Exception) -> str:
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        return type(exc).__name__
    if isinstance(exc, anthropic.APITimeoutError):
        return "timeout"
    if isinstance(exc, anthropic.APIConnectionError):
        return "connection"
    if isinstance(exc, anthropic.APIStatusError):
        return f"http_{exc.status_code}"
    return type(exc).__name__


class ClaudeLLM:
    provider = "anthropic"

    def __init__(self, model: str, fact_base: FactBase, *, client: Any = None, api_key: str | None = None, effort: str = "low",
                 max_tokens: int = 600, timeout_s: float = budgets.LLM_CALL_TIMEOUT_S, prompt_cache: bool = False,
                 base_url: str | None = None) -> None:
        assert_anthropic_is_not_pointed_at_openrouter(base_url, api_key)
        if client is None:
            import anthropic
            kwargs: dict[str, Any] = {}
            if base_url:
                kwargs["base_url"] = base_url
            if api_key:
                kwargs["api_key"] = api_key
            client = anthropic.Anthropic(**kwargs)  # sem api_key: o SDK le ANTHROPIC_API_KEY
        self.model, self.effort, self.max_tokens, self.timeout_s = model, effort, max_tokens, timeout_s
        self._client = client
        self._fact_ids = fact_base.ids()
        self.system_prompt = build_system_prompt(fact_base)
        self._schema = response_schema(self._fact_ids)
        block: dict[str, Any] = {"type": "text", "text": self.system_prompt}
        if prompt_cache:
            block["cache_control"] = {"type": "ephemeral"}
        self._system = [block]

    def __repr__(self) -> str:
        return f"ClaudeLLM(model={self.model!r})"

    def request_kwargs(self, user_message: str) -> dict[str, Any]:
        """Os parametros EXATOS enviados a API (testados: sem temperature, effort dentro de output_config)."""
        return dict(model=self.model, max_tokens=self.max_tokens, system=self._system,
                    messages=[{"role": "user", "content": user_message}],
                    output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": self._schema}})

    def turn(self, user_message: str) -> LLMResult:
        t0 = time.perf_counter()
        try:
            resp = self._client.with_options(timeout=self.timeout_s, max_retries=0).messages.create(**self.request_kwargs(user_message))
        except Exception as exc:  # noqa: BLE001 - classificamos; o orquestrador decide (retry/handoff SAFETY_GUARD)
            return LLMResult(None, _classify_exception(exc), time.perf_counter() - t0, None, None, http_status=getattr(exc, "status_code", None))
        latency = time.perf_counter() - t0
        usage, stop = _usage(getattr(resp, "usage", None)), getattr(resp, "stop_reason", None)
        rid = getattr(resp, "_request_id", None)
        if stop in ("refusal", "max_tokens"):
            return LLMResult(None, stop, latency, usage, stop, rid)
        text = next((b.text for b in getattr(resp, "content", []) if getattr(b, "type", None) == "text"), None)
        if text is None:
            return LLMResult(None, "no_text", latency, usage, stop, rid)
        return result_from_text(text, self._fact_ids, latency_s=latency, usage=usage, stop_reason=stop, request_id=rid,
                                served_model=getattr(resp, "model", None))


__all__ = ["ClaudeLLM", "LLMResult", "Usage"]
