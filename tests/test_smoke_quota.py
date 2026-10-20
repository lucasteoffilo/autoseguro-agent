"""O smoke de ponta a ponta contra um servidor LOCAL que imita o OpenRouter: contagem de cota, pre-checagem, 429, gate. Sem rede e sem chave real."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from autoseguro.llm.config import DEFAULT_MODEL
from tools import smoke_llm
from tools.smoke_messages import MESSAGES, SmokeMessage
from tests.fake_servers import CANARY_KEY, GOOD, FakeServer, chat_json, error_json

PLANNED = 1 + len(MESSAGES) * 2   # 31


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", CANARY_KEY)
    s = FakeServer()
    s.reply(200, chat_json(json.dumps(GOOD)))
    yield s
    s.close()


def run(tmp_path, server, *extra) -> int:
    return smoke_llm.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--rpm", "60000", "--no-remote-check", "--backoff-base-s", "0",
                           "--timeout", "3", *extra])


def quota_lines(tmp_path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "quota.jsonl").read_text().splitlines()]


def posts(server) -> list[dict]:
    return [r for r in server.requests if r["method"] == "POST"]


def test_a_full_run_sends_exactly_the_planned_requests_and_counts_each_one(tmp_path, server, capsys):
    run(tmp_path, server)  # o veredito (passa ou nao) nao importa aqui; o servidor devolve sempre a mesma saida
    assert len(posts(server)) == PLANNED == 31
    reqs = [r for r in quota_lines(tmp_path) if r["kind"] == "request"]
    assert len(reqs) == 31 and {r["outcome"] for r in reqs} == {"ok"}
    (report,) = tmp_path.glob("smoke-*.json")
    data = json.loads(report.read_text())
    assert data["requests_sent"] == 31 and data["quota"] == {"limit": 50, "used_today": 31} and data["retries_on_429"] == 0
    assert data["provider"] == "openrouter" and data["model"].endswith(":free") and data["config"]["structured_output"] == "json_schema"
    out = capsys.readouterr().out
    assert "requisicao 31/50 hoje" in out and "requisicoes enviadas nesta execucao: 31" in out and f"provedor: openrouter | modelo: {DEFAULT_MODEL['openrouter']}" in out


def test_every_request_carries_the_documented_openrouter_shape(tmp_path, server):
    run(tmp_path, server)
    body = posts(server)[0]["body"]
    assert posts(server)[0]["path"] == "/chat/completions" and body["response_format"]["type"] == "json_schema"
    assert body["reasoning"] == {"effort": "none"} and body["provider"] == {"require_parameters": True}


def test_it_aborts_before_spending_when_the_local_quota_does_not_cover_the_plan(tmp_path, server, capsys):
    now = datetime.now(UTC).isoformat()
    (tmp_path / "quota.jsonl").write_text("".join(json.dumps({"ts": now, "kind": "request", "provider": "openrouter", "model": "m:free",
                                                              "outcome": "ok", "status": 200}) + "\n" for _ in range(30)))
    assert run(tmp_path, server) == 4
    assert server.requests == [], "nada pode ter sido enviado"
    assert "ABORTADO" in capsys.readouterr().err


def test_it_asks_openrouter_for_the_real_remaining_quota_and_aborts_if_it_is_short(tmp_path, server, capsys):
    server.queue(200, {"data": {"is_free_tier": True, "free_model_daily_requests": {"used": 45, "limit": 50, "remaining": 5}}})
    assert smoke_llm.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--rpm", "60000", "--timeout", "3"]) == 4
    assert [(r["method"], r["path"]) for r in server.requests] == [("GET", "/key")], "so a consulta de cota saiu; nenhuma chamada de chat"
    out = capsys.readouterr()
    assert "OpenRouter diz restar 5" in out.out and "restam 5" in out.err


def test_when_openrouter_confirms_enough_quota_the_run_proceeds(tmp_path, server):
    server.queue(200, {"data": {"free_model_daily_requests": {"used": 0, "limit": 50, "remaining": 50}}})
    smoke_llm.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--rpm", "60000", "--backoff-base-s", "0", "--timeout", "3"])
    assert server.requests[0]["method"] == "GET" and len(posts(server)) == PLANNED


def test_an_unreachable_quota_endpoint_does_not_block_the_run_the_local_log_still_protects(tmp_path, server, capsys):
    server.queue(500, error_json(500, "boom"))
    smoke_llm.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--rpm", "60000", "--backoff-base-s", "0", "--timeout", "3"])
    assert "OpenRouter diz restar desconhecido" in capsys.readouterr().out and len(posts(server)) == PLANNED


def test_a_per_minute_429_is_backed_off_retried_and_counted(tmp_path, server, capsys):
    server.queue(429, error_json(429, "Rate limit exceeded: free-models-per-min", error_type="rate_limit_exceeded"), {"Retry-After": "0"})
    run(tmp_path, server)
    assert len(posts(server)) == PLANNED + 1
    data = json.loads(next(tmp_path.glob("smoke-*.json")).read_text())
    assert data["retries_on_429"] == 1 and data["requests_sent"] == 32 and data["quota"]["used_today"] == 32
    assert "429: espera" in capsys.readouterr().out
    assert [r["outcome"] for r in quota_lines(tmp_path) if r["kind"] == "request"][0] == "http_429", "a tentativa que falhou tambem conta na cota"


def test_a_daily_429_stops_the_run_and_marks_the_day_as_exhausted(tmp_path, server, capsys):
    server.reply(429, error_json(429, "Rate limit exceeded: free-models-per-day", error_type="rate_limit_exceeded"))
    assert run(tmp_path, server) == 4
    assert len(posts(server)) == 1, "nao insiste num limite diario"
    assert any(r["kind"] == "daily_limit_hit" for r in quota_lines(tmp_path))
    assert "cota diaria" in capsys.readouterr().err
    # uma 2a execucao no mesmo dia nao envia nada
    server.requests.clear()
    assert run(tmp_path, server) == 4 and server.requests == []


def test_a_non_free_model_has_no_local_daily_cap_but_keeps_the_rate_limit(tmp_path, server, capsys):
    run(tmp_path, server, "--model", "vendor/pago-model")
    assert len(posts(server)) == PLANNED
    assert "sem cota diaria local" in capsys.readouterr().out


def test_pii_in_a_message_aborts_the_smoke_before_a_single_request(tmp_path, server, monkeypatch, capsys):
    leaky = SmokeMessage("vaza", "meu email é " + "a" + "@" + "b.com.br")
    monkeypatch.setattr(smoke_llm, "MESSAGES", (leaky, *MESSAGES[1:]))
    assert run(tmp_path, server) == 3
    assert server.requests == [] and "ABORTADO" in capsys.readouterr().err


def test_the_requested_repetitions_and_model_are_honoured(tmp_path, server):
    run(tmp_path, server, "--repeats", "1", "--model", "outro/modelo:free")
    assert len(posts(server)) == 1 + len(MESSAGES) and posts(server)[0]["body"]["model"] == "outro/modelo:free"


# --- falha rapido: o primeiro erro de protocolo custa UMA requisicao, nao 31 -------------------------------------------------------------------
@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_the_first_protocol_error_aborts_the_smoke_having_spent_one_request(tmp_path, server, capsys, status):
    server.reply(status, error_json(status, "No endpoints found that can handle the requested parameters"))
    assert run(tmp_path, server) == 6
    assert len(posts(server)) == 1, f"HTTP {status}: so a 1a requisicao pode ter saido, nao as {PLANNED}"
    rows = [r for r in quota_lines(tmp_path) if r["kind"] == "request"]
    assert len(rows) == 1 and rows[0]["outcome"] == f"http_{status}", "a que falhou conta, e so ela"
    err = capsys.readouterr().err
    assert f"erro de protocolo (http_{status}) na chamada 1 de {PLANNED}" in err
    assert "causa provavel" in err and "requisicoes gastas nesta execucao: 1 (hoje 1/50)" in err and f"As {PLANNED - 1} restantes do plano NAO foram enviadas" in err
    assert not list(tmp_path.glob("smoke-*.json")), "sem medicao, sem relatorio: nada para confundir com resultado"


def test_the_404_for_json_schema_with_require_parameters_names_the_likely_cause(tmp_path, server, capsys):
    server.reply(404, error_json(404, "No endpoints found that can handle the requested parameters"))
    assert run(tmp_path, server) == 6
    err = capsys.readouterr().err
    assert "json_schema + require_parameters" in err and "LLM_STRUCTURED_OUTPUT=none" in err


def test_a_protocol_error_in_the_middle_of_the_run_stops_there(tmp_path, server, capsys):
    for _ in range(5):
        server.queue(200, chat_json(json.dumps(GOOD)))
    server.queue(401, error_json(401, "No auth credentials found"))
    server.reply(200, chat_json(json.dumps(GOOD)))  # se o smoke insistisse, isto teria resposta
    assert run(tmp_path, server) == 6
    assert len(posts(server)) == 6, "5 que deram certo + a 401; nada depois"
    assert f"na chamada 6 de {PLANNED}" in capsys.readouterr().err


def test_a_protocol_error_does_not_back_off_or_retry(tmp_path, server, capsys):
    server.reply(400, error_json(400, "bad"))
    run(tmp_path, server)
    assert len(posts(server)) == 1 and "espera" not in capsys.readouterr().out


def test_a_persistent_5xx_backs_off_then_trips_the_breaker_instead_of_burning_the_quota(tmp_path, server, capsys):
    server.reply(503, error_json(503, "No available provider"))
    assert run(tmp_path, server, "--max-retries", "2") == 7
    assert len(posts(server)) == 9, "3 chamadas seguidas x (1 + 2 retentativas) e para: nao gasta as 31 nem as 50"
    out = capsys.readouterr()
    assert "503: espera" in out.out and "servico instavel (3 falhas seguidas)" in out.err and "As 28 restantes" in out.err


def test_a_transient_5xx_recovers_and_the_run_completes(tmp_path, server):
    server.queue(503, error_json(503, "No available provider"))
    server.queue(500, error_json(500, "boom"))
    run(tmp_path, server)
    assert len(posts(server)) == PLANNED + 2, "2 retentativas por 5xx, depois tudo certo"
    data = json.loads(next(tmp_path.glob("smoke-*.json")).read_text())
    assert data["retries_on_429"] == 2 and data["requests_sent"] == PLANNED + 2


def test_the_breaker_threshold_is_configurable(tmp_path, server):
    server.reply(500, error_json(500, "boom"))
    assert run(tmp_path, server, "--max-retries", "0", "--max-consecutive-failures", "5") == 7
    assert len(posts(server)) == 5


def test_a_bad_model_output_is_not_a_reason_to_abort(tmp_path, server):
    """Saida invalida e dado do smoke (o criterio e 100% validas), nao falha de protocolo: roda os 31 e reprova no veredito."""
    server.reply(200, chat_json("isto nao e JSON"))
    assert run(tmp_path, server) == 1
    assert len(posts(server)) == PLANNED
