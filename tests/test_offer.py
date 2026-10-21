"""A oferta de plano alternativo ("Posso te mostrar outro plano?") e respondida pelo LEXICO, nao pelo rotulo do modelo.

Rodada de 2026-10-21 com o modelo real: "sim, pode mostrar" veio rotulado `price_objection` e a oferta virou handoff PRICE_OBJECTION (tests/fixtures/real_run). O mock rotula
`provide_info` e escondia o defeito. Aqui o rotulo gravado do modelo real e reproduzido, alem do mock."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoseguro import templates
from tests.test_orchestrator import BASE, DATA, GREET, NEED_FULL, START, Harness, comp, ess, only_one_terminal_per_turn

REAL = json.loads((Path(__file__).parent / "fixtures" / "real_run" / "demo-2026-10-21.json").read_text(encoding="utf-8"))
REAL_LABEL = {t["lead"]: t["intent"] for t in REAL["turns"]}


class RelabelLLM:
    """O MockLLM de sempre, mas com a INTENCAO que o modelo real gravou para aquela mensagem do lead (ou a do `override`)."""

    provider, model, system_prompt = "relabel", "relabel-1", "sistema"

    def __init__(self, labels):
        from autoseguro.mock_llm import MockLLM
        self.inner, self.labels, self.calls = MockLLM(BASE), labels, []

    def turn(self, user_message):
        res = self.inner.turn(user_message)
        self.calls.append(user_message)
        text = user_message.split("mensagem do lead:\n", 1)[-1]
        if res.output is None or text not in self.labels:
            return res
        from autoseguro.llm.base import result_from_text
        out = res.output
        payload = {"slots": [{"slot": s.slot, "value": s.value, "uncertain": s.uncertain} for s in out.slots], "intent": self.labels[text], "facts_used": list(out.facts_used), "reply": out.reply}
        return result_from_text(json.dumps(payload, ensure_ascii=False), BASE.ids(), latency_s=0.05, usage=None, stop_reason="stop", http_status=200)


def offered(*steps, llm=None, extra=()):
    h = Harness(*steps, llm=llm)
    h.run(GREET, DATA, NEED_FULL, START)
    r = h.say("achei caro")
    assert r.terminal[0].text == templates.PRICE_OFFER and h.conv["status"] == "quoted"
    return h


def test_the_real_models_label_for_a_yes_does_not_turn_the_offer_into_a_handoff():
    """O rotulo REAL gravado: `price_objection` para "sim, pode mostrar"."""
    assert REAL_LABEL["sim, pode mostrar"] == "price_objection"
    h = offered(comp(), ess(), llm=RelabelLLM(REAL_LABEL))
    r = h.say("sim, pode mostrar")
    assert r.terminal[0].kind == "quote" and "outra opção para você comparar" in r.terminal[0].text and "R$ 119,90" in r.terminal[0].text
    assert [q["kind"] for q in h.store.quotes(h.trace)] == ["quote", "alternative"] and h.conv["status"] == "quoted" and h.conv["handoff_reason"] is None
    assert h.store.money_not_in_quotes(h.trace) == []


def test_the_same_yes_with_the_mock_label_also_quotes_the_alternative():
    h = offered(comp(), ess())
    r = h.say("sim, pode mostrar")
    assert r.terminal[0].kind == "quote" and [q["kind"] for q in h.store.quotes(h.trace)] == ["quote", "alternative"]


@pytest.mark.parametrize("label", ["price_objection", "provide_info", "unclear", "correction", "greeting", "out_of_scope", "question_not_in_facts"])
@pytest.mark.parametrize("yes", ["sim", "sim, pode mostrar", "isso", "aham", "sim!"])
def test_whatever_the_models_label_a_yes_quotes_the_alternative(label, yes):
    h = offered(comp(), ess(), llm=RelabelLLM({yes: label}))
    h.say(yes)
    assert [q["kind"] for q in h.store.quotes(h.trace)] == ["quote", "alternative"] and h.conv["handoff_reason"] is None


@pytest.mark.parametrize("label", ["price_objection", "provide_info", "unclear"])
@pytest.mark.parametrize("no", ["não", "não, obrigado", "negativo", "n"])
def test_whatever_the_models_label_a_no_is_a_price_objection_handoff(label, no):
    h = offered(comp(), llm=RelabelLLM({no: label}))
    r = h.say(no)
    assert r.terminal[0].kind == "handoff" and h.conv["handoff_reason"] == "PRICE_OBJECTION" and h.transport.calls == 1 and h.conv["handoff_detail"] is None
    assert "desconto" not in r.terminal[0].text.lower()


def test_neither_yes_nor_no_repeats_the_yes_no_question_once_by_template_and_then_accepts_a_yes():
    h = offered(comp(), ess(), llm=RelabelLLM({"talvez": "price_objection"}))
    r = h.say("talvez")
    assert r.terminal[0].text == templates.OFFER_AGAIN and r.terminal[0].kind == "question" and h.conv["status"] == "quoted" and h.meta(h.agent[-1])["reply_source"] == "template_risk"
    assert h.transport.calls == 1
    r = h.say("sim")
    assert r.terminal[0].kind == "quote" and [q["kind"] for q in h.store.quotes(h.trace)] == ["quote", "alternative"]
    only_one_terminal_per_turn(h)


def test_the_second_ambiguity_goes_to_a_human_as_price_objection_with_the_reason_recorded():
    h = offered(comp())
    h.say("talvez")
    r = h.say("sei lá")
    assert r.terminal[0].kind == "handoff" and h.conv["handoff_reason"] == "PRICE_OBJECTION" and h.conv["handoff_detail"] == "oferta_sem_resposta" and h.transport.calls == 1
    assert "desconto" not in r.terminal[0].text.lower() and "R$" not in r.terminal[0].text.replace("R$ 209,90", "")
    assert json.loads(h.conv["handoff_package"])["reason"] == "PRICE_OBJECTION"


def test_an_ambiguity_followed_by_a_no_is_a_no():
    h = offered(comp())
    h.say("hmm")
    h.say("não")
    assert h.conv["handoff_reason"] == "PRICE_OBJECTION" and h.conv["handoff_detail"] is None


@pytest.mark.parametrize("message,reason", [("prefiro falar com uma pessoa", "HUMAN_REQUESTED"), ("quero cancelar", "CANCELLATION"), ("isso é um absurdo, quero reclamar", "COMPLAINT")])
def test_the_intents_that_are_a_handoff_by_themselves_still_win_over_a_pending_offer(message, reason):
    h = offered(comp())
    h.say(message)
    assert h.conv["handoff_reason"] == reason and h.transport.calls == 1


def test_a_correction_with_a_pending_offer_requotes_instead_of_asking_again():
    h = offered(comp(), comp())
    h.say("na verdade tenho 40 anos")
    assert h.transport.calls == 2 and [q["kind"] for q in h.store.quotes(h.trace)] == ["quote", "quote"] and h.conv["status"] == "quoted"


def test_an_accepted_offer_leaves_no_pending_offer_so_a_later_yes_does_not_quote_again():
    h = offered(comp(), ess())
    h.say("sim")
    calls = h.transport.calls
    h.say("sim")
    assert h.transport.calls == calls


def test_a_refusal_of_the_alternative_by_the_api_hands_off_without_showing_anything():
    from tests.fakes import refused
    h = offered(comp(), refused("Regra nova do servico: perfil bloqueado."))
    r = h.say("sim")
    assert r.terminal[0].kind == "handoff" and h.conv["handoff_reason"] == "PRICE_OBJECTION"
