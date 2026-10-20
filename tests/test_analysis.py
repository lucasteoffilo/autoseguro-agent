"""As analises rodam, reproduzem o que o README afirma e nao vazam texto do dataset."""
from __future__ import annotations

import json
import os

import pytest

from analysis import cost_model, e2e_latency_sim, latency_sim


@pytest.fixture(scope="module")
def e2e():
    return e2e_latency_sim.run_all(n=20_000, seed=11)


def test_quote_turn_p95_is_dominated_by_the_quote_slow_mode_not_the_llm(e2e):
    """Achado da Etapa 1: tirar o LLM do caminho critico devolve exatamente o p95 da /quote; com LLM rapido/medio so soma 1-2s."""
    quote_only = e2e["quote_only"]["nominal"]["p95_s"]
    for prof in ("rapido", "medio"):
        d = e2e["by_profile"]["nominal"][prof]
        assert d["quote_fast"]["p95_s"] == quote_only
        assert quote_only < d["quote"]["p95_s"] < quote_only + 3


def test_acceptance_criteria_break_where_the_plan_says(e2e):
    """Janelas robustas ao ruido de amostra (valores perto do limite nao sao assertados)."""
    sweep = {w["llm_p50_s"]: w for w in e2e["sweep"]}
    assert sweep[1.5]["c2_ok"] and sweep[1.5]["c3_ok"]        # LLM p50 <= 1,5s: tudo ok
    assert sweep[2.0]["c3_ok"]                                # cotacao ainda ok com p50 = 2s
    assert not sweep[3.0]["c2_ok"] and not sweep[4.0]["c3_ok"]  # turno simples quebra primeiro; cotacao depois
    p95s = [w["llm_turn_p95_s"] for w in e2e["sweep"]]
    assert all(a <= b + 0.1 for a, b in zip(p95s, p95s[1:]))  # monotonico


def test_slow_llm_profile_fails_acceptance_and_fast_passes(e2e):
    nominal = e2e["by_profile"]["nominal"]
    assert nominal["rapido"]["llm"]["p95_s"] <= e2e_latency_sim.C2_P95 and nominal["rapido"]["quote"]["p95_s"] <= e2e_latency_sim.C3_P95
    assert nominal["lento"]["llm"]["p95_s"] > e2e_latency_sim.C2_P95


def test_cache_break_even_matches_the_closed_form():
    h = cost_model.cache_break_even_hit_rate()
    assert h == pytest.approx(0.25 / 1.15)
    # exatamente no equilibrio, cachear o prefixo custa o mesmo que nao cachear
    assert cost_model.call_usd("haiku-5-5", True, h) == pytest.approx(cost_model.call_usd("haiku-5-5", False))
    assert cost_model.call_usd("haiku-5-5", True, 0.95) < cost_model.call_usd("haiku-5-5", False)
    assert cost_model.call_usd("haiku-5-5", True, 0.0) > cost_model.call_usd("haiku-5-5", False)


def test_cost_ordering_and_linearity_in_calls():
    r = cost_model.run_all()["usd_per_conversation"]
    k = lambda s, c: r[f"{s} | {c} | sem cache | sem thinking"]  # noqa: E731
    c5, c8 = "com fast-path (5 chamadas)", "sem fast-path (8 chamadas)"
    assert k("haiku", c8) < k("haiku+sonnet", c8) < k("sonnet", c8) < k("opus", c8)
    assert k("haiku", c8) / k("haiku", c5) == pytest.approx(8 / 5, rel=0.01)


def test_prices_are_the_documented_ones():
    p = cost_model.PRICES
    assert (p["haiku-5-5"]["inp"], p["haiku-5-5"]["out"]) == (0.10, 0.50)
    assert (p["sonnet-5-5"]["inp"], p["sonnet-5-5"]["out"]) == (2.00, 10.00)


@pytest.fixture(scope="module")
def sim():
    result = latency_sim.run_all(n=30_000, seed=7)
    return {(r["scenario"], r["policy"]): r for r in result["rows"]}


def test_latency_table_supports_policy_b(sim):
    """Amarra a justificativa do README (B adotada, hedging descartado) ao script que gera os numeros."""
    a, b, c = (sim[("nominal", p)] for p in "ABC")
    assert b["p50_s"] < 0.5 and 7.9 <= b["p95_s"] <= 8.2   # resposta lenta (8s) responde; cauda de ~8s
    assert b["no_quote_in_budget_pct"] < 0.5               # ~0.2^4
    assert 1.20 <= b["calls_per_quote"] <= 1.30
    # timeout curto cancela chamadas que o servidor continua processando: mais carga e mais falha que B
    assert a["calls_per_quote"] > b["calls_per_quote"] + 0.1
    assert a["no_quote_in_budget_pct"] > b["no_quote_in_budget_pct"]
    # hedging corta a cauda (p95), mas custa carga extra
    assert c["p95_s"] < 3.5 < b["p95_s"]
    assert c["calls_per_quote"] > b["calls_per_quote"] + 0.1


def test_adopted_policy_never_has_more_than_one_call_in_flight(sim):
    """Comportamento, nao string: sem hedging, o cliente espera uma chamada por vez em TODA cotacao simulada.

    O controle negativo esta aqui mesmo: a politica C (hedging) viola a propriedade, entao o teste distingue as duas.
    O mesmo teste vale para o cliente real na Etapa 2a (transporte falso + relogio virtual); ver docs/PLAN.md.
    """
    for scenario in ("nominal", "degradado"):
        for policy in ("A", "B"):
            assert sim[(scenario, policy)]["max_inflight"] == 1, f"{policy}/{scenario}"
        assert sim[(scenario, "C")]["max_inflight"] >= 2, "controle negativo: hedging deveria violar a propriedade"


def test_degraded_scenario_hedging_adds_load_without_helping(sim):
    b, c = sim[("degradado", "B")], sim[("degradado", "C")]
    assert c["calls_per_quote"] > b["calls_per_quote"] + 0.4
    assert abs(c["no_quote_in_budget_pct"] - b["no_quote_in_budget_pct"]) < 1.5


def test_dataset_profile_output_is_aggregate_only(dataset_bodies, tmp_path):
    pytest.importorskip("pandas")
    from analysis import dataset_profile

    out = tmp_path / "profile.json"
    dataset_profile.main(["--parquet", os.environ["DATASET_PATH"], "--out", str(out)])
    text = out.read_text(encoding="utf-8").lower()
    json.loads(text)  # valido
    leaked = [b for b in dataset_bodies if b in text]
    assert not leaked, f"{len(leaked)} texto(s) de mensagem na saida da analise"
