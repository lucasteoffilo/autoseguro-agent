"""Exportacao do log de uma execucao: o que sai, o que fica de fora e a varredura que recusa PII."""
from __future__ import annotations

import pytest

from autoseguro.logexport import ExportRefused, export_markdown, latest_trace, scan
from autoseguro.store import Store
from tests import synthetic_pii
from tests.fakes import err5xx
from tests.test_orchestrator import DATA, GREET, HAPPY, NEED_BASIC, START, Harness, ess

V = synthetic_pii.values()


def a_run_with_a_retry():
    h = Harness(err5xx(503, 0.2), ess())
    h.run(f"oi, meu cpf é {V['cpf']}", *HAPPY[1:])
    return h


def test_the_markdown_has_transcript_decisions_quote_attempts_slots_and_the_checks():
    h = a_run_with_a_retry()
    md = export_markdown(h.store, h.trace)
    assert md.startswith(f"# Log de execução — `{h.trace}`") and "`mock/mock-1`" in md
    for section in ("## Verificações (critérios E3 do PLAN)", "## Transcrição", "## Decisões do agente, mensagem a mensagem", "## Cotações e tentativas da `/quote`",
                    "## Estado final dos slots"):
        assert section in md
    assert "| 1 | 0.0 | 0.2 | 503 | http_5xx | retry |" in md and "| 2 | 0.37 | 0.1 | 200 | none | accept |" in md, "a falha seguida de retry aparece na tabela de tentativas"
    assert "Mensalidade: R$ 119,90" in md
    assert "| Existe cotação `ok` | sim: qte_0001 |" in md and "| Existe falha seguida de retry visível | sim: 1 tentativa(s)" in md
    assert "| Todo `R$` dito pelo agente existe numa cotação `ok` desta conversa | sim (2 valor(es)) |" in md
    assert "**não** — modo `mock`" in md, "o log de um mock nao se passa por log de LLM real"
    assert "sim (varredura do texto exportado: 0 achados)" in md
    assert "reply_source" in md and "intent" in md


def test_the_export_never_contains_what_the_lead_typed_raw():
    h = a_run_with_a_retry()
    md = export_markdown(h.store, h.trace)
    assert "[CPF]" in md and V["cpf"] not in md and V["cpf_digits"] not in md
    assert scan(md) == []


def test_a_run_without_a_retry_or_a_quote_says_so_in_the_checks():
    h = Harness()
    h.run(GREET, DATA)
    md = export_markdown(h.store, h.trace)
    assert "| Existe cotação `ok` | **não** |" in md and "| Existe falha seguida de retry visível | **não**" in md
    assert "_Nenhuma chamada à `/quote` nesta conversa._" in md


def test_the_precheck_confirmation_shows_up_as_its_own_quote_kind():
    from tests.fakes import refused
    h = Harness(refused("Veiculo com mais de 20 anos nao e aceito."))
    h.run(GREET, "é um fusca 1998, tenho 45 anos e moro no cep 01310-100")
    md = export_markdown(h.store, h.trace)
    assert " — precheck · refused · plano `essencial`" in md and "precheck_kind" in md and "refusal_kind" in md


def test_the_handoff_package_is_included_when_there_was_one():
    h = Harness()
    h.run(GREET, "prefiro falar com uma pessoa")
    md = export_markdown(h.store, h.trace)
    assert "## Pacote de handoff entregue ao humano" in md and '"reason": "HUMAN_REQUESTED"' in md


@pytest.mark.parametrize("leak", ["cpf_digits", "cpf", "email", "tel_plus", "home", "key_or"])
def test_the_export_is_refused_if_pii_got_into_the_database_by_any_route(leak):
    h = Harness()
    h.run(GREET)
    # simula um defeito a montante: texto cru gravado direto no banco
    h.store.add_message(h.trace, "msg_leak", role="lead", kind="text", text=f"dado {V[leak]}", ts=__import__("datetime").datetime.now(__import__("datetime").UTC), status="processed")
    with pytest.raises(ExportRefused) as exc:
        export_markdown(h.store, h.trace)
    assert V[leak] not in str(exc.value) and exc.value.kinds


def test_latest_trace_picks_the_most_recent_conversation_with_the_given_status(tmp_path):
    store = Store(tmp_path / "x.db")
    from autoseguro.store import utc_now
    for i, status in enumerate(("quoted", "handoff", "quoted", "open"), 1):
        store.open_conversation(f"trc_{i}", mode="mock", provider="m", model="m", now=utc_now())
        store.update_conversation(f"trc_{i}", utc_now(), status=status)
    assert latest_trace(store) == "trc_4" and latest_trace(store, status="quoted") == "trc_3" and latest_trace(store, status="refused") is None


def test_the_cli_writes_the_file_and_refuses_with_exit_3_on_pii(tmp_path, capsys):
    from tools import export_log
    db = tmp_path / "run.db"
    h = Harness(store=Store(db))
    h.run(*HAPPY[:1])
    out = tmp_path / "log.md"
    assert export_log.main(["--db", str(db), "--trace", h.trace, "--out", str(out)]) == 0 and out.read_text(encoding="utf-8").startswith("# Log de execução")
    assert export_log.main(["--db", str(db), "--trace", "trc_inexistente", "--out", str(out)]) == 2
    h.store.add_message(h.trace, "msg_leak", role="lead", kind="text", text=f"dado {V['email']}", ts=__import__("datetime").datetime.now(__import__("datetime").UTC), status="processed")
    out2 = tmp_path / "log2.md"
    assert export_log.main(["--db", str(db), "--trace", h.trace, "--out", str(out2)]) == 3 and not out2.exists()
    assert V["email"] not in capsys.readouterr().err
