"""Pre-checagem de elegibilidade: as faixas vem do /planos, a leitura espelha o servico e o CONTRATO contra a logica vendorizada vale nas bordas e numa amostra com semente.

O mesmo contrato contra a API HTTP real esta em tests/integration/test_precheck_contract.py (`make test-integration`)."""
from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from autoseguro.precheck import Rules, precheck
from autoseguro.refusals import RefusalKind
from tests.precheck_contract import SEED, cases, compare, vendored_service

ROOT = Path(__file__).resolve().parent.parent
PLANOS = json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8"))
RULES = Rules.from_planos(PLANOS)
TODAY = date(2026, 10, 21)


def verdict(idade, ano, today=TODAY, rules=RULES):
    return precheck(rules, idade=idade, veiculo_ano=ano, today=today)


def test_the_rules_are_read_from_the_plans_not_from_the_code():
    assert [(b.lo, b.hi, b.refuse) for b in RULES.age] == [(18, 24, False), (25, 29, False), (30, 59, False), (60, 75, False), (76, 200, True)]
    assert [(b.lo, b.hi, b.refuse) for b in RULES.vehicle] == [(0, 5, False), (6, 10, False), (11, 20, False), (21, 200, True)]
    stricter = copy.deepcopy(PLANOS)
    stricter["regras"]["faixa_etaria"][3]["idade_max"] = 70
    stricter["regras"]["faixa_etaria"][4]["idade_min"] = 71
    assert verdict(72, 2019).accepts and not verdict(72, 2019, rules=Rules.from_planos(stricter)).accepts


@pytest.mark.parametrize("idade,ano,accepts,kind", [
    (18, 2019, True, None), (17, 2019, False, RefusalKind.AGE_OUT_OF_RANGE), (75, 2019, True, None), (76, 2019, False, RefusalKind.AGE_ABOVE_LIMIT),
    (35, 2006, True, None), (35, 2005, False, RefusalKind.VEHICLE_TOO_OLD), (35, 2026, True, None), (35, 2027, False, RefusalKind.VEHICLE_YEAR_OUT_OF_RANGE),
    (80, 1998, False, RefusalKind.AGE_ABOVE_LIMIT),       # as duas recusam: o servico diz a da IDADE primeiro, e a pre-checagem tambem
    (10, 1998, False, RefusalKind.AGE_OUT_OF_RANGE),
])
def test_the_verdict_at_the_edges_of_each_band(idade, ano, accepts, kind):
    v = verdict(idade, ano)
    assert (v.accepts, v.kind) == (accepts, kind) and v.label == ("ok" if accepts else "recusa_provavel")


def test_the_clock_is_the_services_clock_so_the_edge_moves_with_the_year():
    assert verdict(35, 2006, date(2026, 12, 31)).accepts and not verdict(35, 2006, date(2027, 1, 1)).accepts


def test_the_boundaries_are_derived_from_the_rules_and_include_the_neighbours_outside():
    edges = RULES.boundaries()
    assert {17, 18, 24, 25, 29, 30, 59, 60, 75, 76} <= set(edges["idade"]) and {-1, 0, 5, 6, 10, 11, 20, 21} <= set(edges["anos_veiculo"])


@pytest.mark.parametrize("today", [date(2026, 10, 21), date(2027, 1, 1), date(2026, 12, 31), date(2028, 2, 29)])
def test_contract_against_the_services_own_logic_at_the_edges_and_on_a_seeded_sample(today):
    """A logica vendorizada do servico, em processo. O relogio e fixado, entao o teste tambem cobre a virada do ano."""
    bad = compare(RULES, vendored_service(today), today)
    assert not bad, f"{len(bad)} divergencia(s):\n" + "\n".join(bad[:20])
    n = len(cases(RULES, today))
    assert n > 400, "as bordas mais a amostra"


def test_the_contract_has_teeth_a_wrong_rule_is_caught_in_both_directions():
    """Controle negativo: a mesma comparacao, com uma regra errada de proposito, tem que reprovar. Sem isto, 'sem divergencia' nao provaria nada."""
    today = TODAY
    too_strict = copy.deepcopy(PLANOS)
    too_strict["regras"]["faixa_etaria"][3]["idade_max"] = 70
    too_strict["regras"]["faixa_etaria"][4]["idade_min"] = 71
    bad = compare(Rules.from_planos(too_strict), vendored_service(today), today)
    assert any(line.startswith("PRE-CHECAGEM RECUSA E O SERVICO ACEITA: idade=71") for line in bad), "o caso grave aparece"

    too_lenient = copy.deepcopy(PLANOS)
    too_lenient["regras"]["idade_veiculo"][3]["recusar"] = False
    bad = compare(Rules.from_planos(too_lenient), vendored_service(today), today)
    assert any(line.startswith("pre-checagem aceita e o servico recusa") for line in bad)
    assert f"semente {SEED}" in bad[0], "toda falha imprime a semente para reproduzir"


def test_the_sample_is_reproducible():
    assert cases(RULES, TODAY) == cases(RULES, TODAY)
