"""As analises rodam, reproduzem o que o PLAN/README afirmam e nao vazam texto do dataset."""
from __future__ import annotations

import json
import math
import os
import random

import pytest

from analysis import cost_model, e2e_latency_sim, latency_sim


@pytest.fixture(scope="module")
def e2e():
    return e2e_latency_sim.run_all(n=20_000, seed=11)


@pytest.fixture(scope="module")
def sim():
    result = latency_sim.run_all(n=30_000, seed=7)
    return {(r["scenario"], r["policy"]): r for r in result["rows"]}


# --- latencia fim a fim ---------------------------------------------------------------------------------------------------
def test_quote_turn_p95_is_dominated_by_the_quote_slow_mode_not_the_llm(e2e):
    """Tirar o LLM do caminho critico devolve exatamente o p95 da /quote; o LLM soma por cima ~1,1s (rapido) a ~2,5s (medio)."""
    quote_only = e2e["quote_only"]["nominal"]["p95_s"]
    for prof, margin in (("rapido", 3.0), ("medio", 4.5)):
        d = e2e["by_profile"]["nominal"][prof]
        assert d["quote_fast"]["p95_s"] == quote_only
        assert quote_only < d["quote"]["p95_s"] < quote_only + margin


def test_acceptance_criteria_break_where_the_plan_says(e2e):
    """Janelas robustas ao ruido de amostra (valores perto do limite nao sao assertados)."""
    sweep = {w["llm_p50_s"]: w for w in e2e["sweep"]}
    assert sweep[1.5]["c2_ok"] and sweep[1.5]["c3_ok"]
    assert sweep[2.0]["c3_ok"]
    assert not sweep[3.0]["c2_ok"] and not sweep[4.0]["c3_ok"]
    p95s = [w["llm_turn_p95_s"] for w in e2e["sweep"]]
    assert all(a <= b + 0.1 for a, b in zip(p95s, p95s[1:]))


def test_slow_llm_profile_fails_acceptance_and_fast_passes(e2e):
    nominal = e2e["by_profile"]["nominal"]
    assert nominal["rapido"]["llm"]["p95_s"] <= e2e_latency_sim.C2_P95 and nominal["rapido"]["quote"]["p95_s"] <= e2e_latency_sim.C3_P95
    assert nominal["lento"]["llm"]["p95_s"] > e2e_latency_sim.C2_P95


def test_a_short_reply_alone_does_not_rescue_the_medium_profile(e2e):
    """Ajuste 1: 'o perfil medio estourar 5s so vale como conclusao se o reply curto nao resolver'. O teto de 40 palavras NAO resolve sozinho;
    a lista compacta de slots aproxima, mas deixa o medio SEM margem (perto do criterio)."""
    ts = e2e["token_scenarios"]
    assert ts["so_slots_verboso"]["medio"]["meets_no_quote"], "antes de o LLM redigir a resposta, o medio cumpria"
    assert not ts["reply_sem_teto"]["medio"]["meets_no_quote"]
    assert not ts["reply_40_palavras"]["medio"]["meets_no_quote"]
    capped_only = ts["reply_40_palavras"]["medio"]["turn_no_quote_p95_s"]
    assert ts["reply_sem_teto"]["medio"]["turn_no_quote_p95_s"] - capped_only < 1.0, "o teto sozinho tira menos de 1s"
    compact = ts["reply_40_slots_compactos"]["medio"]["turn_no_quote_p95_s"]
    assert compact < capped_only - 2.0 and abs(compact - e2e_latency_sim.C2_P95) < 1.0, "compactar ajuda, mas o medio fica na fronteira"


def test_the_fast_profile_meets_the_criterion_in_every_output_scenario_with_margin(e2e):
    for row in e2e["token_scenarios"].values():
        assert row["rapido"]["meets_no_quote"] and row["rapido"]["meets_with_quote"]
        assert row["rapido"]["turn_no_quote_p95_s"] < e2e_latency_sim.C2_P95 - 1.5


