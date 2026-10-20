"""Um criterio de latencia, uma fonte de numeros: produto, simuladores e smoke leem de `autoseguro.budgets`."""
from __future__ import annotations

from analysis import e2e_latency_sim, latency_sim
from autoseguro import budgets


def test_the_single_latency_criterion_is_the_approved_one():
    assert (budgets.TURN_P95_NO_QUOTE_S, budgets.TURN_P95_WITH_QUOTE_S) == (5.0, 12.0)


def test_mechanisms_serve_the_criterion_and_are_not_extra_criteria():
    assert budgets.HOLD_AFTER_S <= 3.0, "o 'um instante' garante silencio de no maximo 3s"
    assert budgets.TURN_CEILING_S == 20.0 and budgets.TURN_CEILING_S > budgets.TURN_P95_WITH_QUOTE_S
    assert budgets.QUOTE_BUDGET_S < budgets.TURN_CEILING_S


def test_the_simulators_use_the_product_numbers_not_their_own_copies():
    assert (e2e_latency_sim.C2_P95, e2e_latency_sim.C3_P95) == (budgets.TURN_P95_NO_QUOTE_S, budgets.TURN_P95_WITH_QUOTE_S)
    assert e2e_latency_sim.E2E_DEADLINE == budgets.TURN_CEILING_S and e2e_latency_sim.HOLD_AT == budgets.HOLD_AFTER_S
    assert (latency_sim.DEADLINE, latency_sim.MAX_CALLS, latency_sim.BACKOFF_BASE) == (
        budgets.QUOTE_BUDGET_S, budgets.QUOTE_MAX_CALLS, budgets.QUOTE_BACKOFF_BASE_S)


def test_reply_cap_is_about_forty_words_with_a_hard_limit_above_it():
    assert budgets.REPLY_TARGET_WORDS == 40 and budgets.REPLY_HARD_MAX_WORDS > budgets.REPLY_TARGET_WORDS
