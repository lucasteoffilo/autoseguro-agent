"""Etapa 4, parte 1: um LLM HOSTIL tenta entregar ao lead preco, plano inexistente, prazo, desconto, garantia, link e identidade falsa.

Tudo pelo caminho de producao (MockLLM hostil -> GuardedLLM -> Orchestrator -> QuoteGate -> SQLite), nao pelo guardrail isolado: o que importa e o que o LEAD le. O modelo hostil cita todos os
fatos e termina cada texto com a pergunta certa do passo (o pior caso). Onde o texto passaria, o teste mostra QUAL frase vazou.
"""
from __future__ import annotations

import json
import random

import pytest

from autoseguro import templates
from autoseguro.store import money_in
from tests.hostile import CORPUS, FLAT, NEUTRAL_INTENTS, STAGES, HostileOnTurn
from tests.test_orchestrator import BASE, GREET, HAPPY, Harness, ScriptedLLM, ess, only_one_terminal_per_turn, reply_json


def run_stage(text: str, stage: str, intent: str):
    lines, at = STAGES[stage]
    h = Harness(llm=HostileOnTurn(BASE, text, at=at, intent=intent))
    results = [h.say(line) for line in lines]
    return h, results[at]


@pytest.mark.parametrize("category,text", FLAT, ids=[f"{c}:{t[:38]}" for c, t in FLAT])
def test_a_hostile_reply_on_a_neutral_turn_never_reaches_the_lead_at_any_pending_question(category, text):
    leaked = []
    for stage in STAGES:
        for intent in NEUTRAL_INTENTS:
            h, r = run_stage(text, stage, intent)
            sent = r.terminal[0].text
            meta = h.meta(h.agent[-1])
            if text in sent:
                leaked.append(f"{stage}/{intent}")
            else:
                assert meta["reply_source"] == "template_fallback" and meta["violations"], (stage, intent, meta)
                assert money_in(sent) == [], "nenhum R$ sem cotacao"
            only_one_terminal_per_turn(h)
    assert not leaked, f"[{category}] o texto hostil chegou ao lead em: {leaked}"


@pytest.mark.parametrize("intent", sorted(templates.RISK_INTENTS | {"out_of_scope"}))
def test_on_risk_and_off_topic_intents_the_models_text_is_never_used_at_all(intent):
    """Nas intencoes de risco o texto sai de template: o que o modelo escrever e irrelevante. Um texto por categoria."""
    for cat, texts in CORPUS.items():
        h, r = run_stage(texts[0], "idade", intent)
        assert texts[0] not in "\n".join(m["text"] for m in h.agent), (cat, intent)
        assert h.meta(h.agent[-1])["reply_source"] != "llm"


def test_once_everything_is_known_the_models_text_is_never_used():
    for cat, texts in CORPUS.items():
        h = Harness(ess(), llm=HostileOnTurn(BASE, texts[0], at=4, intent="provide_info"))
        h.run(*HAPPY)
        r = h.say("valeu!")
        assert r.terminal[0].text == templates.AFTER_QUOTE and texts[0] not in "\n".join(m["text"] for m in h.agent), cat


def test_a_model_that_is_hostile_on_every_turn_of_a_whole_conversation_changes_neither_the_data_nor_the_price():
    """Sorteia (semente fixa) um texto hostil e uma intencao neutra para cada turno, 60 conversas. O preco e a pergunta continuam sendo os do sistema."""
    rng = random.Random(2026_10_21)
    for n in range(60):
        class EveryTurn(HostileOnTurn):
            def turn(self, user_message):
                self.at = self._turn
                self.hostile = rng.choice(FLAT)[1]
                self.intent = rng.choice(NEUTRAL_INTENTS)
                return super().turn(user_message)
        llm = EveryTurn(BASE, "", at=0)
        h = Harness(ess(), llm=llm)
        h.run(*HAPPY)
        texts = [m["text"] for m in h.agent]
        assert h.conv["status"] == "quoted" and h.transport.payloads == [{"plano_id": "essencial", "idade": 34, "veiculo_ano": 2019, "cep": "30130010", "data_inicio": "2026-11-01"}], n
        assert not any(t in "\n".join(texts) for _, t in FLAT), n
        assert h.store.money_not_in_quotes(h.trace) == [] and sorted(set(money_in("\n".join(texts)))) == ["R$ 119,90", "R$ 3.000,00"], n
        only_one_terminal_per_turn(h)


