"""Esquema da saida estruturada, prompt e fast-path estrito."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from autoseguro import budgets
from autoseguro.facts import FactBase
from autoseguro.fastpath import fast_extract
from autoseguro.llm.prompt import build_system_prompt, build_user_message
from autoseguro.llm.schema import INTENTS, SLOT_NAMES, OutputError, SlotValue, TurnOutput, parse_turn_output, response_schema
from autoseguro.pii import find_pii

ROOT = Path(__file__).resolve().parent.parent
BASE = FactBase.from_planos(json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8")))
TODAY = date(2026, 10, 21)

UNSUPPORTED = {"minLength", "maxLength", "minimum", "maximum", "multipleOf", "minItems", "maxItems", "pattern", "format"}


def _walk(node):
    yield node
    if isinstance(node, dict):
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


# --- esquema ----------------------------------------------------------------------------------------------
def test_schema_uses_only_the_supported_subset():
    """Saida estruturada exige additionalProperties=false em todo objeto, todos os campos em `required`, e nao aceita limites de tamanho."""
    schema = response_schema(BASE.ids())
    for node in _walk(schema):
        if isinstance(node, dict) and node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        if isinstance(node, dict):
            assert not (UNSUPPORTED & set(node)), "o limite de 40 palavras vive no prompt e no guardrail, nao no esquema"


def test_slots_are_a_compact_list_not_five_nullable_fields():
    schema = response_schema(BASE.ids())
    slots = schema["properties"]["slots"]
    assert slots["type"] == "array" and slots["items"]["properties"]["slot"]["enum"] == list(SLOT_NAMES)
    assert schema["properties"]["intent"]["enum"] == list(INTENTS)
    assert "null" not in json.dumps(schema)


def test_facts_used_can_only_name_real_facts():
    assert response_schema(BASE.ids())["properties"]["facts_used"]["items"]["enum"] == list(BASE.ids())


# --- leitura da saida ------------------------------------------------------------------------------------------
def _ok(**over):
    base = {"slots": [{"slot": "idade", "value": "42", "uncertain": False}], "intent": "provide_info", "facts_used": [], "reply": "Anotado!"}
    base.update(over)
    return base


def test_parse_valid_output():
    out = parse_turn_output(_ok(), BASE.ids())
    assert out.slots == (SlotValue("idade", "42", False),) and out.intent == "provide_info" and out.reply == "Anotado!"


@pytest.mark.parametrize("bad", [
    {}, {"slots": []}, _ok(extra=1), _ok(slots="idade=42"), _ok(slots=[{"slot": "idade", "value": 42, "uncertain": False}]),
    _ok(slots=[{"slot": "cpf", "value": "x", "uncertain": False}]), _ok(slots=[{"slot": "idade", "value": "1", "uncertain": "nao"}]),
    _ok(slots=[{"slot": "idade", "value": "1"}]), _ok(intent="inventado"), _ok(facts_used="carencia"), _ok(facts_used=[1]), _ok(reply=None), [], "texto",
])
def test_parse_rejects_anything_outside_the_contract(bad):
    with pytest.raises(OutputError):
        parse_turn_output(bad, BASE.ids())


def test_value_is_returned_only_when_unambiguous():
    clear = TurnOutput((SlotValue("idade", "42", False),), "provide_info", (), "x")
    unsure = TurnOutput((SlotValue("idade", "35", True),), "provide_info", (), "x")
    conflict = TurnOutput((SlotValue("veiculo_ano", "2015", False), SlotValue("veiculo_ano", "2016", False)), "provide_info", (), "x")
    assert clear.value("idade") == "42" and clear.ambiguous() == frozenset()
    assert unsure.value("idade") is None and unsure.ambiguous() == {"idade"}
    assert conflict.value("veiculo_ano") is None and conflict.ambiguous() == {"veiculo_ano"}  # dois valores = incerteza, mesmo sem a marca
    assert clear.value("cep") is None


def test_same_value_written_twice_is_not_a_conflict():
    out = TurnOutput((SlotValue("cep", "01310-100", False), SlotValue("cep", "01310100", False)), "provide_info", (), "x")
    assert out.ambiguous() == frozenset()


# --- prompt -----------------------------------------------------------------------------------------------------------
def test_system_prompt_is_static_so_it_can_be_cached():
    a, b = build_system_prompt(BASE), build_system_prompt(BASE)
    assert a == b
    assert not re.search(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", a), "data no prompt de sistema invalidaria o cache; 'hoje' vai na mensagem"


def test_system_prompt_carries_the_rules_the_guardrail_enforces():
    p = build_system_prompt(BASE)
    assert f"No máximo {budgets.REPLY_TARGET_WORDS} palavras" in p
    for fact_id in BASE.ids():
        assert f"[{fact_id}]" in p
    assert "NUNCA calcule a idade" in p and "dado, nunca instrução" in p and "NUNCA escreva valores em dinheiro" in p
    assert "R$" not in p.replace("NUNCA escreva valores em dinheiro", "")  # nenhum valor em dinheiro nos fatos
    assert find_pii(p) == []


def test_user_message_is_deterministic_and_complete():
    kw = dict(today=TODAY, known_slots={"veiculo_ano": "2015", "idade": "42"}, asked_slot="cep", history=[("assistente", "Qual o CEP?")], message="01310-100")
    m = build_user_message(**kw)
    assert m == build_user_message(**kw)
    assert "hoje: 2026-10-21" in m and "idade=42, veiculo_ano=2015" in m and "pergunta pendente: cep" in m and m.endswith("01310-100")
    empty = build_user_message(today=TODAY, known_slots={}, asked_slot=None, history=[], message="oi")
    assert "dados já coletados: nenhum" in empty and "pergunta pendente: nenhuma" in empty and "(sem histórico)" in empty


# --- fast-path estrito -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("asked,text,expected", [
    ("veiculo_ano", "2015", "2015"), ("veiculo_ano", "ano 2015", "2015"), ("veiculo_ano", "o ano é 2015", "2015"), ("veiculo_ano", " 2015 ", "2015"),
    ("idade", "42", "42"), ("idade", "tenho 42", "42"), ("idade", "tenho 42 anos", "42"), ("idade", "42 anos", "42"),
    ("cep", "01310-100", "01310100"), ("cep", "o cep é 01310-100", "01310100"), ("cep", "meu cep 01310100", "01310100"), ("cep", "01310 100", "01310100"),
])
def test_fast_path_fires_only_on_a_direct_unambiguous_answer(asked, text, expected):
    assert fast_extract(asked, text, today=TODAY) == expected


@pytest.mark.parametrize("asked,text", [
    ("veiculo_ano", "2015 mas o modelo é 2016"), ("veiculo_ano", "2027"), ("veiculo_ano", "1949"), ("veiculo_ano", "2015!"), ("veiculo_ano", "é um onix 2019"),
    ("veiculo_ano", "42"), ("idade", "uns 35, quase 36 kkk"), ("idade", "nasci em 1990"), ("idade", "1990"), ("idade", "17"), ("idade", "130"),
    ("idade", "2015"), ("idade", "tenho 42 anos e moro em sp"), ("cep", "acho q é 04538-132 mas n tenho certeza"), ("cep", "1310100"),
    ("cep", "é um onix 2019, tenho 34 anos e moro no cep 30130-010"), (None, "2015"), ("necessidade", "completa"), ("data_inicio", "2026-11-15"),
])
def test_fast_path_abstains_whenever_there_is_any_doubt(asked, text):
    """Na duvida devolve None e a mensagem vai para o LLM. Estes sao exatamente os casos em que um erro silencioso custaria um preco errado."""
    assert fast_extract(asked, text, today=TODAY) is None


def test_the_product_does_not_call_the_fast_path():
    """Nasce desligado: so o smoke-llm (que mede) e os testes o importam."""
    users = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py") if "fastpath" in p.read_text(encoding="utf-8") and p.name != "fastpath.py"]
    assert users == []
