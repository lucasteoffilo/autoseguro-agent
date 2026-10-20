"""A chave NUNCA aparece em log, erro, relatorio nem saida.

O servidor falso ECOA a chave de volta (em mensagem de erro, em pagina HTML, no corpo de um 200 e ate dentro do texto do "modelo") e o smoke
roda em cada modo de falha. Depois varremos TUDO que o processo escreveu: stdout, stderr, relatorio, log de cota e qualquer arquivo no diretorio.
Antes, o teste confirma que a chave FOI enviada (cabecalho Authorization), senao a ausencia na saida nao provaria nada.
"""
from __future__ import annotations

import json

import pytest

from autoseguro.llm.base import LLMResult
from autoseguro.llm.config import ConfigError, LLMConfig
from autoseguro.llm.openai_compat import OpenAICompatLLM
from autoseguro.llm.redact import REDACTED, redact
from tests.fake_servers import CANARY_KEY, GOOD, FakeServer, chat_json, error_json
from tools import llm_ping, smoke_llm

ECHO = f"Invalid credentials for key {CANARY_KEY}. Header Authorization: Bearer {CANARY_KEY}. x-api-key: {CANARY_KEY}"


def echo_in_reply() -> dict:
    return chat_json(json.dumps({**GOOD, "reply": f"Sua chave e {CANARY_KEY}"}))


SCENARIOS = {
    "401_com_eco": (401, error_json(401, ECHO), None),
    "402_com_eco": (402, error_json(402, ECHO), None),
    "500_com_eco": (500, error_json(500, ECHO), None),
    "429_por_minuto_com_eco": (429, error_json(429, "rate limit " + ECHO, error_type="rate_limit_exceeded"), {"Retry-After": "0"}),
    "429_diario_com_eco": (429, error_json(429, "free-models-per-day " + ECHO), None),
    "200_com_erro_e_eco": (200, error_json(502, ECHO), None),
    "pagina_html_com_chave": (502, f"<html><body>Bad gateway for {CANARY_KEY}</body></html>".encode(), None),
    "chave_dentro_da_resposta_do_modelo": (200, echo_in_reply(), None),
    "sucesso": (200, chat_json(json.dumps(GOOD)), None),
}


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", CANARY_KEY)
    s = FakeServer()
    yield s
    s.close()


def written_by_the_process(tmp_path, capsys) -> str:
    captured = capsys.readouterr()
    text = captured.out + "\n" + captured.err
    for f in tmp_path.rglob("*"):
        if f.is_file():
            text += "\n" + f.read_text(encoding="utf-8")
    return text


def run(tmp_path, server, *extra) -> int:
    return smoke_llm.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--rpm", "60000", "--no-remote-check", "--repeats", "1",
                           "--backoff-base-s", "0", "--max-retries", "1", "--timeout", "2", *extra])


# Codigo de saida esperado por cenario: erro de protocolo aborta na hora (6), servico instavel apos o backoff (7), limite diario (4); resposta do
# modelo, certa ou errada, e medicao (0 ou 1).
EXPECTED_EXIT = {"401_com_eco": {6}, "402_com_eco": {6}, "500_com_eco": {7}, "429_por_minuto_com_eco": {7}, "429_diario_com_eco": {4},
                 "200_com_erro_e_eco": {7}, "pagina_html_com_chave": {7}, "chave_dentro_da_resposta_do_modelo": {0, 1}, "sucesso": {0, 1}}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_key_appears_nowhere_the_process_writes(tmp_path, server, capsys, name):
    status, payload, headers = SCENARIOS[name]
    server.reply(status, payload, headers)
    code = run(tmp_path, server)
    assert code in EXPECTED_EXIT[name], f"{name}: saida inesperada {code}"
    assert server.requests, f"{name}: o smoke nem chegou ao servidor"
    assert server.requests[0]["headers"]["authorization"] == f"Bearer {CANARY_KEY}", "a chave PRECISA ter sido enviada, senao o teste nao prova nada"
    everything = written_by_the_process(tmp_path, capsys)
    assert CANARY_KEY not in everything, f"{name}: a chave vazou"
    assert "CANARY0123456789" not in everything, f"{name}: pedaco da chave vazou"


ECHOING = [n for n in sorted(SCENARIOS) if n not in ("sucesso", "chave_dentro_da_resposta_do_modelo")]


@pytest.mark.parametrize("name", ECHOING)
def test_an_error_that_echoes_the_key_is_redacted_inside_the_adapter_result(server, name):
    """O smoke nao imprime o `detail`, entao os testes de saida nao pegam um `redact` removido do adaptador. Este pega: o eco chegou, e saiu mascarado."""
    status, payload, headers = SCENARIOS[name]
    server.reply(status, payload, headers)
    adapter = OpenAICompatLLM("m:free", smoke_llm.load_fact_base(), base_url=server.url, api_key=CANARY_KEY, provider="openrouter", timeout_s=2)
    result = adapter.turn("oi")
    sent = server.requests[0]
    assert sent["headers"]["authorization"] == f"Bearer {CANARY_KEY}"
    assert result.error, name
    assert CANARY_KEY not in repr(result) and CANARY_KEY not in str(result.detail)
    if name == "pagina_html_com_chave":  # corpo que nao e JSON nunca vira detalhe: o adaptador nem le o texto
        assert result.detail is None
    else:
        assert result.detail and REDACTED in result.detail, f"{name}: o eco deveria ter sido visto e mascarado, nao ignorado"


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_the_ping_shows_neither_the_key_nor_its_prefix_in_any_failure_mode(tmp_path, server, capsys, name):
    status, payload, headers = SCENARIOS[name]
    server.reply(status, payload, headers)
    code = llm_ping.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--timeout", "2"])
    assert code in {0, 1, 4, 6, 7}, f"{name}: saida inesperada {code}"
    assert len(server.requests) == 1, "o ping e UMA requisicao"
    assert server.requests[0]["headers"]["authorization"] == f"Bearer {CANARY_KEY}", "a chave PRECISA ter sido enviada, senao o teste nao prova nada"
    everything = written_by_the_process(tmp_path, capsys)
    assert CANARY_KEY not in everything and "CANARY0123456789" not in everything, f"{name}: a chave vazou"
    assert "sk-or" not in everything, f"{name}: o prefixo da chave vazou"


