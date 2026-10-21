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


def test_export_all_writes_one_file_per_conversation_and_an_index_without_message_text(tmp_path):
    from tools import export_log
    db = tmp_path / "run.db"
    store = Store(db)
    h1 = Harness(err5xx(503, 0.2), ess(), store=store)
    h1.run(*HAPPY)
    from autoseguro.orchestrator import Orchestrator  # uma segunda conversa no MESMO banco
    t2 = h1.orc.start()
    h1.orc.handle(t2, "prefiro falar com uma pessoa")
    out = tmp_path / "expl"
    assert export_log.main(["--db", str(db), "--trace", "all", "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == sorted([f"{h1.trace}.md", f"{t2}.md", "index.md"])
    index = (out / "index.md").read_text(encoding="utf-8")
    assert f"| `{h1.trace}` | quoted |" in index and f"| `{t2}` | handoff | HUMAN_REQUESTED |" in index and "| 1/0/0 | 1 |" in index, "cotacao ok e 1 retry na primeira"
    assert "prefiro falar" not in index and "onix" not in index, "o indice so tem metadados"


def test_export_all_skips_only_the_conversation_that_the_scan_refuses_and_exits_3(tmp_path, capsys):
    from tools import export_log
    import datetime as dt
    db = tmp_path / "run.db"
    h = Harness(store=Store(db))
    h.run(GREET)
    bad = h.orc.start()
    h.store.add_message(bad, "msg_x", role="lead", kind="text", text=f"dado {V['email']}", ts=dt.datetime.now(dt.UTC), status="processed")
    out = tmp_path / "expl"
    assert export_log.main(["--db", str(db), "--trace", "all", "--out", str(out)]) == 3
    assert (out / f"{h.trace}.md").exists() and not (out / f"{bad}.md").exists() and (out / "index.md").exists()
    err = capsys.readouterr().err
    assert bad in err and V["email"] not in err


# --- de onde veio cada texto que o lead leu: modelo contra template, e por que o guardrail barrou -----------------------------------------------------------
from autoseguro.logexport import Origins, classify_reply, origins_of  # noqa: E402
from tests.hostile import HostileOnTurn  # noqa: E402
from tests.test_orchestrator import BASE, ScriptedLLM, reply_json  # noqa: E402


@pytest.mark.parametrize("meta,bucket,rules", [
    ({"reply_source": "llm"}, "llm", []),
    ({"reply_source": "template_fallback", "violations": ["R1_dinheiro", "R3_prazo_ou_contato"]}, "barrado", ["R1_dinheiro", "R3_prazo_ou_contato"]),
    ({"reply_source": "template_fallback", "violations": ["sem_saida"], "llm_error": "content_filter"}, "sem_saida", []),
    ({"reply_source": "template_question", "asked": ["veiculo_ano", "ask"]}, "trocado_orquestrador", []),
    ({"reply_source": "template_question", "asked": ["necessidade", "ask"]}, "trocado_produto", []),
    ({"reply_source": "template_question", "asked": ["idade", "confirm"]}, "trocado_produto", []),
    ({"reply_source": "template_echo", "asked": ["idade", "ask"], "echo": "Anotado: modelo 2019."}, "trocado_produto", []),
    ({"reply_source": "template_question", "asked": ["idade", "ask"], "echo": "Anotado: modelo 2019."}, "trocado_produto", []),
    # o desenho vem ANTES do guardrail: o texto do modelo seria trocado de qualquer jeito, entao a regra violada ali nao e "barrado"
    ({"reply_source": "template_fallback", "violations": ["R2_cobertura_sem_fato"], "asked": ["necessidade", "ask"]}, "trocado_produto", []),
    ({"reply_source": "template_fallback", "violations": ["R1_dinheiro"], "asked": ["idade", "confirm"]}, "trocado_produto", []),
    ({"reply_source": "template_fallback", "violations": ["R1_dinheiro"], "asked": ["veiculo_ano", "ask"]}, "barrado", ["R1_dinheiro"]),
    ({"reply_source": "template_fallback", "violations": ["sem_saida"], "asked": ["necessidade", "ask"]}, "sem_saida", []),
    ({"reply_source": "template_risk"}, "template", []), ({"reply_source": "template_quote"}, "template", []), ({"reply_source": "template_state"}, "template", []),
    ({}, "template", []),
])
def test_each_reply_source_lands_in_exactly_one_bucket(meta, bucket, rules):
    assert classify_reply(meta) == (bucket, rules)


def test_a_normal_conversation_splits_into_model_text_product_questions_and_templates():
    h = Harness(ess())
    h.run(*HAPPY)
    o = origins_of(h.store.messages(h.trace))
    assert dict(o.counts) == {"llm": 1, "trocado_produto": 2, "template": 1} and o.total == 4 and o.candidates == 1
    assert dict(o.sources) == {"template_quote": 1}
    md = export_markdown(h.store, h.trace)
    assert "## De onde veio cada texto que o lead leu" in md
    assert "| Texto do modelo, entregue | 1 | `llm` | — |" in md
    assert "**Fração do modelo:** 1 de 4 respostas ao lead (25%); 1 de 1 em que o texto do modelo poderia ter chegado (100%). **Barrados pelo guardrail:** 0 (0% das vezes" in md


def test_a_reply_the_guardrail_blocked_is_counted_with_the_rule_that_blocked_it_and_its_text_is_exported_for_judging():
    h = Harness(llm=HostileOnTurn(BASE, "Um consultor te liga amanhã com um desconto.", at=0))
    h.say(GREET)
    o = origins_of(h.store.messages(h.trace))
    assert o.counts["barrado"] == 1 and o.counts["llm"] == 0 and set(o.rules) >= {"R3_prazo_ou_contato", "R4_desconto_ou_condicao"}
    md = export_markdown(h.store, h.trace)
    assert "| Texto do modelo barrado pelo guardrail | 1 | `template_fallback` | R3_prazo_ou_contato ×1" in md
    assert "**Barrados pelo guardrail:** 1 (100% das vezes" in md
    assert "### Textos do modelo barrados pelo guardrail" in md and "Um consultor te liga amanhã com um desconto. Qual é o ano do modelo do seu carro?" in md.split("### Textos do modelo barrados")[1].split("## Transcrição")[0]
    assert "Um consultor te liga" not in h.agent[0]["text"], "o texto barrado NUNCA vai ao lead: o lead leu o template"


def test_the_blocked_text_is_recorded_masked_and_truncated_at_the_same_limit_as_the_error_detail():
    from autoseguro.llm import openai_compat, redact
    assert openai_compat.DETAIL_LIMIT is redact.DETAIL_LIMIT == 500, "um limite so, compartilhado"
    h = Harness(llm=HostileOnTurn(BASE, ("desconto " * 80).strip(), at=0))
    h.say(GREET)
    meta = h.meta(h.agent[0])
    assert meta["reply_source"] == "template_fallback" and len(meta["blocked_reply"]) == 501 and meta["blocked_reply"].endswith("…") and "blocked_reply_omitted" not in meta
    short = Harness(llm=HostileOnTurn(BASE, "Isso tem desconto.", at=0))
    short.say(GREET)
    assert short.meta(short.agent[0])["blocked_reply"] == "Isso tem desconto. Qual é o ano do modelo do seu carro?"


def test_an_invented_phone_in_the_blocked_reply_is_masked_and_the_export_neither_has_pii_nor_refuses_the_conversation():
    phone = V["tel_paren"]
    h = Harness(llm=HostileOnTurn(BASE, f"Um consultor te liga amanhã no {phone} com um desconto.", at=0))
    h.say(GREET)
    meta = h.meta(h.agent[0])
    assert "[TELEFONE]" in meta["blocked_reply"] and phone not in meta["blocked_reply"] and V["tel_core"] not in meta["blocked_reply"]
    md = export_markdown(h.store, h.trace)        # nao levanta ExportRefused
    assert "[TELEFONE]" in md and phone not in md and V["tel_core"] not in md and scan(md) == []
    assert phone not in h.store.all_text()


def test_if_pii_survives_the_masker_only_the_rule_is_recorded_and_the_export_still_works():
    from autoseguro.masker import Masked, Masker

    class LeakyMasker(Masker):                     # um mascarador que deixa tudo passar: o que sobra e PII de verdade
        def mask(self, text):
            return Masked(text, ())

    h = Harness(llm=HostileOnTurn(BASE, f"Um consultor te liga amanhã no {V['tel_plus']} com um desconto.", at=0), masker=LeakyMasker())
    h.say(GREET)
    meta = h.meta(h.agent[0])
    assert meta["blocked_reply_omitted"] == "pii" and "blocked_reply" not in meta and meta["violations"], "a regra continua gravada"
    assert V["tel_plus"] not in h.store.all_text() and V["tel_core"] not in h.store.all_text()
    md = export_markdown(h.store, h.trace)        # nao recusa
    assert "_texto omitido: pii_" in md and scan(md) == [] and "R3_prazo_ou_contato" in md


def test_the_export_says_the_blocked_text_only_exists_for_runs_after_the_commit_that_records_it():
    h = Harness()
    h.run(GREET)
    clean = export_markdown(h.store, h.trace)
    assert "Nenhum destes textos chegou ao lead" in clean and "O texto barrado só existe em execuções feitas depois do commit que o introduziu" in clean and "_Nenhum texto do modelo foi barrado pelo guardrail._" in clean
    # um banco de ANTES da gravacao: a mensagem barrada so tem a regra
    import datetime as dt
    old = Harness()
    old.store.add_message(old.trace, "msg_old", role="agent", kind="question", text="Qual é o ano do modelo do seu carro?", ts=dt.datetime.now(dt.UTC), status="sent",
                          meta={"reply_source": "template_fallback", "violations": ["R1_dinheiro"], "intent": "provide_info"})
    md = export_markdown(old.store, old.trace)
    assert "| 1 | R1_dinheiro | _não gravado: execução anterior ao commit que grava o texto barrado_ |" in md


def test_only_a_guardrail_block_records_a_text_not_a_provider_failure_nor_a_normal_reply():
    h = Harness(failures=["content_filter", "content_filter"])
    h.say(GREET)
    assert "blocked_reply" not in h.meta(h.agent[0]) and "blocked_reply_omitted" not in h.meta(h.agent[0])
    ok = Harness()
    ok.say(GREET)
    assert "blocked_reply" not in ok.meta(ok.agent[0])


def test_the_index_lists_the_blocked_texts_of_every_conversation(tmp_path):
    from tools import export_log
    db = tmp_path / "run.db"
    h = Harness(llm=HostileOnTurn(BASE, "Hoje mesmo você já fica coberto.", at=0), store=Store(db))
    h.say(GREET)
    out = tmp_path / "logs"
    assert export_log.main(["--db", str(db), "--trace", "all", "--out", str(out)]) == 0
    index = (out / "index.md").read_text(encoding="utf-8")
    assert "### Textos do modelo barrados pelo guardrail (todas as conversas)" in index and f"| `{h.trace}` 2 | " in index and "Hoje mesmo você já fica coberto." in index


def test_a_model_text_the_guardrail_would_block_is_not_a_block_when_the_pending_data_is_the_necessity_or_a_confirmation():
    """A causa dos 4 barrados da rodada do DEMO: o modelo redigindo a pergunta de necessidade (do produto, que o lead leu de qualquer jeito)."""
    bad = reply_json("Qual cobertura você quer: roubo, colisão, vidros ou carro reserva?",
                     slots=[("veiculo_ano", "2019", False), ("idade", "34", False), ("cep", "30130010", False)])
    h = Harness(llm=ScriptedLLM(reply_json("Anotado!"), bad))
    h.run(GREET, "é um onix 2019, tenho 34 anos e moro no cep 30130-010")
    o = origins_of(h.store.messages(h.trace))
    assert o.counts["barrado"] == 0 and o.counts["trocado_produto"] >= 1 and not o.rules
    assert "_Nenhum texto do modelo foi barrado pelo guardrail._" in export_markdown(h.store, h.trace)


def test_a_provider_filter_is_not_counted_as_a_guardrail_block_and_neither_is_the_orchestrators_swap():
    h = Harness(failures=["content_filter", "content_filter"])
    h.say(GREET)
    assert dict(origins_of(h.store.messages(h.trace)).counts) == {"sem_saida": 1}
    h2 = Harness(llm=ScriptedLLM(reply_json("Anotado!")))      # nao pergunta o dado pendente: o orquestrador usa a pergunta do produto
    h2.say(GREET)
    assert dict(origins_of(h2.store.messages(h2.trace)).counts) == {"trocado_orquestrador": 1}


def test_the_hold_message_is_not_a_reply():
    from tests.fakes import Step
    h = Harness(Step(3.0, 200, __import__("tests.fakes", fromlist=["ok_body"]).ok_body("essencial", 119.9)))
    h.run(*HAPPY)
    assert any(m["kind"] == "hold" for m in h.agent) and origins_of(h.store.messages(h.trace)).total == len([m for m in h.agent if m["kind"] != "hold"])


def test_the_index_has_the_fraction_per_conversation_and_the_total(tmp_path):
    from tools import export_log
    db = tmp_path / "run.db"
    h = Harness(ess(), store=Store(db))
    h.run(*HAPPY)
    t2 = h.orc.start()
    h.orc.handle(t2, GREET)
    t3 = h.orc.start()
    h.orc.handle(t3, "prefiro falar com uma pessoa")
    out = tmp_path / "logs"
    assert export_log.main(["--db", str(db), "--trace", "all", "--out", str(out)]) == 0
    index = (out / "index.md").read_text(encoding="utf-8")
    assert f"| `{h.trace}` | quoted |" in index and "| 1/4 | 0 |" in index and f"| `{t2}` | open |" in index and "| 1/1 | 0 |" in index and f"| `{t3}` | handoff | HUMAN_REQUESTED |" in index and "| 0/1 | 0 |" in index
    assert "## Total das 3 conversas: de onde veio cada texto que o lead leu" in index
    assert "**Fração do modelo:** 2 de 6 respostas ao lead (33%); 2 de 2 em que o texto do modelo poderia ter chegado (100%)." in index
    assert "prefiro falar" not in index


def test_the_cli_prints_the_total_fraction(tmp_path, capsys):
    from tools import export_log
    db = tmp_path / "run.db"
    h = Harness(llm=HostileOnTurn(BASE, "Hoje mesmo você já fica coberto.", at=0), store=Store(db))
    h.say(GREET)
    assert export_log.main(["--db", str(db), "--trace", "all", "--out", str(tmp_path / "logs")]) == 0
    assert "texto do modelo: 0 de 1 respostas ao lead; barrados pelo guardrail: 1" in capsys.readouterr().out
