"""Adaptador OpenAI-compativel (OpenRouter) contra um servidor LOCAL falso: formato exato do pedido e tratamento de cada resposta.
Sem rede e sem chave real. NAO prova que o OpenRouter aceita o pedido: isso e o `make smoke-llm`, rodado pelo autor."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from autoseguro.facts import FactBase
from autoseguro.llm.config import ConfigError
from autoseguro.llm.openai_compat import OpenAICompatLLM
from tests.fake_servers import CANARY_KEY, GOOD, FakeServer, chat_json, error_json

ROOT = Path(__file__).resolve().parent.parent
BASE = FactBase.from_planos(json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8")))


@pytest.fixture
def server():
    s = FakeServer()
    s.reply(200, chat_json(json.dumps(GOOD)))
    yield s
    s.close()


def make(server, **kw) -> OpenAICompatLLM:
    opts = dict(base_url=server.url, api_key=CANARY_KEY, provider="openrouter", reasoning_effort="none", timeout_s=3.0)
    opts.update(kw)
    return OpenAICompatLLM("vendor/model:free", BASE, **opts)


# --- o pedido ---------------------------------------------------------------------------------------------------------------------
def test_request_has_exactly_the_documented_openrouter_shape(server):
    llm = make(server)
    llm.turn("mensagem de teste")
    (req,) = server.requests
    body = req["body"]
    assert req["method"] == "POST" and req["path"] == "/chat/completions"
    assert req["headers"]["authorization"] == f"Bearer {CANARY_KEY}" and req["headers"]["content-type"] == "application/json"
    assert body["model"] == "vendor/model:free" and body["max_tokens"] == 800
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"] == llm.system_prompt and body["messages"][1]["content"] == "mensagem de teste"
    assert body["response_format"] == {"type": "json_schema", "json_schema": {"name": "turn_output", "strict": True, "schema": llm._schema}}
    assert body["reasoning"] == {"effort": "none"}
    assert body["provider"] == {"require_parameters": True}, "so roteia a endpoints que suportam TODOS os parametros pedidos"
    for absent in ("temperature", "tools", "stream", "plugins", "top_p"):
        assert absent not in body


def test_the_format_is_also_written_in_the_prompt_because_some_providers_treat_the_schema_as_a_hint(server):
    assert "FORMATO DE SAÍDA" in make(server).system_prompt and "FORMATO DE SAÍDA" in make(server, structured_output="none").system_prompt


def test_without_structured_output_there_is_no_response_format(server):
    make(server, structured_output="none", reasoning_effort=None).turn("x")
    body = server.requests[0]["body"]
    assert "response_format" not in body and "provider" not in body and "reasoning" not in body


def test_openrouter_extensions_are_only_sent_to_openrouter(server):
    make(server, provider="openai_compat", reasoning_effort="low").turn("x")
    body = server.requests[0]["body"]
    assert "reasoning" not in body and "provider" not in body and "response_format" in body  # response_format e padrao OpenAI


def test_temperature_is_sent_only_when_configured(server):
    make(server, temperature=0.0).turn("x")
    assert server.requests[0]["body"]["temperature"] == 0.0


# --- a resposta ---------------------------------------------------------------------------------------------------------------------
def test_successful_turn_is_parsed_with_usage_and_served_model(server):
    server.reply(200, chat_json(json.dumps(GOOD), model="other/served:free", completion_tokens=200, reasoning_tokens=70, cached_tokens=1500))
    res = make(server).turn("x")
    assert res.error is None and res.output.value("idade") == "42" and res.output.reply == "Anotado! Qual o seu CEP?"
    assert (res.usage.input_tokens, res.usage.output_tokens, res.usage.reasoning_tokens, res.usage.cache_read_tokens) == (2400, 200, 70, 1500)
    assert res.served_model == "other/served:free" and res.request_id == "gen-test-123" and res.http_status == 200 and res.latency_s > 0


@pytest.mark.parametrize("payload,expected", [
    (chat_json('{"slots":', finish_reason="length"), "max_tokens"),            # raciocinio consumiu o orcamento: truncado
    (chat_json("", finish_reason="length"), "max_tokens"),                      # ... ou conteudo vazio
    (chat_json(None), "no_text"), (chat_json("   "), "no_text"),
    (chat_json(json.dumps(GOOD), finish_reason="content_filter"), "content_filter"),
    (chat_json(json.dumps(GOOD), finish_reason="error"), "provider_error:finish_reason"),
    ({"id": "gen-x", "choices": []}, "no_choices"), ({"id": "gen-x"}, "no_choices"), ({"choices": ["x"]}, "no_choices"),
])
def test_responses_that_are_not_usable_output_are_errors_never_data(server, payload, expected):
    server.reply(200, payload)
    res = make(server).turn("x")
    assert res.output is None and res.error == expected


# --- NAO CONFIA no provedor: validacao local do formato --------------------------------------------------------------------------------
@pytest.mark.parametrize("content,expected", [
    ("isto nao e json {", "invalid_output:JSONDecodeError"),
    ("```json\n" + json.dumps(GOOD) + "\n```", "invalid_output:JSONDecodeError"),   # cerca de markdown: SEM conserto, e invalido
    ("Aqui esta o JSON: " + json.dumps(GOOD), "invalid_output:JSONDecodeError"),
    (json.dumps({**GOOD, "intent": "inventado"}), "invalid_output:OutputError"),     # o provedor "garantiu" o esquema; o esquema local nao concorda
    (json.dumps({**GOOD, "extra": 1}), "invalid_output:OutputError"),
    (json.dumps({"slots": [], "intent": "greeting", "facts_used": [], "reply": 7}), "invalid_output:OutputError"),
    (json.dumps([GOOD]), "invalid_output:OutputError"), ("null", "invalid_output:OutputError"),
])
def test_output_that_violates_the_local_schema_is_rejected_even_if_the_provider_claims_strict_mode(server, content, expected):
    server.reply(200, chat_json(content))
    res = make(server).turn("x")
    assert res.output is None and res.error == expected and res.usage is not None


# --- erros HTTP e erros dentro de um 200 -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("status", [400, 401, 402, 403, 408, 502, 503])
def test_http_errors_are_classified_by_status(server, status):
    server.reply(status, error_json(status, "algo deu errado"))
    res = make(server).turn("x")
    assert res.error == f"http_{status}" and res.http_status == status and res.output is None and res.detail == "algo deu errado"


def test_a_non_json_error_page_is_still_a_classified_error(server):
    server.reply(502, b"<html>Bad Gateway</html>")
    res = make(server).turn("x")
    assert res.error == "http_502" and res.detail is None


def test_an_error_inside_a_200_is_an_error_not_a_result(server):
    server.reply(200, error_json(502, "Provider returned error"))
    res = make(server).turn("x")
    assert res.error == "http_502" and res.http_status == 502
    server.reply(200, {"error": {"message": "boom", "code": "weird"}})
    assert make(server).turn("x").error == "provider_error:weird"


# --- 429 ------------------------------------------------------------------------------------------------------------------------------------
def test_429_exposes_retry_after_and_marks_it_as_a_rate_limit(server):
    server.reply(429, error_json(429, "Rate limit exceeded: free-models-per-min.", error_type="rate_limit_exceeded"), {"Retry-After": "7"})
    res = make(server).turn("x")
    assert (res.error, res.http_status, res.quota_kind, res.retry_after_s) == ("http_429", 429, "rate", 7.0)


def test_429_reads_the_reset_header_when_there_is_no_retry_after(server):
    reset_ms = str(int((time.time() + 12) * 1000))
    server.reply(429, error_json(429, "Rate limit exceeded"), {"X-RateLimit-Reset": reset_ms, "X-RateLimit-Remaining": "0"})
    assert 10.0 <= make(server).turn("x").retry_after_s <= 13.0


def test_retry_after_is_capped_so_a_hostile_header_cannot_stall_the_agent(server):
    server.reply(429, error_json(429, "slow down"), {"Retry-After": "99999"})
    assert make(server).turn("x").retry_after_s == 120.0


@pytest.mark.parametrize("message", ["Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day",
                                     "You exceeded your daily limit"])
def test_a_daily_429_is_told_apart_from_a_per_minute_one(server, message):
    server.reply(429, error_json(429, message, error_type="rate_limit_exceeded"))
    assert make(server).turn("x").quota_kind == "daily"


# --- prazo, conexao ---------------------------------------------------------------------------------------------------------------------------
def test_a_slow_response_times_out_inside_the_total_budget(server):
    server.delay = 1.5
    t0 = time.perf_counter()
    res = make(server, timeout_s=0.3).turn("x")
    assert res.error == "timeout" and time.perf_counter() - t0 < 1.0


def test_connection_refused_is_a_connection_error():
    res = OpenAICompatLLM("m", BASE, base_url="http://127.0.0.1:9", api_key=CANARY_KEY, timeout_s=1.0).turn("x")
    assert res.error == "connection"


# --- chave e destino ---------------------------------------------------------------------------------------------------------------------------
def test_the_adapter_never_sends_an_anthropic_key_to_another_provider(server):
    with pytest.raises(ConfigError):
        make(server, api_key="sk-ant" + "-api03-abcdefghij")


def test_the_adapter_refuses_plain_http_to_a_remote_host_because_the_key_would_travel_in_clear():
    with pytest.raises(ConfigError, match="https"):
        OpenAICompatLLM("m", BASE, base_url="http://api.exemplo.com/v1", api_key=CANARY_KEY)
    OpenAICompatLLM("m", BASE, base_url="https://openrouter.ai/api/v1", api_key=CANARY_KEY)  # https remoto: ok


def test_the_error_detail_never_echoes_the_key(server):
    server.reply(401, error_json(401, f"Invalid key {CANARY_KEY}. Authorization: Bearer {CANARY_KEY}"))
    res = make(server).turn("x")
    assert res.error == "http_401" and CANARY_KEY not in (res.detail or "") and "[REDACTED]" in res.detail


def test_repr_never_shows_the_key(server):
    assert CANARY_KEY not in repr(make(server)) and CANARY_KEY not in str(make(server))
