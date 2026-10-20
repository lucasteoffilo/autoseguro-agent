"""Simulacao Monte Carlo das politicas de cliente para o POST /quote.

Modelo (de vendor/quote-service/app/main.py + medicao local, ver docs/FINDINGS.md):
  F = P(5xx instantaneo, 0.04-0.20s) | S = P(lenta: 8.0s e responde 200 valido) | resto: 200 em 0.04-0.25s
Cada chamada sorteia seu resultado de forma independente (como o mock).

Politicas (orcamento de 15s por cotacao, no maximo 4 chamadas, backoff exponencial com jitter):
  A  timeout 2s + retry
  B  timeout 10s, retry so em 5xx     <- ADOTADA
  C  hedge aos 2s (+ retry em 5xx)    <- DESCARTADA

C existe AQUI apenas para documentar a decisao (README). O cliente de producao nao tem parametro de hedging.

Uso:  python -I analysis/latency_sim.py --out analysis/results [--n 200000] [--seed 7]
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

DEADLINE = 15.0   # orcamento por cotacao (s)
HOLD_AT = 2.5     # mensagem "um instante" se ainda sem resposta (s)
MAX_CALLS = 4

POLICIES = {
    "A": {"label": "A) timeout 2s + retry", "timeout": 2.0, "hedge": None},
    "B": {"label": "B) timeout 10s, retry so em 5xx (adotada)", "timeout": 10.0, "hedge": None},
    "C": {"label": "C) hedge aos 2s (descartada)", "timeout": 10.0, "hedge": 2.0},
}
SCENARIOS = {
    "nominal": {"label": "Nominal (5xx 20% / lenta 10%)", "fail": 0.20, "slow": 0.10},
    "degradado": {"label": "Degradado (5xx 50% / lenta 20%)", "fail": 0.50, "slow": 0.20},
}


def one_quote(rng: random.Random, fail: float, slow: float, timeout: float, max_calls: int, hedge: float | None,
              deadline: float = DEADLINE):
    """Simula uma cotacao. Retorna (tempo_ate_sucesso | None, tempo_decorrido, chamadas_feitas, pico_em_voo).

    "Em voo" = chamadas cujo resultado o cliente ainda espera. Uma chamada que estourou o timeout deixa de estar
    em voo para o cliente (o servidor segue trabalhando nela, e por isso ela conta em `chamadas_feitas`).
    """
    n_calls = 0
    max_inflight = 0
    inflight: list[tuple[float, bool]] = []  # (instante do evento, sucesso?)
    retry_at: float | None = None
    hedge_at: float | None = None
    failures = 0

    def launch(t: float) -> None:
        nonlocal n_calls, hedge_at, max_inflight
        r = rng.random()
        if r < fail:
            lat, ok = rng.uniform(0.04, 0.20), False
        elif r < fail + slow:
            lat, ok = 8.0 + rng.uniform(0, 0.05), True
        else:
            lat, ok = rng.uniform(0.04, 0.25), True
        limit = min(timeout, deadline - t)
        # estourou o timeout => falha para o cliente (o servidor continua trabalhando: conta como chamada)
        inflight.append((t + lat, ok) if lat <= limit else (t + limit, False))
        n_calls += 1
        max_inflight = max(max_inflight, len(inflight))
        hedge_at = (t + hedge) if hedge is not None else None

    launch(0.0)
    t = 0.0
    while True:
        events = []
        if inflight:
            events.append(("resp", min(e[0] for e in inflight)))
        if retry_at is not None:
            events.append(("retry", retry_at))
        if hedge_at is not None and inflight:
            events.append(("hedge", hedge_at))
        if not events:
            return None, t, n_calls, max_inflight
        kind, tm = min(events, key=lambda e: e[1])
        if tm >= deadline:
            return None, deadline, n_calls, max_inflight
        t = tm
        if kind == "resp":
            ev = min(inflight, key=lambda e: e[0])
            inflight.remove(ev)
            if ev[1]:
                return t, t, n_calls, max_inflight
            failures += 1
            if not inflight and retry_at is None and n_calls < max_calls:
                retry_at = t + 0.3 * 2 ** (failures - 1) * rng.uniform(0.5, 1.0)
        elif kind == "retry":
            retry_at = None
            launch(t)
        else:  # hedge
            hedge_at = None
            if n_calls < max_calls:
                launch(t)


def _quantile(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))]


def simulate(scenario: str, policy: str, n: int, seed: int, max_calls: int = MAX_CALLS) -> dict:
    sc, po = SCENARIOS[scenario], POLICIES[policy]
    rng = random.Random(seed)
    ok_times, calls, held, failed, peak = [], 0, 0, 0, 0
    for _ in range(n):
        res, elapsed, nc, mi = one_quote(rng, sc["fail"], sc["slow"], po["timeout"], max_calls, po["hedge"])
        calls += nc
        peak = max(peak, mi)
        held += elapsed > HOLD_AT
        if res is None:
            failed += 1
        else:
            ok_times.append(res)
    return {
        "policy": policy, "label": po["label"], "scenario": scenario, "n": n, "max_calls": max_calls,
        "p50_s": round(_quantile(ok_times, 50), 2),
        "p95_s": round(_quantile(ok_times, 95), 2),
        "p99_s": round(_quantile(ok_times, 99), 2),
        "no_quote_in_budget_pct": round(failed / n * 100, 2),
        "calls_per_quote": round(calls / n, 2),
        "max_inflight": peak,
        "holding_message_pct": round(held / n * 100, 1),
    }


def run_all(n: int = 200_000, seed: int = 7) -> dict:
    rows = [simulate(s, p, n, seed) for s in SCENARIOS for p in POLICIES]
    sweep = [simulate("nominal", "B", n, seed, max_calls=k) for k in (2, 3, 4, 5)]
    return {"deadline_s": DEADLINE, "holding_message_at_s": HOLD_AT, "rows": rows, "policy_b_max_calls_sweep": sweep}


def to_markdown(result: dict) -> str:
    out = [f"Orcamento {result['deadline_s']:.0f}s por cotacao; mensagem de espera aos {result['holding_message_at_s']}s.", ""]
    for s, sc in SCENARIOS.items():
        out += [f"**{sc['label']}**", "",
                "| Politica | p50 | p95 | p99 | Sem cotacao em 15s | Chamadas por cotacao | Msg 'um instante' |",
                "|---|---|---|---|---|---|---|"]
        for r in (x for x in result["rows"] if x["scenario"] == s):
            out.append(f"| {r['label']} | {r['p50_s']}s | {r['p95_s']}s | {r['p99_s']}s | "
                       f"{r['no_quote_in_budget_pct']}% | {r['calls_per_quote']} | {r['holding_message_pct']}% |")
        out.append("")
    out += ["**Politica B, nominal: efeito do maximo de chamadas**", "",
            "| max_calls | Sem cotacao em 15s | Chamadas por cotacao |", "|---|---|---|"]
    out += [f"| {r['max_calls']} | {r['no_quote_in_budget_pct']}% | {r['calls_per_quote']} |"
            for r in result["policy_b_max_calls_sweep"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="diretorio de saida (latency_sim.json e .md)")
    ap.add_argument("--n", type=int, default=200_000)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    result = run_all(a.n, a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "latency_sim.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    md = to_markdown(result)
    (a.out / "latency_sim.md").write_text(md, encoding="utf-8")
    print(md)
    return result


if __name__ == "__main__":
    main()
