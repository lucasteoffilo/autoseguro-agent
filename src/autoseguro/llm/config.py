"""Configuracao da camada de LLM por variavel de ambiente.

  LLM_PROVIDER   openrouter (padrao) | openai_compat (qualquer endpoint compativel com OpenAI) | anthropic (ClaudeLLM, opcional)
  LLM_BASE_URL   padrao do openrouter: https://openrouter.ai/api/v1
  LLM_MODEL      padrao do openrouter: dots-studio/dots-3-note-preview:free  (ALVO do smoke, nao escolha: quem decide e o smoke)
  LLM_API_KEY    a chave do provedor. Para openrouter, OPENROUTER_API_KEY tambem vale (e o nome que o ecossistema usa)
  LLM_STRUCTURED_OUTPUT   json_schema | none      (so use json_schema se o MODELO suportar: ver docs/PLAN.md, secao 5.5)
  LLM_REASONING_EFFORT    none | minimal | low | medium | high | off   ("off" = nao envia o campo)
  LLM_MAX_TOKENS, LLM_TIMEOUT_S, LLM_TEMPERATURE

Regras que protegem a chave: a chave da Anthropic so vai para a Anthropic e a do OpenRouter so para o OpenRouter. O ClaudeLLM usa parametros
da Anthropic (output_config, effort) que o OpenRouter nao garante, entao ele NUNCA recebe a chave nem a URL do OpenRouter. Chave nunca
trafega por http puro (exceto localhost, para os testes). Nenhuma mensagem de erro daqui contem o valor de uma chave.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .. import budgets

PROVIDERS = ("openrouter", "openai_compat", "anthropic")
DEFAULT_BASE_URL = {"openrouter": "https://openrouter.ai/api/v1"}
DEFAULT_MODEL = {"openrouter": "dots-studio/dots-3-note-preview:free", "anthropic": "claude-haiku-5-5"}
DEFAULT_MAX_TOKENS = {"openrouter": 800, "openai_compat": 800, "anthropic": 600}
STRUCTURED = ("json_schema", "none")
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class ConfigError(ValueError):
    """Configuracao invalida. A mensagem nunca contem o valor de uma chave."""


def is_openrouter_host(base_url: str | None) -> bool:
    return bool(base_url) and "openrouter" in (urlparse(base_url).hostname or "")


def assert_anthropic_is_not_pointed_at_openrouter(base_url: str | None, api_key: str | None) -> None:
    """O ClaudeLLM usa parametros da Anthropic que o OpenRouter nao garante: nada do OpenRouter passa por ele."""
    if is_openrouter_host(base_url):
        raise ConfigError("o ClaudeLLM (provider anthropic) nao pode apontar para o OpenRouter: ele usa parametros da Anthropic "
                          "(output_config, effort) que o OpenRouter nao garante. Use LLM_PROVIDER=openrouter.")
    if api_key and api_key.startswith("sk-or-"):
        raise ConfigError("a chave do OpenRouter (sk-or-) nao pode ser usada com o ClaudeLLM (provider anthropic).")


def assert_secure_url(base_url: str) -> None:
    """A chave nao trafega em http puro: so https, ou localhost (testes)."""
    parsed = urlparse(base_url)
    if parsed.scheme != "https" and (parsed.hostname or "") not in _LOCAL_HOSTS:
        raise ConfigError("a URL do provedor precisa ser https (a chave nao trafega em http puro; so localhost e aceito sem TLS).")


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str | None
    api_key: str | None = field(default=None, repr=False)   # repr=False: a chave nunca aparece em repr, log nem traceback de dataclass
    structured_output: str = "json_schema"
    reasoning_effort: str | None = None
    max_tokens: int = 800
    timeout_s: float = budgets.LLM_CALL_TIMEOUT_S
    temperature: float | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LLMConfig:
        env = os.environ if env is None else env
        get = lambda k: (env.get(k) or "").strip() or None  # noqa: E731
        provider = (get("LLM_PROVIDER") or "openrouter").lower()
        if provider not in PROVIDERS:
            raise ConfigError(f"LLM_PROVIDER invalido: use um de {', '.join(PROVIDERS)}")
        model = get("LLM_MODEL") or DEFAULT_MODEL.get(provider)
        if not model:
            raise ConfigError(f"LLM_MODEL e obrigatorio para o provider {provider}")
        base_url = get("LLM_BASE_URL") or DEFAULT_BASE_URL.get(provider)
        if provider == "openai_compat" and not base_url:
            raise ConfigError("LLM_BASE_URL e obrigatoria para o provider openai_compat")

        if provider == "anthropic":
            api_key = get("ANTHROPIC_API_KEY")
            assert_anthropic_is_not_pointed_at_openrouter(base_url, api_key)
        elif provider == "openrouter":
            api_key = get("LLM_API_KEY") or get("OPENROUTER_API_KEY")
        else:
            api_key = get("LLM_API_KEY")
        if provider != "anthropic" and api_key and api_key.startswith("sk-ant-"):
            raise ConfigError("uma chave da Anthropic (sk-ant-) nao e enviada a outro provedor.")
        if provider != "anthropic" and base_url:
            assert_secure_url(base_url)

        structured = (get("LLM_STRUCTURED_OUTPUT") or {"openrouter": "json_schema"}.get(provider, "none")).lower()
        if structured not in STRUCTURED:
            raise ConfigError(f"LLM_STRUCTURED_OUTPUT invalido: use um de {', '.join(STRUCTURED)}")
        effort = (get("LLM_REASONING_EFFORT") or {"openrouter": "none"}.get(provider, "off")).lower()
        try:
            max_tokens = int(get("LLM_MAX_TOKENS") or DEFAULT_MAX_TOKENS[provider])
            timeout_s = float(get("LLM_TIMEOUT_S") or budgets.LLM_CALL_TIMEOUT_S)
            temperature = float(get("LLM_TEMPERATURE")) if get("LLM_TEMPERATURE") else None
        except ValueError:
            raise ConfigError("LLM_MAX_TOKENS, LLM_TIMEOUT_S e LLM_TEMPERATURE precisam ser numeros") from None
        if max_tokens <= 0 or timeout_s <= 0:
            raise ConfigError("LLM_MAX_TOKENS e LLM_TIMEOUT_S precisam ser positivos")
        return cls(provider, model, base_url, api_key, structured, None if effort == "off" else effort, max_tokens, timeout_s, temperature)

    def missing_key_message(self) -> str:
        if self.provider == "anthropic":
            return "ANTHROPIC_API_KEY ausente (provider anthropic)."
        extra = " (OPENROUTER_API_KEY tambem vale)" if self.provider == "openrouter" else ""
        return f"LLM_API_KEY ausente{extra}. A ANTHROPIC_API_KEY nao e usada pelo provider {self.provider}, de proposito."
