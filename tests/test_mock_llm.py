"""MockLLM: deterministico, passa pela mesma validacao local e pelo mesmo GuardedLLM do modelo real, e nunca e hostil sem querer."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from autoseguro.facts import FactBase
from autoseguro.llm.guarded import GuardedLLM, UnsafePayload
from autoseguro.llm.prompt import build_user_message
from autoseguro.mock_llm import MockLLM
from tests import synthetic_pii

ROOT = Path(__file__).resolve().parent.parent
_SAMPLES = synthetic_pii.values()
BASE = FactBase.from_planos(json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8")))
TODAY = date(2026, 10, 21)  # quarta-feira


def ask(llm, text, *, known=None, asked=None):
    msg = build_user_message(today=TODAY, known_slots=known or {}, asked_slot=asked, history=(), message=text)
    return GuardedLLM(llm, BASE).turn(msg, lead_texts=[text])


def slots(g):
    return [(s.slot, s.value, s.uncertain) for s in g.output.slots]


def test_it_is_deterministic():
    runs = [ask(MockLLM(BASE), "é um onix 2019, tenho 34 anos e moro no cep 30130-010", asked="veiculo_ano").output for _ in range(3)]
    assert runs[0] == runs[1] == runs[2]


def test_it_goes_through_the_same_validation_and_guard_as_the_real_models():
    g = ask(MockLLM(BASE), "oi")
    assert g.result.error is None and g.result.usage is not None and g.result.served_model == "mock-1" and g.reply_ok and g.reply_source == "llm"


def test_a_greeting_gets_a_greeting_and_the_first_question():
    g = ask(MockLLM(BASE), "oii, vi o anuncio de vcs, queria saber quanto fica o seguro")
    assert g.output.intent == "greeting" and slots(g) == [] and g.output.reply.endswith("Qual é o ano do modelo do seu carro?")


def test_it_extracts_only_what_the_lead_wrote_and_asks_for_the_next_missing_slot():
    g = ask(MockLLM(BASE), "é um onix 2019, tenho 34 anos e moro no cep 30130-010", asked="veiculo_ano")
    assert slots(g) == [("veiculo_ano", "2019", False), ("idade", "34", False), ("cep", "30130010", False)]
    assert g.output.intent == "provide_info" and "necessidade" not in str(slots(g))
    assert g.output.facts_used == ("necessidades",) and "assistência 24h" in g.output.reply, "pergunta de necessidade cita o fato"
    assert g.reply_ok


def test_it_marks_doubt_and_two_values_as_uncertain_and_never_calculates_an_age():
    mock = MockLLM(BASE)
    assert slots(ask(mock, "uns 35, quase 36 kkk", asked="idade"))[0][2] is True
    assert slots(ask(mock, "o carro é 2015 mas o modelo é 2016", asked="veiculo_ano")) == [("veiculo_ano", "2016", True)]
    assert slots(ask(mock, "nasci em 1990", asked="idade")) == []
    assert slots(ask(mock, "ah acho q é 04538-132 mas n tenho certeza", asked="cep")) == [("cep", "04538132", True)]


@pytest.mark.parametrize("text,intent", [
    ("quero falar com uma pessoa de verdade", "wants_human"), ("bati o carro ontem, como faço?", "claim"), ("quero cancelar", "cancel"),
    ("isso é um absurdo, péssimo atendimento", "complaint"), ("quero fechar", "ready_to_close"), ("nossa tá muito caro", "price_objection"),
    ("e se roubarem meu carro amanhã, vocês cobrem?", "ask_coverage_question"), ("qual a franquia?", "ask_coverage_question"),
    ("ops, errei a idade, na verdade tenho 53", "correction"), ("kkkk", "unclear"), ("vocês vendem moto?", "question_not_in_facts"),
])
def test_intents(text, intent):
    assert ask(MockLLM(BASE), text, known={"veiculo_ano": "2015"}).output.intent == intent


def test_the_necessity_answer_is_not_mistaken_for_a_coverage_question():
    g = ask(MockLLM(BASE), "só roubo e colisão", asked="necessidade", known={"veiculo_ano": "2015", "idade": "42", "cep": "01310100"})
    assert g.output.intent == "provide_info" and slots(g) == [("necessidade", "basica", False)]
    g = ask(MockLLM(BASE), "e se roubarem meu carro?", asked="necessidade")
    assert g.output.intent == "ask_coverage_question" and slots(g) == []


def test_dates_literal_and_relative():
    mock = MockLLM(BASE)
    assert slots(ask(mock, "dia 01/11/2026", asked="data_inicio")) == [("data_inicio", "2026-11-01", False)]
    assert slots(ask(mock, "segunda que vem", asked="data_inicio")) == [("data_inicio", "2026-10-26", True)]
    assert slots(ask(mock, "amanhã", asked="data_inicio")) == [("data_inicio", "2026-10-22", True)]


def test_its_replies_pass_the_strict_guardrail_for_every_missing_slot():
    for known in ({}, {"veiculo_ano": "2015"}, {"veiculo_ano": "2015", "idade": "42"}, {"veiculo_ano": "2015", "idade": "42", "cep": "01310100"},
                  {"veiculo_ano": "2015", "idade": "42", "cep": "01310100", "necessidade": "basica"}):
        g = ask(MockLLM(BASE), "oi", known=known)
        assert g.reply_ok, (known, g.violations)


@pytest.mark.parametrize("failure,error", [("content_filter", "content_filter"), ("timeout", "timeout"), ("invalid_output", "invalid_output:JSONDecodeError"), ("http_503", "http_503")])
def test_scripted_failures_are_consumed_one_per_call_and_then_it_recovers(failure, error):
    mock = MockLLM(BASE, failures=[failure, None])
    first, second = ask(mock, "oi"), ask(mock, "oi")
    assert first.result.error == error and first.output is None
    assert second.result.error is None and second.output is not None


def test_it_records_every_prompt_it_received():
    mock = MockLLM(BASE)
    ask(mock, "primeira")
    ask(mock, "segunda")
    assert len(mock.calls) == 2 and "primeira" in mock.calls[0] and "segunda" in mock.calls[1]


def test_unknown_failure_names_are_a_test_bug_not_silence():
    with pytest.raises(ValueError):
        ask(MockLLM(BASE, failures=["inventada"]), "oi")


def test_the_guarded_wrapper_still_blocks_pii_before_the_mock_sees_it():
    mock = MockLLM(BASE)
    with pytest.raises(UnsafePayload):
        ask(mock, "meu cpf é " + _SAMPLES["cpf"])
    assert mock.calls == []
