"""Configuracao por ambiente: LLM_PROVIDER, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL. O que protege a chave."""
from __future__ import annotations

import pytest

from autoseguro import budgets
from autoseguro.llm.config import DEFAULT_BASE_URL, DEFAULT_MODEL, ConfigError, LLMConfig
from tests.fake_servers import CANARY_KEY

ANTHROPIC_KEY = "sk-ant" + "-api03-ANTHROPICKEY0123456789"


def cfg(**env) -> LLMConfig:
    return LLMConfig.from_env(env)


def test_defaults_are_openrouter_with_a_free_model_that_declares_structured_outputs():
    c = cfg(LLM_API_KEY=CANARY_KEY)
    assert (c.provider, c.base_url, c.model) == ("openrouter", "https://openrouter.ai/api/v1", DEFAULT_MODEL["openrouter"])
    assert c.model.endswith(":free") and c.structured_output == "json_schema" and c.reasoning_effort == "none"
    assert c.max_tokens == 800 and c.timeout_s == budgets.LLM_CALL_TIMEOUT_S and c.temperature is None


def test_every_variable_asked_for_is_honoured():
    c = cfg(LLM_PROVIDER="openai_compat", LLM_BASE_URL="https://llm.exemplo.com/v1", LLM_API_KEY=CANARY_KEY, LLM_MODEL="acme/m1",
            LLM_STRUCTURED_OUTPUT="none", LLM_REASONING_EFFORT="low", LLM_MAX_TOKENS="1200", LLM_TIMEOUT_S="9", LLM_TEMPERATURE="0.2")
    assert (c.provider, c.base_url, c.model, c.structured_output, c.reasoning_effort, c.max_tokens, c.timeout_s, c.temperature) == (
        "openai_compat", "https://llm.exemplo.com/v1", "acme/m1", "none", "low", 1200, 9.0, 0.2)


def test_openrouter_accepts_the_ecosystem_variable_name_but_llm_api_key_wins():
    """O .env do autor tem OPENROUTER_API_KEY. LLM_API_KEY, quando existe, tem precedencia."""
    assert cfg(OPENROUTER_API_KEY=CANARY_KEY).api_key == CANARY_KEY
    assert cfg(OPENROUTER_API_KEY="outra", LLM_API_KEY=CANARY_KEY).api_key == CANARY_KEY


def test_the_anthropic_key_is_not_used_by_the_openrouter_provider_on_purpose():
    c = cfg(ANTHROPIC_API_KEY=ANTHROPIC_KEY)
    assert c.api_key is None and "ANTHROPIC_API_KEY nao e usada" in c.missing_key_message()
    assert "OPENROUTER_API_KEY" in c.missing_key_message()


def test_reasoning_off_means_the_field_is_not_sent():
    assert cfg(LLM_API_KEY=CANARY_KEY, LLM_REASONING_EFFORT="off").reasoning_effort is None


# --- a chave de um provedor nao vai para outro --------------------------------------------------------------------------------------------
def test_the_claude_adapter_cannot_be_pointed_at_openrouter():
    with pytest.raises(ConfigError, match="nao pode apontar para o OpenRouter"):
        cfg(LLM_PROVIDER="anthropic", LLM_BASE_URL="https://openrouter.ai/api/v1", ANTHROPIC_API_KEY=ANTHROPIC_KEY)


def test_an_openrouter_key_never_goes_through_the_claude_adapter():
    with pytest.raises(ConfigError, match="OpenRouter"):
        cfg(LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY=CANARY_KEY)


def test_an_anthropic_key_never_goes_to_another_provider():
    with pytest.raises(ConfigError, match="Anthropic"):
        cfg(LLM_API_KEY=ANTHROPIC_KEY)
    with pytest.raises(ConfigError, match="Anthropic"):
        cfg(LLM_PROVIDER="openai_compat", LLM_BASE_URL="https://llm.exemplo.com/v1", LLM_MODEL="acme/m1", LLM_API_KEY=ANTHROPIC_KEY)


def test_the_anthropic_provider_reads_only_the_anthropic_key():
    c = cfg(LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY=ANTHROPIC_KEY, LLM_API_KEY=CANARY_KEY)
    assert c.api_key == ANTHROPIC_KEY and c.model == DEFAULT_MODEL["anthropic"] and c.base_url is None


def test_the_key_never_travels_over_plain_http_except_to_localhost():
    with pytest.raises(ConfigError, match="https"):
        cfg(LLM_BASE_URL="http://llm.exemplo.com/v1", LLM_API_KEY=CANARY_KEY)
    assert cfg(LLM_BASE_URL="http://127.0.0.1:8123", LLM_API_KEY=CANARY_KEY).base_url == "http://127.0.0.1:8123"


# --- validacao -----------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("env", [
    {"LLM_PROVIDER": "gemini"}, {"LLM_PROVIDER": "openai_compat"}, {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "https://x.com/v1"},
    {"LLM_STRUCTURED_OUTPUT": "xml"}, {"LLM_MAX_TOKENS": "muito"}, {"LLM_MAX_TOKENS": "0"}, {"LLM_TIMEOUT_S": "-1"}, {"LLM_TEMPERATURE": "quente"},
])
def test_invalid_configuration_is_rejected(env):
    with pytest.raises(ConfigError):
        LLMConfig.from_env({"LLM_API_KEY": CANARY_KEY, **env})


def test_no_config_error_or_repr_ever_contains_a_key():
    for env in ({"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": CANARY_KEY}, {"LLM_API_KEY": ANTHROPIC_KEY, "LLM_TIMEOUT_S": "x"},
                {"LLM_PROVIDER": "anthropic", "LLM_BASE_URL": "https://openrouter.ai/api/v1", "ANTHROPIC_API_KEY": ANTHROPIC_KEY}):
        with pytest.raises(ConfigError) as e:
            LLMConfig.from_env(env)
        assert CANARY_KEY not in str(e.value) and ANTHROPIC_KEY not in str(e.value)
    c = cfg(LLM_API_KEY=CANARY_KEY)
    assert CANARY_KEY not in repr(c) and CANARY_KEY not in str(c) and CANARY_KEY not in c.missing_key_message()


def test_default_base_url_table_has_only_https():
    assert all(u.startswith("https://") for u in DEFAULT_BASE_URL.values())