def test_the_ping_redacts_an_unexpected_exception_that_carries_the_key(tmp_path, server, capsys, monkeypatch):
    def boom(self, user_message):
        raise RuntimeError(f"falha inesperada com a chave {CANARY_KEY} no meio")

    monkeypatch.setattr(OpenAICompatLLM, "turn", boom)
    assert llm_ping.main(["--base-url", server.url, "--out-dir", str(tmp_path)]) == 5
    everything = written_by_the_process(tmp_path, capsys)
    assert CANARY_KEY not in everything and "ERRO INESPERADO: RuntimeError" in everything and REDACTED in everything


def test_a_timeout_leaks_nothing(tmp_path, server, capsys):
    server.reply(200, chat_json(json.dumps(GOOD)))
    server.delay = 0.5
    smoke_llm.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--rpm", "60000", "--no-remote-check", "--repeats", "1", "--timeout", "0.2"])
    assert CANARY_KEY not in written_by_the_process(tmp_path, capsys)


def test_a_connection_error_leaks_nothing(tmp_path, capsys):
    code = smoke_llm.main(["--base-url", "http://127.0.0.1:9", "--out-dir", str(tmp_path), "--rpm", "60000", "--no-remote-check", "--repeats", "1",
                           "--timeout", "1"])
    assert code == 7 and CANARY_KEY not in written_by_the_process(tmp_path, capsys), "sem conexao: servico instavel, nao erro de protocolo"


def test_an_unexpected_exception_carrying_the_key_is_redacted_in_the_output(tmp_path, server, capsys, monkeypatch):
    def boom(self, user_message):
        raise RuntimeError(f"falha inesperada com a chave {CANARY_KEY} no meio")

    monkeypatch.setattr(OpenAICompatLLM, "turn", boom)
    assert run(tmp_path, server) == 5
    everything = written_by_the_process(tmp_path, capsys)
    assert CANARY_KEY not in everything and "ERRO INESPERADO: RuntimeError" in everything and REDACTED in everything


def test_a_configuration_error_never_prints_a_key(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARY_KEY)  # a chave do OpenRouter no provider errado
    assert smoke_llm.main(["--out-dir", str(tmp_path)]) == 2
    everything = written_by_the_process(tmp_path, capsys)
    assert CANARY_KEY not in everything and "CONFIGURACAO INVALIDA" in everything


def test_dry_run_needs_no_key_and_sends_nothing(tmp_path, capsys):
    # sem LLM_API_KEY no ambiente (o conftest limpa): o dry-run so imprime o plano
    assert smoke_llm.main(["--dry-run", "--out-dir", str(tmp_path)]) == 0
    assert "sk-or" not in written_by_the_process(tmp_path, capsys)
    (report,) = tmp_path.glob("smoke-*-dry.json")
    data = json.loads(report.read_text())
    assert data["dry_run"] is True and data["provider"] == "dry-run"
    assert not (tmp_path / "quota.jsonl").exists(), "o dry-run nao pode gastar nem registrar cota"


def test_the_key_is_not_in_the_repr_str_or_dataclass_fields_of_anything_that_holds_it(server):
    cfg = LLMConfig.from_env({"LLM_API_KEY": CANARY_KEY})
    adapter = OpenAICompatLLM(cfg.model, smoke_llm.load_fact_base(), base_url=server.url, api_key=CANARY_KEY, provider="openrouter")
    for obj in (cfg, adapter, LLMResult(None, "timeout", 1.0, None, None, detail=redact(ECHO, [CANARY_KEY]))):
        assert CANARY_KEY not in repr(obj) and CANARY_KEY not in str(obj), type(obj).__name__


def test_redact_removes_the_exact_secret_and_the_known_formats_even_when_the_process_did_not_know_them():
    assert CANARY_KEY not in redact(f"x {CANARY_KEY} y", [CANARY_KEY])
    unknown = "sk-or" + "-v1-OUTRACHAVEQUEOPROCESSONAOCONHECE"
    assert unknown not in redact(f"o provedor ecoou {unknown}", [CANARY_KEY]), "formato conhecido de chave e removido mesmo sem ser o valor configurado"
    assert "Bearer abcdefghijklmnop" not in redact("Authorization: Bearer abcdefghijklmnop")
    assert redact("sem segredo nenhum") == "sem segredo nenhum" and redact(None) == ""
    assert len(redact("a" * 1000, limit=50)) == 51


def test_the_secret_scanner_of_the_repo_knows_the_openrouter_key_format():
    from autoseguro.pii import find_pii
    assert find_pii(f"LLM_API_KEY={CANARY_KEY}") == ["chave_openrouter"]
    assert find_pii("LLM_API_KEY=") == [], ".env.example com a variavel vazia nao e achado"


def test_a_bad_config_message_has_no_key_even_when_the_key_is_the_cause():
    with pytest.raises(ConfigError) as e:
        LLMConfig.from_env({"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": CANARY_KEY})
    assert CANARY_KEY not in str(e.value) and CANARY_KEY not in repr(e.value)
