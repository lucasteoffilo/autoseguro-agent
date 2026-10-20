"""Saida estruturada de UMA chamada por mensagem: {slots, intent, facts_used, reply}.

Decisoes de desenho (ver docs/PLAN.md, secao 5):
  - `slots` e uma LISTA que so contem o que o lead disse nesta mensagem. A API de saida estruturada exige todos os campos em `required`
    e nao tem campo opcional, entao um objeto com 5 slots obrigatorios gastaria tokens com `null`. A lista e compacta por construcao.
  - `facts_used` e um enum com os ids reais da base de fatos: o modelo nao consegue citar um fato que nao existe.
  - O esquema usa so o subconjunto aceito: objetos com additionalProperties=false, enum, array, string, boolean. Sem limites de tamanho:
    o teto de ~40 palavras do `reply` vive no prompt e no guardrail, nao aqui.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

SLOT_NAMES = ("idade", "veiculo_ano", "cep", "necessidade", "data_inicio")
NECESSIDADES = ("basica", "terceiros_vidros", "completa")
INTENTS = ("greeting", "provide_info", "correction", "ask_coverage_question", "question_not_in_facts", "price_objection",
           "wants_human", "complaint", "claim", "cancel", "ready_to_close", "out_of_scope", "unclear")


def response_schema(fact_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "slots": {"type": "array", "items": {
                "type": "object",
                "properties": {"slot": {"type": "string", "enum": list(SLOT_NAMES)}, "value": {"type": "string"},
                               "uncertain": {"type": "boolean"}},
                "required": ["slot", "value", "uncertain"], "additionalProperties": False}},
            "intent": {"type": "string", "enum": list(INTENTS)},
            "facts_used": {"type": "array", "items": {"type": "string", "enum": list(fact_ids)}},
            "reply": {"type": "string"},
        },
        "required": ["slots", "intent", "facts_used", "reply"],
        "additionalProperties": False,
    }


class OutputError(ValueError):
    """Saida do modelo fora do contrato (nao deveria ocorrer com saida estruturada; validamos mesmo assim)."""


@dataclass(frozen=True)
class SlotValue:
    slot: str
    value: str
    uncertain: bool


@dataclass(frozen=True)
class TurnOutput:
    slots: tuple[SlotValue, ...]
    intent: str
    facts_used: tuple[str, ...]
    reply: str

    def entries(self, slot: str) -> list[SlotValue]:
        return [s for s in self.slots if s.slot == slot]

    def ambiguous(self) -> frozenset[str]:
        """Slots marcados como incertos pelo modelo OU informados duas vezes com valores diferentes."""
        out = {s.slot for s in self.slots if s.uncertain}
        for slot in {s.slot for s in self.slots}:
            if len({re.sub(r"\D", "", s.value) or s.value.strip().lower() for s in self.entries(slot)}) > 1:
                out.add(slot)
        return frozenset(out)

    def value(self, slot: str) -> str | None:
        """O valor do slot SO quando e inequivoco: uma unica leitura e nao marcada como incerta. Senao None (o agente pergunta)."""
        e = self.entries(slot)
        if len(e) == 1 and not e[0].uncertain:
            return e[0].value
        return None


def parse_turn_output(obj: object, fact_ids: Sequence[str]) -> TurnOutput:
    if not isinstance(obj, Mapping) or set(obj) != {"slots", "intent", "facts_used", "reply"}:
        raise OutputError("chaves inesperadas")
    if not isinstance(obj["slots"], list):
        raise OutputError("slots nao e lista")
    slots = []
    for s in obj["slots"]:
        if not isinstance(s, Mapping) or set(s) != {"slot", "value", "uncertain"}:
            raise OutputError("slot mal formado")
        if s["slot"] not in SLOT_NAMES or not isinstance(s["value"], str) or not isinstance(s["uncertain"], bool):
            raise OutputError("slot invalido")
        slots.append(SlotValue(s["slot"], s["value"], s["uncertain"]))
    if obj["intent"] not in INTENTS:
        raise OutputError("intent invalido")
    fu = obj["facts_used"]
    if not isinstance(fu, list) or not all(isinstance(f, str) for f in fu):
        raise OutputError("facts_used invalido")
    if not isinstance(obj["reply"], str):
        raise OutputError("reply invalido")
    return TurnOutput(tuple(slots), obj["intent"], tuple(fu), obj["reply"])  # ids de fato desconhecidos: quem reprova e o guardrail