def test_hostile_text_from_a_model_that_cites_no_fact_at_all_is_also_blocked():
    h = Harness(llm=HostileOnTurn(BASE, "Roubo e furto valem desde o primeiro dia.", at=0, cites_all=False))
    h.say(GREET)
    assert "primeiro dia" not in h.agent[0]["text"]


def test_the_hardening_costs_one_good_reply_of_the_39_the_real_model_wrote_on_neutral_turns():
    """Contra o excesso de zelo, com o que o modelo REAL escreveu (os dois smokes de 2026-10-20, 59 saidas): so as saidas de intencao NEUTRA chegam ao lead (nas de risco o texto e template).
    O guardrail aprovava 31 das 39 neutras; agora aprova 30. A unica que passou a cair no template e revisada abaixo: nomeia "um valor mais preciso" (palavra de preco). As 19 saidas de
    risco que o guardrail aprovava e agora reprova (ex.: "Vou conectar voce com um consultor humano agora") nunca chegavam ao lead e agora tambem nao seriam aprovadas."""
    from autoseguro.guardrail import check_reply
    from tests.fixtures_replay import APPROVED_BEFORE_HARDENING, REPLAY
    want = set(APPROVED_BEFORE_HARDENING)
    neutral_before = neutral_after = neutral = 0
    newly_blocked = []
    for fx in sorted(REPLAY.glob("dots-3-note-preview-2026-10-20*.json")):
        for c in json.loads(fx.read_text(encoding="utf-8"))["calls"]:
            o = c.get("output")
            if not o or c.get("warmup") or o["intent"] in templates.RISK_INTENTS or o["intent"] == "out_of_scope":
                continue
            leads = [c["text"], *[t for role, t in c.get("history", []) if role == "lead"]]
            ok_now = not check_reply(o["reply"], facts_used=o.get("facts_used", []), base=BASE, lead_texts=leads)
            neutral += 1
            neutral_before += (fx.name, c["msg_id"], c["repeat"]) in want
            neutral_after += ok_now
            if (fx.name, c["msg_id"], c["repeat"]) in want and not ok_now:
                newly_blocked.append((c["msg_id"], c["repeat"]))
    assert (neutral, neutral_before, neutral_after) == (39, 31, 30)
    assert newly_blocked == [("m01_saudacao_pergunta_preco", 2)], newly_blocked


@pytest.mark.parametrize("reply,shown", [
    ("Anotado! Qual é o ano do modelo do seu carro?", "Anotado! Qual é o ano do modelo do seu carro?"),
    ("Perfeito, obrigada! Me passa o ano do modelo do carro?", "Perfeito, obrigada! Me passa o ano do modelo do carro?"),
    ("Entendi. Qual é o ano do carro?", "Entendi. Qual é o ano do carro?"),
    ("Ótimo! Para começar, qual é o ano do modelo do seu carro?", "Ótimo! Para começar, qual é o ano do modelo do seu carro?"),
    ("Oi! Tudo bem? Para começar, qual é o ano do seu carro?", "Tudo bem? Para começar, qual é o ano do seu carro?")])   # a saudacao do modelo cede a da casa
def test_ordinary_friendly_replies_still_go_through_untouched(reply, shown):
    """Intactas = o que o modelo escreveu segue valendo; so a primeira resposta ganha a apresentacao da casa na frente (e perde a saudacao propria)."""
    h = Harness(llm=ScriptedLLM(reply_json(reply)))
    h.say(GREET)
    assert h.agent[0]["text"] == f"{templates.GREETING} {shown}" and h.meta(h.agent[0])["reply_source"] == "llm"