def test_more_output_tokens_never_shorten_the_turn(e2e):
    ts = e2e["token_scenarios"]
    ordered = sorted(ts.values(), key=lambda r: r["out_tokens"])
    for prof in e2e_latency_sim.PROFILE_PARAMS:
        p95s = [r[prof]["turn_no_quote_p95_s"] for r in ordered]
        assert all(a <= b + 0.15 for a, b in zip(p95s, p95s[1:])), prof


def test_per_call_limit_is_derived_from_the_turn_criterion_not_picked(e2e):
    d = e2e["derived_llm_call_limit"]
    assert d["binding_turn"] == "no_quote_turn", "o criterio de 5s sem cotacao e o que manda"
    assert 4.0 <= d["binding_llm_call_p95_max_s"] <= 5.5
    assert d["binding_llm_call_p95_max_s"] == pytest.approx(min(d["no_quote_turn"]["llm_call_p95_max_s"], d["with_quote_turn"]["llm_call_p95_max_s"]))
    ok = [w["llm_p50_s"] for w in e2e["sweep"] if w["c2_ok"]]
    bad = [w["llm_p50_s"] for w in e2e["sweep"] if not w["c2_ok"]]
    assert max(ok) <= d["no_quote_turn"]["llm_call_p50_max_s"] + 0.1 and min(bad) >= d["no_quote_turn"]["llm_call_p50_max_s"] - 0.1, \
        "o limite derivado concorda com a varredura"


def test_projection_from_measured_latencies_matches_the_parametric_model(e2e):
    """`project_turn_p95` e o que o smoke usa: reamostra latencias MEDIDAS. Com amostras do mesmo perfil, reproduz o modelo."""
    p50, p95 = e2e_latency_sim.profile("rapido", e2e["assumptions"]["out_tokens"])
    rng = random.Random(3)
    lats = [rng.lognormvariate(math.log(p50), math.log(p95 / p50) / 1.645) for _ in range(3000)]
    proj = e2e_latency_sim.project_turn_p95(lats, n=20_000)
    d = e2e["by_profile"]["nominal"]["rapido"]
    assert abs(proj["no_quote_p95_s"] - d["llm"]["p95_s"]) < 0.4 and abs(proj["with_quote_p95_s"] - d["quote"]["p95_s"]) < 0.6


def test_projection_flags_a_slow_model():
    slow = e2e_latency_sim.project_turn_p95([6.5] * 50, n=5000)
    assert slow["no_quote_p95_s"] > e2e_latency_sim.C2_P95
    with pytest.raises(ValueError):
        e2e_latency_sim.project_turn_p95([])


def test_profiles_at_110_tokens_reproduce_the_previous_analysis():
    for name, (p50, p95) in {"rapido": (0.8, 2.0), "medio": (1.8, 4.5), "lento": (3.5, 9.0)}.items():
        got = e2e_latency_sim.profile(name, e2e_latency_sim.OUT_TOKENS["so_slots_verboso"])
        assert got[0] == pytest.approx(p50, abs=0.05) and got[1] == pytest.approx(p95, abs=0.3)


def test_strict_fast_path_buys_little_p95_with_a_fast_llm(e2e):
    """Por que o fast-path nasce desligado: com LLM rapido, cobrir 40% dos turnos rende menos de 1s no p95 por mensagem."""
    s = e2e["fast_share_sensitivity"]["rapido"]
    assert 0 <= s["0.0"] - s["0.4"] < 1.0


def test_mix_weights_sum_to_a_typical_conversation():
    for fs in (0.0, 0.3, 0.4):
        assert sum(e2e_latency_sim.mix_weights(fs).values()) == pytest.approx(e2e_latency_sim.TURNS_PER_CONVERSATION)


# --- custo ------------------------------------------------------------------------------------------------------------------
def test_reply_in_the_llm_call_costs_between_a_sixth_and_a_third_more():
    """Com saida compacta (128 tokens) o custo sobe ~16% (com cache) a ~32% (sem cache); o prefixo maior pesa mais que o reply."""
    ba = cost_model.run_all()["before_after_reply_in_llm"]
    assert ba and all(10 < v["delta_pct"] < 40 for v in ba.values())
    assert ba["haiku | sem cache"]["delta_pct"] > ba["haiku | cache, hit 95% (trafego continuo)"]["delta_pct"]


