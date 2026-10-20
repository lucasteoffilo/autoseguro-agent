"""Adaptador OpenAI-compativel (chat completions), SO com a biblioteca padrao. Padrao de uso: OpenRouter (https://openrouter.ai/api/v1).

Contrato igual ao do ClaudeLLM: `turn(user_message) -> LLMResult`, uma chamada, sem retry (o retry e de quem orquestra: ver `llm/throttle.py`).
O que vem dos docs do OpenRouter (conferidos antes de codar; docs/PLAN.md, secao 5.5):
  - `response_format = {"type": "json_schema", "json_schema": {"name", "strict": true, "schema"}}`, so quando o MODELO declara `structured_outputs`;
  - suporte e POR ENDPOINT e a aplicacao do esquema varia (alguns provedores o tratam como dica): por isso o formato tambem vai escrito no prompt
    e a resposta passa SEMPRE pela validacao local (`result_from_text`). `provider.require_parameters = true` evita rotear a quem nao suporta;
  - o conteudo esta em `choices[0].message.content`; `finish_reason` normalizado ("stop", "length", "content_filter", "error");
  - modelos de raciocinio gastam o proprio `max_tokens` com o raciocinio: `finish_reason == "length"` com conteudo vazio e FALHA, nao saida;
  - erros podem vir dentro de um HTTP 200 (`{"error": {"code", "message"}}`); 429 traz `Retry-After` e `X-RateLimit-*`.

Este adaptador NAO faz gate de PII nem guardrail: isso fica acima (`llm/guarded.py`), igual para qualquer provedor. A chave so existe aqui no
cabecalho Authorization: nunca em repr, erro, log nem relatorio (tudo que sai passa por `redact`).
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from .. import budgets
from ..facts import FactBase
from .base import LLMResult, Usage, result_from_text
from .config import ConfigError, assert_secure_url, is_openrouter_host
from .prompt import build_system_prompt
from .redact import redact
from .schema import response_schema

_DAILY = re.compile(r"(?i)per[- ]day|daily|requests per day")


class _Timeout(Exception):
    pass


class _Connection(Exception):
    pass


def _int(x: Any) -> int:
    return x if isinstance(x, int) and not isinstance(x, bool) else 0


def _usage(u: Any) -> Usage | None:
    if not isinstance(u, dict):
        return None
    prompt_details = u.get("prompt_tokens_details") if isinstance(u.get("prompt_tokens_details"), dict) else {}
    completion_details = u.get("completion_tokens_details") if isinstance(u.get("completion_tokens_details"), dict) else {}
    return Usage(_int(u.get("prompt_tokens")), _int(u.get("completion_tokens")), cache_read_tokens=_int(prompt_details.get("cached_tokens")),
                 reasoning_tokens=_int(completion_details.get("reasoning_tokens")))


def _retry_after(headers: dict[str, str]) -> float | None:
    """Segundos pedidos pelo provedor: `Retry-After` (segundos) ou `X-RateLimit-Reset` (epoch em ms). Limitado a 0..120s."""
    ra = headers.get("retry-after")
    if ra:
        try:
            return max(0.0, min(120.0, float(ra)))
        except ValueError:
            pass
    reset = headers.get("x-ratelimit-reset")
    if reset:
        try:
            return max(0.0, min(120.0, float(reset) / 1000.0 - time.time()))
        except ValueError:
            pass
    return None


class OpenAICompatLLM:
    def __init__(self, model: str, fact_base: FactBase, *, base_url: str, api_key: str | None, provider: str = "openai_compat",
                 structured_output: str = "json_schema", reasoning_effort: str | None = None, max_tokens: int = 800,
                 timeout_s: float = budgets.LLM_CALL_TIMEOUT_S, temperature: float | None = None) -> None:
        assert_secure_url(base_url)
        if api_key and api_key.startswith("sk-ant-"):
            raise ConfigError("uma chave da Anthropic (sk-ant-) nao e enviada a outro provedor.")
        self.provider, self.model = provider, model
        self.structured_output, self.reasoning_effort = structured_output, reasoning_effort
        self.max_tokens, self.timeout_s, self.temperature = max_tokens, timeout_s, temperature
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._openrouter = provider == "openrouter" or is_openrouter_host(base_url)
        self._fact_ids = fact_base.ids()
        self.system_prompt = build_system_prompt(fact_base, format_hint=True)
        self._schema = response_schema(self._fact_ids)

    def __repr__(self) -> str:
        return f"OpenAICompatLLM(provider={self.provider!r}, model={self.model!r}, url={self._url!r})"  # sem a chave, de proposito

    def request_body(self, user_message: str) -> dict[str, Any]:
        """O corpo EXATO enviado (testado). `reasoning` e `provider` sao extensoes do OpenRouter e so vao quando o destino e o OpenRouter."""
        body: dict[str, Any] = {
            "model": self.model, "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user_message}]}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.structured_output == "json_schema":
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "turn_output", "strict": True, "schema": self._schema}}
        if self._openrouter:
            if self.reasoning_effort:
                body["reasoning"] = {"effort": self.reasoning_effort}
            if self.structured_output == "json_schema" or self.reasoning_effort:
                body["provider"] = {"require_parameters": True}  # so roteia a endpoints que suportam TODOS os parametros pedidos
        return body

    def _post(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = urllib.request.Request(self._url, data=body, headers=headers, method="POST")
        box: dict[str, Any] = {}

        def run() -> None:
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as r:  # noqa: S310 - URL validada por assert_secure_url
                    box["ok"] = (r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
            except urllib.error.HTTPError as exc:  # 4xx/5xx sao RESPOSTAS
                box["ok"] = (exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read())
            except urllib.error.URLError as exc:
                box["err"] = "timeout" if isinstance(exc.reason, TimeoutError) else "connection"
            except TimeoutError:
                box["err"] = "timeout"
            except Exception:  # noqa: BLE001 - qualquer outra falha de rede/IO
                box["err"] = "connection"

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(self.timeout_s)  # prazo TOTAL; o timeout do socket sozinho nao limita uma resposta que goteja
        if worker.is_alive() or box.get("err") == "timeout":
            raise _Timeout
        if "err" in box:
            raise _Connection
        return box["ok"]

    def turn(self, user_message: str) -> LLMResult:
        t0 = time.perf_counter()
        try:
            status, headers, raw = self._post(json.dumps(self.request_body(user_message)).encode())
        except _Timeout:
            return LLMResult(None, "timeout", time.perf_counter() - t0, None, None)
        except _Connection:
            return LLMResult(None, "connection", time.perf_counter() - t0, None, None)
        return self._interpret(status, headers, raw, time.perf_counter() - t0)

    def _interpret(self, status: int, headers: dict[str, str], raw: bytes, latency: float) -> LLMResult:
        try:
            body = json.loads(raw)
        except ValueError:
            body = None
        err = body.get("error") if isinstance(body, dict) else None
        message = err.get("message") if isinstance(err, dict) and isinstance(err.get("message"), str) else None
        detail = redact(message, [self._api_key], limit=200) or None
        code = err.get("code") if isinstance(err, dict) else None
        effective = status if status >= 400 else (code if isinstance(code, int) and code >= 400 else status)  # erro dentro de um HTTP 200

        if effective >= 400:
            quota_kind, retry_after = None, None
            if effective == 429:
                blob = (message or "") + json.dumps(err.get("metadata") or {}) if isinstance(err, dict) else ""
                quota_kind = "daily" if _DAILY.search(blob) else "rate"
                retry_after = _retry_after(headers)
            return LLMResult(None, f"http_{effective}", latency, None, None, http_status=effective, retry_after_s=retry_after,
                             quota_kind=quota_kind, detail=detail)
        if isinstance(err, dict):
            return LLMResult(None, f"provider_error:{code}", latency, None, None, http_status=status, detail=detail)
        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return LLMResult(None, "no_choices", latency, None, None, http_status=status)
        choice = choices[0]
        usage, rid, served = _usage(body.get("usage")), body.get("id"), body.get("model")
        rid, served = rid if isinstance(rid, str) else None, served if isinstance(served, str) else None
        finish = choice.get("finish_reason")
        common = dict(latency_s=latency, usage=usage, request_id=rid, http_status=status, served_model=served)
        if finish == "length":  # tipicamente o raciocinio consumiu o max_tokens: conteudo vazio ou cortado
            return LLMResult(None, "max_tokens", stop_reason=finish, **common)
        if finish == "content_filter":
            return LLMResult(None, "content_filter", stop_reason=finish, **common)
        if finish == "error":
            return LLMResult(None, "provider_error:finish_reason", stop_reason=finish, detail=detail, **common)
        message_obj = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = message_obj.get("content")
        if not isinstance(content, str) or not content.strip():
            return LLMResult(None, "no_text", stop_reason=finish, **common)
        return result_from_text(content, self._fact_ids, latency_s=latency, usage=usage, stop_reason=finish, request_id=rid,
                                http_status=status, served_model=served)
