"""Terminal: o mesmo orquestrador com o MockLLM ou com o caminho do LLM real (aqui, um servidor local falso), a /quote por HTTP, tudo no SQLite."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from autoseguro import cli, templates
from autoseguro.cli import build_orchestrator, fetch_planos, main, make_llm_for
from autoseguro.facts import FactBase
from autoseguro.llm.guarded import GuardedLLM
from autoseguro.llm.throttle import ThrottledLLM
from autoseguro.store import SequentialIds, Store
from tests import synthetic_pii
from tests.fake_servers import FakeServer, chat_json
from tests.fakes import ok_body

ROOT = Path(__file__).resolve().parent.parent
PLANOS = json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8"))
BASE = FactBase.from_planos(PLANOS)
V = synthetic_pii.values()
SCRIPT = [f"oi! sou a Maria Silva, meu cpf é {V['cpf']}", "é um onix 2019, tenho 34 anos e moro no cep 30130-010", "só roubo e colisão", "01/11/2026"]


@pytest.fixture
def api():
    srv = FakeServer()
    srv.route("GET", "/planos", 200, PLANOS)
    srv.reply(200, ok_body("essencial", 119.9))
    yield srv
    srv.close()


def run(tmp_path, api, lines, *extra, stdin=None):
    script = tmp_path / "conversa.txt"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = io.StringIO()
    code = main(["--api", api.url, "--db", str(tmp_path / "x.db"), "--script", str(script), *extra], stdout=out)
    return code, out.getvalue()


def test_a_scripted_conversation_runs_end_to_end_over_http_and_lands_in_sqlite(tmp_path, api):
    code, out = run(tmp_path, api, SCRIPT)
    assert code == 0 and "LLM mock/mock-1" in out and f"{api.url}/planos" in out
    assert "agente> Aqui está a cotação do plano Essencial:" in out and "R$ 119,90" in out
    store = Store(tmp_path / "x.db")
    (trace,) = [r[0] for r in store._conn.execute("SELECT trace_id FROM conversations")]
    assert store.conversation(trace)["status"] == "quoted" and store.money_not_in_quotes(trace) == []
    assert [r["path"] for r in api.requests if r["method"] == "POST"] == ["/quote"] and api.requests[-1]["body"]["plano_id"] == "essencial"


def test_what_the_terminal_prints_for_the_agent_and_what_the_database_keeps_never_contain_the_raw_pii(tmp_path, api):
    _, out = run(tmp_path, api, SCRIPT)
    agent_lines = "\n".join(line for line in out.splitlines() if not line.startswith("lead>"))
    store = Store(tmp_path / "x.db")
    for raw in (V["cpf"], "Maria"):
        assert raw not in agent_lines and raw not in store.all_text()
    store.close()
    blob = b"".join(p.read_bytes() for p in tmp_path.glob("x.db*"))
    assert V["cpf"].encode() not in blob and b"Maria" not in blob


def test_the_script_skips_blank_lines_and_comments(tmp_path, api):
    _, out = run(tmp_path, api, ["# um comentario", "", "oi"])
    assert out.count("lead>") == 1 and "# um comentario" not in out


def test_interactive_mode_reads_stdin_and_supports_new_and_quit(tmp_path, api):
    out = io.StringIO()
    stdin = io.StringIO("oi\n/novo\nquero falar com uma pessoa\n/sair\nisto nao e lido\n")
    code = main(["--api", api.url, "--db", str(tmp_path / "x.db")], stdin=stdin, stdout=out)
    text = out.getvalue()
    assert code == 0 and text.count("[conversa trc_") == 2 and "isto nao e lido" not in text
    assert "[conversa encaminhada a um consultor; /novo abre outra]" in text
    store = Store(tmp_path / "x.db")
    assert sorted(r[0] for r in store._conn.execute("SELECT status FROM conversations")) == ["handoff", "open"]


def test_without_the_planos_endpoint_it_falls_back_to_the_vendored_copy_and_says_so():
    planos, source = fetch_planos("http://127.0.0.1:9", timeout_s=1.0)
    assert [p["id"] for p in planos["planos"]] == ["essencial", "completo", "premium"] and "plans.json" in source and "nao respondeu" in source


def test_build_orchestrator_with_the_mock_returns_a_guarded_llm_like_the_real_one(tmp_path, api):
    orc, store, info = build_orchestrator(llm_mode="mock", api_url=api.url, db_path=tmp_path / "y.db", ids=SequentialIds())
    assert isinstance(orc._llm, GuardedLLM) and info["llm"] == "mock/mock-1" and orc.start() == "trc_0001"


def test_the_real_llm_path_is_the_same_orchestrator_and_masks_before_the_provider_sees_a_byte(tmp_path, api):
    llm_srv = FakeServer()
    try:
        llm_srv.reply(200, chat_json(json.dumps({"slots": [], "intent": "greeting", "facts_used": [],
                                                 "reply": "Olá! Qual é o ano do modelo do seu carro?"})))
        env = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": llm_srv.url, "LLM_API_KEY": "chave-de-teste-123456", "LLM_MODEL": "fornecedor/modelo",
               "LLM_STRUCTURED_OUTPUT": "none"}
        orc, store, info = build_orchestrator(llm_mode="real", api_url=api.url, db_path=tmp_path / "z.db", env=env)
        assert isinstance(orc._llm, GuardedLLM) and isinstance(orc._llm.inner, ThrottledLLM) and info["llm"] == "openai_compat/fornecedor/modelo"
        trace = orc.start()
        r = orc.handle(trace, f"oi, sou a Maria Silva, meu cpf é {V['cpf']} e meu email é {V['email']}")
        assert r.terminal[0].text == f"{templates.GREETING} Qual é o ano do modelo do seu carro?" and r.status == "open"
        sent = json.dumps(llm_srv.requests[0]["body"], ensure_ascii=False)
        for raw in (V["cpf"], V["email"], "Maria"):
            assert raw not in sent and raw not in store.all_text()
        assert "[CPF]" in sent and "[EMAIL]" in sent and "[NOME]" in sent
        assert store.conversation(trace)["mode"] == "real" and store.conversation(trace)["llm_model"] == "fornecedor/modelo"
    finally:
        llm_srv.close()


def test_the_real_llm_without_a_key_stops_with_a_message_and_never_prints_a_secret(monkeypatch, capsys, tmp_path, api):
    for k in ("LLM_API_KEY", "OPENROUTER_API_KEY", "LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(cli, "load_env", lambda path: None)   # o teste nunca le o .env de verdade
    code = main(["--llm", "real", "--api", api.url, "--db", str(tmp_path / "x.db")], stdout=io.StringIO())
    err = capsys.readouterr().err
    assert code == 2 and "LLM_API_KEY ausente" in err and "sk-" not in err


def test_make_llm_for_the_mock_does_not_touch_the_environment():
    llm = make_llm_for("mock", BASE)
    assert isinstance(llm, GuardedLLM) and (llm.provider, llm.model) == ("mock", "mock-1")