def test_cache_break_even_matches_the_closed_form():
    h = cost_model.cache_break_even_hit_rate()
    assert h == pytest.approx(0.25 / 1.15)
    assert cost_model.call_usd("haiku-5-5", True, h) == pytest.approx(cost_model.call_usd("haiku-5-5", False))
    assert cost_model.call_usd("haiku-5-5", True, 0.95) < cost_model.call_usd("haiku-5-5", False)
    assert cost_model.call_usd("haiku-5-5", True, 0.0) > cost_model.call_usd("haiku-5-5", False)


def test_cost_ordering_and_linearity_in_calls():
    r = cost_model.run_all()["usd_per_conversation"]
    k = lambda s, c: r[f"{s} | {c} | sem cache | sem thinking"]  # noqa: E731
    c5, c8 = "com fast-path (5 chamadas)", "sem fast-path (8 chamadas)"
    assert k("haiku", c8) < k("haiku+sonnet", c8) < k("sonnet", c8) < k("opus", c8)
    assert k("haiku", c8) / k("haiku", c5) == pytest.approx(8 / 5, rel=0.01)


def test_verbose_slots_would_cost_more_than_the_compact_list():
    r = cost_model.run_all()
    assert r["sensitivity_verbose_slots_haiku_8_calls_no_cache_usd"] > r["usd_per_conversation"]["haiku | sem fast-path (8 chamadas) | sem cache | sem thinking"]


def test_prices_are_the_documented_ones():
    p = cost_model.PRICES
    assert (p["haiku-5-5"]["inp"], p["haiku-5-5"]["out"]) == (0.10, 0.50)
    assert (p["sonnet-5-5"]["inp"], p["sonnet-5-5"]["out"]) == (2.00, 10.00)


# --- politica de cotacao (simulador) ----------------------------------------------------------------------------------------------
def test_latency_table_supports_policy_b(sim):
    a, b, c = (sim[("nominal", p)] for p in "ABC")
    assert b["p50_s"] < 0.5 and 7.9 <= b["p95_s"] <= 8.2
    assert b["no_quote_in_budget_pct"] < 0.5
    assert 1.20 <= b["calls_per_quote"] <= 1.30
    assert a["calls_per_quote"] > b["calls_per_quote"] + 0.1
    assert a["no_quote_in_budget_pct"] > b["no_quote_in_budget_pct"]
    assert c["p95_s"] < 3.5 < b["p95_s"]
    assert c["calls_per_quote"] > b["calls_per_quote"] + 0.1


def test_adopted_policy_never_has_more_than_one_call_in_flight(sim):
    """No SIMULADOR. O mesmo teste roda no cliente real em tests/test_quote_client.py::test_never_more_than_one_call_in_flight."""
    for scenario in ("nominal", "degradado"):
        for policy in ("A", "B"):
            assert sim[(scenario, policy)]["max_inflight"] == 1, f"{policy}/{scenario}"
        assert sim[(scenario, "C")]["max_inflight"] >= 2, "controle negativo: hedging deveria violar a propriedade"


def test_degraded_scenario_hedging_adds_load_without_helping(sim):
    b, c = sim[("degradado", "B")], sim[("degradado", "C")]
    assert c["calls_per_quote"] > b["calls_per_quote"] + 0.4
    assert abs(c["no_quote_in_budget_pct"] - b["no_quote_in_budget_pct"]) < 1.5


# --- dataset ----------------------------------------------------------------------------------------------------------------------
def test_dataset_profile_output_is_aggregate_only(dataset_bodies, tmp_path):
    pytest.importorskip("pandas", reason="extra opcional ausente (pip install -e '.[analysis]')")
    from analysis import dataset_profile

    out = tmp_path / "profile.json"
    dataset_profile.main(["--parquet", os.environ["DATASET_PATH"], "--out", str(out)])
    text = out.read_text(encoding="utf-8").lower()
    json.loads(text)
    leaked = [b for b in dataset_bodies if b in text]
    assert not leaked, f"{len(leaked)} texto(s) de mensagem na saida da analise"
