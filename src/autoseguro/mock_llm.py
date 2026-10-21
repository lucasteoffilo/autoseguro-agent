"""MockLLM: o LLM de mentira DETERMINISTICO. Mesma interface (`LLMClient`), mesma validacao local (`result_from_text`), mesmo `GuardedLLM` por cima:
o orquestrador nao sabe se fala com ele ou com o OpenRouter. E o caminho reproduzivel da demo e dos testes (README, D4).

Imita um modelo de boa-fe, nao um adversario: extrai so o que o lead escreveu (com o mesmo leitor deterministico da ancoragem), marca incerteza quando ha
hesitacao ou dois valores, NAO calcula idade a partir do ano de nascimento, e escreve respostas curtas e sem numeros. Quem quiser um modelo hostil usa
`HostileLLM` dos testes; quem quiser falhas usa `failures=`: uma lista consumida chamada a chamada (None = normal, "content_filter", "timeout",
"invalid_output", "http_503", "http_401").

Guarda `calls` (os prompts que recebeu): e como os testes provam que nenhum texto cru chegou ao LLM.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from datetime import date, timedelta

from . import questions
from .anchoring import implied_tier, read_text
from .facts import FactBase, strip_accents
from .llm.base import LLMResult, Usage, result_from_text
from .llm.prompt import build_system_prompt
from .llm.schema import SLOT_NAMES

_ORDER = ("veiculo_ano", "idade", "cep", "necessidade", "data_inicio")
_ASK = {"veiculo_ano": "Qual é o ano do modelo do seu carro?", "idade": "Qual é a sua idade?", "cep": "Qual é o CEP de onde o carro dorme?",
        "data_inicio": "Em que dia você quer que o seguro comece a valer?"}
_WEEKDAYS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}

_INTENT_RULES = (
    ("wants_human", re.compile(r"\b(pessoa|humano|atendente|consultor|alguem de verdade)\b")),
    ("claim", re.compile(r"\b(bati|batida|acidente|sinistro|roubaram|furtaram|roubou|furtou|colidi)\b")),
    ("cancel", re.compile(r"\b(cancelar|cancelamento)\b")),
    ("complaint", re.compile(r"\b(reclamacao|reclamar|absurdo|pessimo|horrivel|vergonha)\b")),
    ("ready_to_close", re.compile(r"\b(fechar|contratar|vamos fechar|pode emitir|quero esse|fechado)\b")),
    ("price_objection", re.compile(r"\b(caro|cara|mais barato|desconto|muito alto|muito salgado)\b")),
    ("out_of_scope", re.compile(r"\b(seguro (de )?(vida|casa|residencial|viagem|celular|saude|empresarial)|plano de saude|emprestimo|financiamento|"
                               r"previsao do tempo|receita de)\b")),
)
_COVERAGE_WORDS = re.compile(r"\b(cobre|cobrem|cobertura|coberturas|carencia|franquia|plano|planos|vidro|vidros|terceiros|assistencia|reserva|proporcional|"
                             r"roub\w*|furt\w*|colis\w*)\b")
_GREETING = re.compile(r"^\s*(oi+|ola|bom dia|boa tarde|boa noite|e ai|opa)\b")
_CORRECTION = re.compile(r"\b(errei|na verdade|corrigindo|corrigir|ops)\b")


def _parse_prompt(user_message: str) -> dict:
    today = re.search(r"hoje: (\d{4}-\d{2}-\d{2})", user_message)
    known = re.search(r"dados já coletados: (.*)", user_message)
    asked = re.search(r"pergunta pendente: (\w+)", user_message)
    text = user_message.split("mensagem do lead:\n", 1)[-1]
    known_slots = {}
    if known and known.group(1).strip() != "nenhum":
        for part in known.group(1).split(", "):
            k, _, v = part.partition("=")
            known_slots[k.strip()] = v.strip()
    return {"today": date.fromisoformat(today.group(1)) if today else date(2026, 10, 21), "known": known_slots,
            "asked": None if not asked or asked.group(1) == "nenhuma" else asked.group(1), "text": text}


def _relative_date(plain: str, today: date) -> date | None:
    if "depois de amanha" in plain:
        return today + timedelta(days=2)
    if "amanha" in plain:
        return today + timedelta(days=1)
    if re.search(r"\bhoje\b", plain):
        return today
    for name, wd in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", plain):
            return today + timedelta(days=(wd - today.weekday()) % 7 or 7)
    m = re.search(r"\bdia (\d{1,2})\b", plain)
    if m and 1 <= int(m.group(1)) <= 28:
        d = date(today.year, today.month, int(m.group(1)))
        return d if d >= today else date(today.year + (today.month == 12), today.month % 12 + 1, int(m.group(1)))
    return None


class MockLLM:
    provider, model = "mock", "mock-1"

    def __init__(self, fact_base: FactBase, *, failures: Sequence[str | None] = ()) -> None:
        self._facts = fact_base
        self.system_prompt = build_system_prompt(fact_base, format_hint=True)
        self.failures = list(failures)
        self.calls: list[str] = []

    def __repr__(self) -> str:
        return "MockLLM()"

    # --- a interface ----------------------------------------------------------------------------------------------------------------------------
    def turn(self, user_message: str) -> LLMResult:
        self.calls.append(user_message)
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None:
            return self._failure(failure)
        text = json.dumps(self._answer(_parse_prompt(user_message)), ensure_ascii=False)
        return result_from_text(text, self._facts.ids(), latency_s=0.05, usage=Usage(1300, 60), stop_reason="stop", http_status=200, served_model=self.model)

    @staticmethod
    def _failure(kind: str) -> LLMResult:
        if kind == "content_filter":
            return LLMResult(None, "content_filter", 0.05, Usage(1300, 60), "content_filter", http_status=200)
        if kind == "timeout":
            return LLMResult(None, "timeout", 6.0, None, None)
        if kind == "invalid_output":
            return result_from_text("isto não é JSON", (), latency_s=0.05, usage=Usage(1300, 20), stop_reason="stop", http_status=200)
        if kind.startswith("http_"):
            status = int(kind.split("_")[1])
            return LLMResult(None, kind, 0.05, None, None, http_status=status, detail="falha simulada")
        raise ValueError(f"falha desconhecida: {kind}")

    # --- o "modelo" -----------------------------------------------------------------------------------------------------------------------------
    def _answer(self, p: dict) -> dict:
        text, asked, today = p["text"], p["asked"], p["today"]
        reading = read_text(text, asked)
        plain = strip_accents(text).lower()
        slots: list[dict] = []

        def put(slot: str, value: str, uncertain: bool) -> None:
            slots.append({"slot": slot, "value": value, "uncertain": uncertain})

        for slot, cands in (("veiculo_ano", reading.years), ("idade", reading.ages), ("cep", reading.ceps)):
            values = list(dict.fromkeys(c.value for c in cands))
            if len(values) == 1:
                put(slot, values[0], reading.hedge)
            elif len(values) > 1:  # dois valores: um so, marcado como incerto (nunca escolhe em silencio)
                labeled = [c.value for c in cands if c.label == "modelo"]
                put(slot, labeled[0] if labeled else values[-1], True)
        tier = implied_tier(reading.plain)
        if asked == "necessidade" and tier and "?" not in text:
            put("necessidade", tier[0], reading.hedge)
        if len(reading.dates) == 1:
            put("data_inicio", reading.dates[0].value, reading.hedge)
        elif not reading.dates and reading.relative_date and (d := _relative_date(plain, today)):
            put("data_inicio", d.isoformat(), True)

        intent = self._intent(plain, text, slots, asked, tier)
        known = {**p["known"], **{s["slot"]: s["value"] for s in slots if not s["uncertain"]}}
        missing = [s for s in _ORDER if s not in known]
        prefix = {"greeting": "Olá! Sou a assistente virtual da AutoSeguro. ", "provide_info": "Anotado! ", "correction": "Anotado! ",
                  "unclear": "Não entendi bem. "}.get(intent, "Já te respondo. ")
        facts_used: list[str] = []
        if not missing:
            reply = f"{prefix}Já vou montar a sua cotação."
        elif missing[0] == "necessidade":
            reply = prefix + questions.ask("necessidade", self._facts)
            facts_used = ["necessidades"]
        else:
            reply = prefix + _ASK[missing[0]]
        return {"slots": [s for s in slots if s["slot"] in SLOT_NAMES], "intent": intent, "facts_used": facts_used, "reply": reply}

    @staticmethod
    def _intent(plain: str, text: str, slots: list[dict], asked: str | None, tier) -> str:
        for intent, rx in _INTENT_RULES:
            if rx.search(plain):
                return intent
        if _CORRECTION.search(plain) and slots:
            return "correction"
        answering_need = asked == "necessidade" and tier is not None and "?" not in text
        if _COVERAGE_WORDS.search(plain) and not answering_need and ("?" in text or not slots):
            return "ask_coverage_question"
        if slots:
            return "provide_info"
        if _GREETING.search(plain):
            return "greeting"
        return "question_not_in_facts" if "?" in text else "unclear"
