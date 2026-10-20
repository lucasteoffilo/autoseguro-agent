"""ClaudeLLM contra um servidor HTTP LOCAL que imita a API de mensagens: prova o formato EXATO do pedido (que o SDK serializa) e o tratamento
de cada resposta, sem chave e sem rede. NAO prova que a API real aceita o pedido: isso e o `make smoke-llm`, rodado pelo autor."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

anthropic = pytest.importorskip("anthropic")

from autoseguro.facts import FactBase  # noqa: E402
from autoseguro.llm.claude import ClaudeLLM  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BASE = FactBase.from_planos(json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8")))

GOOD = {"slots": [{"slot": "idade", "value": "42", "uncertain": False}], "intent": "provide_info", "facts_used": [], "reply": "Anotado! Qual o CEP?"}


def message_json(text: str, stop_reason: str = "end_turn", **usage) -> dict:
    u = {"input_tokens": 2400, "output_tokens": 130, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    u.update(usage)
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "stop_reason": stop_reason,
            "stop_sequence": None, "content": [{"type": "text", "text": text}], "usage": u}


class FakeAPI:
    def __init__(self):
        self.requests: list[dict] = []
        self.status, self.payload, self.delay = 200, message_json(json.dumps(GOOD)), 0.0
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                api.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                time.sleep(api.delay)
                data = json.dumps(api.payload).encode()
                self.send_response(api.status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass  # o cliente ja desistiu (timeout)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-de-teste-nao-e-real")
    fake = FakeAPI()
    yield fake
    fake.server.shutdown()


def llm(api, **kw):
    return ClaudeLLM("claude-haiku-5-5", BASE, base_url=api.url, **kw)


def test_request_has_exactly_the_documented_shape(api):
    """Saida estruturada por output_config.format, effort DENTRO de output_config, sem parametros de amostragem."""
    client = llm(api)
    client.turn("mensagem de teste")
    (req,) = api.requests
    body = req["body"]
    assert req["path"].endswith("/v1/messages")
    assert body["model"] == "claude-haiku-5-5" and body["max_tokens"] == 600
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"] == client._schema
    assert body["system"][0]["text"] == client.system_prompt and "cache_control" not in body["system"][0]
    assert body["messages"] == [{"role": "user", "content": "mensagem de teste"}]
    for forbidden in ("temperature", "top_p", "top_k", "thinking", "tools", "tool_choice", "stream"):
        assert forbidden not in body, f"{forbidden} nao pode ir (400 no Haiku 5.5 / Sonnet 5.5, ou fora do desenho)"
    assert "x-api-key" in req["headers"]


def test_prompt_cache_is_off_by_default_and_marks_only_the_static_system_prefix_when_on(api):
    llm(api, prompt_cache=True).turn("x")
    block = api.requests[-1]["body"]["system"][0]
    assert block["cache_control"] == {"type": "ephemeral"} and api.requests[-1]["body"]["messages"][0]["content"] == "x"


def test_successful_turn_is_parsed_with_usage(api):
    api.payload = message_json(json.dumps(GOOD), cache_read_input_tokens=1800, cache_creation_input_tokens=0)
    res = llm(api).turn("x")
    assert res.error is None and res.output is not None and res.output.value("idade") == "42" and res.output.reply == "Anotado! Qual o CEP?"
    assert (res.usage.input_tokens, res.usage.output_tokens, res.usage.cache_read_tokens) == (2400, 130, 1800)
    assert res.latency_s > 0 and res.stop_reason == "end_turn"


def test_sdk_retries_are_disabled_because_the_orchestrator_owns_the_retry(api):
    api.status, api.payload = 500, {"type": "error", "error": {"type": "api_error", "message": "boom"}}
    res = llm(api).turn("x")
    assert res.error == "http_500" and len(api.requests) == 1, "o SDK repetiria 2x por padrao e estouraria o orcamento de 6s"


def test_429_is_reported_without_retrying(api):
    api.status, api.payload = 429, {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
    res = llm(api).turn("x")
    assert res.error == "http_429" and len(api.requests) == 1


def test_a_slow_call_times_out_inside_the_call_budget(api):
    api.delay = 1.5
    t0 = time.perf_counter()
    res = llm(api, timeout_s=0.3).turn("x")
    assert res.error == "timeout" and time.perf_counter() - t0 < 1.2


@pytest.mark.parametrize("stop,expected", [("refusal", "refusal"), ("max_tokens", "max_tokens")])
def test_stop_reasons_that_break_the_contract_are_errors(api, stop, expected):
    api.payload = message_json(json.dumps(GOOD), stop_reason=stop)
    res = llm(api).turn("x")
    assert res.output is None and res.error == expected and res.usage is not None


def test_invalid_json_and_schema_violations_are_errors_not_exceptions(api):
    api.payload = message_json("nao e json {")
    assert llm(api).turn("x").error.startswith("invalid_output:")
    api.payload = message_json(json.dumps({**GOOD, "intent": "inventado"}))
    assert llm(api).turn("x").error == "invalid_output:OutputError"


def test_response_without_a_text_block_is_an_error(api):
    api.payload = {**message_json("x"), "content": []}
    assert llm(api).turn("x").error == "no_text"


def test_connection_refused_is_a_connection_error():
    res = ClaudeLLM("claude-haiku-5-5", BASE, base_url="http://127.0.0.1:9", timeout_s=1.0, client=anthropic.Anthropic(api_key="x", base_url="http://127.0.0.1:9")).turn("x")
    assert res.error == "connection"
