"""llm-ping: UMA requisicao real. Contra um servidor LOCAL que imita o OpenRouter: sem rede e sem chave real."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from tests.fake_servers import CANARY_KEY, GOOD, FakeServer, chat_json, error_json
from tools import llm_ping
from tools.smoke_messages import MESSAGES, SmokeMessage


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", CANARY_KEY)
    s = FakeServer()
    s.reply(200, chat_json(json.dumps(GOOD)))
    yield s
    s.close()


def ping(tmp_path, server, *extra) -> int:
    return llm_ping.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--timeout", "3", *extra])


def posts(server) -> list[dict]:
    return [r for r in server.requests if r["method"] == "POST"]


def rows(tmp_path) -> list[dict]:
    path = tmp_path / "quota.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# --- o caminho feliz -----------------------------------------------------------------------------------------------------------------------
def test_a_good_ping_sends_exactly_one_request_and_checks_the_four_things(tmp_path, server, capsys):
    assert ping(tmp_path, server) == 0
    assert len(server.requests) == 1, "UMA requisicao, e nenhuma consulta extra (nem GET /key)"
    out = capsys.readouterr().out
    assert "[ok] autenticacao nao rejeitada (sem 401/403), resposta HTTP 200" in out
    assert "[ok] pedido aceito como montado (json_schema + require_parameters, reasoning=none)" in out
    assert "[ok] saida valida no schema local" in out
    assert "latencia desta amostra" in out and "UMA amostra, nao um p95" in out
    assert "PING OK. Proximo passo: make smoke-llm" in out
    assert [r["kind"] for r in rows(tmp_path)] == ["request"] and rows(tmp_path)[0]["outcome"] == "ok", "conta na mesma cota do smoke"


def test_the_request_is_the_one_the_smoke_will_send(tmp_path, server):
    """O ping so vale se testa o MESMO pedido do smoke: json_schema estrito, require_parameters, raciocinio desligado, a chave no cabecalho."""
    ping(tmp_path, server)
    (req,) = posts(server)
    body = req["body"]
    assert req["path"] == "/chat/completions" and req["headers"]["authorization"] == f"Bearer {CANARY_KEY}"
    assert body["response_format"]["type"] == "json_schema" and body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"require_parameters": True} and body["reasoning"] == {"effort": "none"}


def test_it_reports_the_remaining_quota_against_the_smoke_plan(tmp_path, server, capsys):
    ping(tmp_path, server)
    out = capsys.readouterr().out
    assert "hoje 1/50" in out and "o smoke planeja 31 requisicoes: cabe (restam 49)" in out


def test_it_warns_when_the_smoke_will_not_fit(tmp_path, server, capsys):
    now = datetime.now(UTC).isoformat()
    (tmp_path / "quota.jsonl").write_text("".join(json.dumps({"ts": now, "kind": "request", "provider": "openrouter", "model": "m:free",
                                                              "outcome": "ok", "status": 200}) + "\n" for _ in range(30)))
    assert ping(tmp_path, server) == 0
    assert "NAO cabe (restam 19)" in capsys.readouterr().out


def test_a_slow_sample_is_flagged_but_does_not_fail_the_ping(tmp_path, server, capsys):
    server.delay = 0.3
    assert ping(tmp_path, server) == 0  # o limite derivado e 4.89s; 0.3s esta dentro
    assert "dentro do limite derivado" in capsys.readouterr().out


# --- a chave: confirmada sem mostrar nada dela -------------------------------------------------------------------------------------------
def test_it_confirms_the_key_is_set_without_showing_value_prefix_or_length(tmp_path, server, capsys):
    ping(tmp_path, server)
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert "chave: configurada" in text
    assert CANARY_KEY not in text and "sk-or" not in text and "CANARY" not in text, "nem o valor, nem o prefixo"
    assert "o valor, o prefixo e o tamanho nunca sao mostrados" in text


def test_a_missing_key_is_reported_as_absent_and_nothing_is_sent(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert llm_ping.main(["--out-dir", str(tmp_path)]) == 2  # base-url padrao = OpenRouter, nao local: a chave e obrigatoria
    captured = capsys.readouterr()
    assert "chave: AUSENTE" in captured.out and "LLM_API_KEY ausente" in captured.err
    assert rows(tmp_path) == [], "sem chave nao sai requisicao nem entra na cota"


def test_the_alias_openrouter_api_key_counts_as_configured(tmp_path, server, capsys, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY")
    monkeypatch.setenv("OPENROUTER_API_KEY", CANARY_KEY)
    assert ping(tmp_path, server) == 0
    assert "chave: configurada" in capsys.readouterr().out and posts(server)[0]["headers"]["authorization"] == f"Bearer {CANARY_KEY}"


# --- erros de protocolo: custam uma requisicao, com a causa provavel --------------------------------------------------------------------
@pytest.mark.parametrize("status", [400, 401, 402, 403, 404])
def test_a_protocol_error_is_reported_with_the_likely_cause_after_one_request(tmp_path, server, capsys, status):
    server.reply(status, error_json(status, "detalhe do provedor"))
    assert ping(tmp_path, server) == 6
    assert len(server.requests) == 1
    captured = capsys.readouterr()
    assert f"FALHA (http_{status})" in captured.err and "detalhe do provedor" in captured.err and "causa provavel" in captured.err
    assert "PING OK" not in captured.out
    assert rows(tmp_path)[0]["outcome"] == f"http_{status}" and len(rows(tmp_path)) == 1


def test_a_401_explains_how_to_fix_the_key(tmp_path, server, capsys):
    server.reply(401, error_json(401, "No auth credentials found"))
    ping(tmp_path, server)
    captured = capsys.readouterr()
    assert "[FALHA] autenticacao nao rejeitada (sem 401/403), resposta HTTP 401" in captured.out and "Confira LLM_API_KEY" in captured.err


def test_a_404_blames_the_request_not_the_key_and_names_json_schema_and_require_parameters(tmp_path, server, capsys):
    """O caso que o ping existe para pegar: o OpenRouter nao aceita o pedido como montado."""
    server.reply(404, error_json(404, "No endpoints found that can handle the requested parameters"))
    assert ping(tmp_path, server) == 6
    captured = capsys.readouterr()
    assert "[ok] autenticacao nao rejeitada (sem 401/403), resposta HTTP 404" in captured.out, "404 nao e recusa de autenticacao (e tambem nao a prova)"
    assert "[FALHA] pedido aceito como montado (json_schema + require_parameters" in captured.out
    assert "json_schema + require_parameters" in captured.err and "LLM_STRUCTURED_OUTPUT=none" in captured.err


def test_a_protocol_error_inside_a_200_is_still_a_protocol_error(tmp_path, server):
    server.reply(200, error_json(400, "bad request inside a 200"))
    assert ping(tmp_path, server) == 6 and len(server.requests) == 1


# --- falhas transitorias: UMA requisicao, sem retentativa, o usuario decide ------------------------------------------------------------------
@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_a_transient_failure_is_reported_without_retrying(tmp_path, server, capsys, status):
    server.reply(status, error_json(status, "indisponivel", **({"error_type": "rate_limit_exceeded"} if status == 429 else {})))
    assert ping(tmp_path, server) == 7
    assert len(server.requests) == 1, "o ping e UMA requisicao: nada de backoff nem retentativa"
    err = capsys.readouterr().err
    assert f"FALHA (http_{status})" in err and "causa provavel" in err


def test_the_unknown_checks_are_marked_unknown_not_failed_on_a_transient_failure(tmp_path, server, capsys):
    server.reply(503, error_json(503, "No available provider"))
    ping(tmp_path, server)
    out = capsys.readouterr().out
    assert "[?] pedido aceito como montado" in out and "[?] saida valida no schema local" in out, "nao se sabe: nao e para dizer que falhou"


def test_a_daily_429_exits_with_the_quota_code_and_marks_the_day(tmp_path, server):
    server.reply(429, error_json(429, "Rate limit exceeded: free-models-per-day", error_type="rate_limit_exceeded"))
    assert ping(tmp_path, server) == 4
    assert any(r["kind"] == "daily_limit_hit" for r in rows(tmp_path))


def test_a_timeout_is_reported_as_no_response(tmp_path, server, capsys):
    server.delay = 0.6
    assert ping(tmp_path, server, "--timeout", "0.2") == 7
    captured = capsys.readouterr()
    assert "[?] autenticacao nao rejeitada (sem 401/403), sem resposta HTTP" in captured.out and "FALHA (timeout)" in captured.err
    assert len(rows(tmp_path)) == 1, "a requisicao que estourou o prazo tambem conta"


def test_a_refused_connection_is_reported(tmp_path, capsys):
    assert llm_ping.main(["--base-url", "http://127.0.0.1:9", "--out-dir", str(tmp_path), "--timeout", "1"]) == 7
    assert "FALHA (connection)" in capsys.readouterr().err


# --- a resposta chegou, mas a saida e ruim ----------------------------------------------------------------------------------------------------
def test_an_invalid_output_fails_the_ping_but_shows_auth_and_request_ok(tmp_path, server, capsys):
    server.reply(200, chat_json("isto nao e JSON"))
    assert ping(tmp_path, server) == 1
    captured = capsys.readouterr()
    assert "[ok] autenticacao nao rejeitada" in captured.out and "[ok] pedido aceito como montado" in captured.out
    assert "[FALHA] saida valida no schema local" in captured.out
    assert "invalid_output" in captured.err and "nao impos o schema" in captured.err, "json_schema ligado: o modelo/provedor nao impos o schema"


def test_reasoning_that_eats_max_tokens_is_diagnosed(tmp_path, server, capsys):
    server.reply(200, chat_json("", finish_reason="length", reasoning_tokens=800, completion_tokens=800))
    assert ping(tmp_path, server) == 1
    assert "max_tokens" in capsys.readouterr().err


# --- protecoes continuam: o ping nao e uma porta lateral ------------------------------------------------------------------------------------
def test_the_pii_gate_still_runs_and_blocks_before_any_request(tmp_path, server, monkeypatch, capsys):
    leaky = SmokeMessage("vaza", "meu email é " + "a" + "@" + "b.com.br")
    monkeypatch.setattr(llm_ping, "MESSAGES", (leaky, *MESSAGES[1:]))
    assert ping(tmp_path, server) == 3
    assert server.requests == [] and "ABORTADO" in capsys.readouterr().err


def test_it_stops_before_sending_when_the_local_quota_is_gone(tmp_path, server, capsys):
    now = datetime.now(UTC).isoformat()
    (tmp_path / "quota.jsonl").write_text("".join(json.dumps({"ts": now, "kind": "request", "provider": "openrouter", "model": "m:free",
                                                              "outcome": "ok", "status": 200}) + "\n" for _ in range(50)))
    assert ping(tmp_path, server) == 4 and server.requests == []


def test_it_only_ever_sends_the_hand_written_message(tmp_path, server):
    ping(tmp_path, server)
    sent = posts(server)[0]["body"]["messages"][-1]["content"]
    assert MESSAGES[0].text in sent and MESSAGES[0].source == "hand-written"


def test_a_configuration_error_never_reaches_the_network(tmp_path, server, capsys, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nao_existe")
    assert ping(tmp_path, server) == 2 and server.requests == []


def test_the_ping_is_not_tied_to_the_real_env_file_under_pytest(tmp_path, server):
    """Os testes nunca leem o .env de quem os roda (o conftest neutraliza o load_env do smoke, que o ping reusa)."""
    import os
    assert os.environ["LLM_API_KEY"] == CANARY_KEY
