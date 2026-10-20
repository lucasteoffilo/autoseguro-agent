"""Latencia fim a fim POR MENSAGEM: chamada ao LLM + /quote (politica B) + overhead.

ATENCAO: a latencia do LLM aqui e HIPOTESE, nao medicao (nenhuma chamada real foi feita). Os perfis abaixo sao
substitutos parametricos (lognormal definida por p50 e p95); NAO sao a latencia de nenhum modelo especifico.
A /quote usa o modelo medido (analysis/latency_sim.py). Por isso o script tambem VARRE o p50 do LLM e mostra
em que ponto cada criterio de aceitacao quebra: a decisao nao deve depender de um numero que ainda nao foi medido.

Tipos de turno:
  fast         resposta deterministica (regex/fast-path), sem LLM
  llm          1 chamada de extracao ao LLM e resposta por template
  quote        1 chamada de extracao ao LLM e depois a /quote (LLM no caminho critico)
  quote_fast   igual a quote, mas o ultimo slot e extraido por regex: o LLM sai do caminho critico

Criterios de aceitacao (PROPOSTA do autor, a confirmar com o dono do produto):
  C1  silencio maximo <= 3s: garantido pela mensagem "um instante" aos 2,5s desde a chegada da mensagem
  C2  turno sem cotacao: p95 <= 5s
  C3  turno com cotacao: p95 <= 12s
  C4  pior caso duro de 20s por turno; estourou, vira handoff

Uso:  python -I analysis/e2e_latency_sim.py --out analysis/results [--n 100000] [--seed 11]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # sob `python -I` o diretorio do script nao entra no path
from analysis.latency_sim import DEADLINE, SCENARIOS, one_quote  # noqa: E402

OVERHEAD = 0.10        # webhook/terminal + SQLite + mascaramento + render de template (s)
HOLD_AT = 2.5          # "um instante" desde a CHEGADA da mensagem (s)
E2E_DEADLINE = 20.0    # pior caso duro por turno (s)
LLM_TIMEOUT = 6.0      # por tentativa; 1 retry
LLM_RETRY_BACKOFF = 0.3
QUOTE_TIMEOUT, QUOTE_MAX_CALLS = 10.0, 4  # politica B

# HIPOTESES (p50, p95) de UMA chamada: ~1,6K tokens de entrada, ~110 de saida, saida estruturada, effort baixo.
PROFILES = {"rapido": (0.8, 2.0), "medio": (1.8, 4.5), "lento": (3.5, 9.0)}
# turnos esperados por conversa tipica (7 a 8 mensagens do lead)
MIX = {"fast": 3.0, "llm": 3.0, "quote": 1.5}

C2_P95, C3_P95 = 5.0, 12.0


def llm_step(rng: random.Random, p50: float, p95: float) -> tuple[float, bool]:
    """Uma etapa de LLM com timeout e 1 retry. Retorna (tempo gasto, ok)."""
    mu, sigma = math.log(p50), math.log(p95 / p50) / 1.645
    spent = 0.0
    for attempt in range(2):
        lat = rng.lognormvariate(mu, sigma)
        if lat <= LLM_TIMEOUT:
            return spent + lat, True
        spent += LLM_TIMEOUT + (LLM_RETRY_BACKOFF if attempt == 0 else 0.0)
    return spent, False


def turn(rng: random.Random, kind: str, prof: tuple[float, float], scenario: dict) -> tuple[float, bool]:
    """Tempo ate a resposta final (resposta normal ou handoff) e se foi resposta normal."""
    t = OVERHEAD
    if kind == "fast":
        return t, True
    if kind in ("llm", "quote"):
        spent, ok = llm_step(rng, *prof)
        t += spent
        if not ok:
            return t, False  # LLM caiu: handoff SAFETY_GUARD
    if kind in ("quote", "quote_fast"):
        remaining = E2E_DEADLINE - t
        if remaining < 1.0:
            return t, False
        res, elapsed, _, _ = one_quote(rng, scenario["fail"], scenario["slow"], QUOTE_TIMEOUT, QUOTE_MAX_CALLS, None,
                                       deadline=min(DEADLINE, remaining))
        t += elapsed
        if res is None:
            return t, False  # QUOTE_UNAVAILABLE
    return t, True


def q(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))]


def stats(times: list[float], oks: list[bool]) -> dict:
    n = len(times)
    return {"p50_s": round(q(times, 50), 2), "p95_s": round(q(times, 95), 2), "p99_s": round(q(times, 99), 2),
            "hold_msg_pct": round(sum(t > HOLD_AT for t in times) / n * 100, 1),
            "handoff_pct": round(oks.count(False) / n * 100, 2)}


def run_kind(kind: str, prof: tuple[float, float], scenario: dict, n: int, seed: int) -> dict:
    rng = random.Random(seed)
    res = [turn(rng, kind, prof, scenario) for _ in range(n)]
    return stats([r[0] for r in res], [r[1] for r in res])


def run_mix(prof: tuple[float, float], scenario: dict, n: int, seed: int) -> dict:
    rng = random.Random(seed)
    kinds, weights = list(MIX), list(MIX.values())
    res = [turn(rng, rng.choices(kinds, weights)[0], prof, scenario) for _ in range(n)]
    return stats([r[0] for r in res], [r[1] for r in res])


def run_all(n: int = 100_000, seed: int = 11) -> dict:
    out: dict = {"assumptions": {"llm_profiles_p50_p95_s": PROFILES, "overhead_s": OVERHEAD, "hold_at_s": HOLD_AT,
                                 "e2e_deadline_s": E2E_DEADLINE, "llm_timeout_s": LLM_TIMEOUT,
                                 "turn_mix_per_conversation": MIX, "c2_p95_s": C2_P95, "c3_p95_s": C3_P95},
                 "by_profile": {}, "quote_only": {}, "sweep": []}
    for sname, sc in SCENARIOS.items():
        out["quote_only"][sname] = run_kind("quote_fast", (1.0, 2.0), sc, n, seed)  # LLM nao entra: so a /quote
        for pname, prof in PROFILES.items():
            out["by_profile"].setdefault(sname, {})[pname] = {
                kind: run_kind(kind, prof, sc, n, seed) for kind in ("llm", "quote", "quote_fast")}
            out["by_profile"][sname][pname]["mix"] = run_mix(prof, sc, n, seed)
    nominal = SCENARIOS["nominal"]
    for p50 in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0):
        prof = (p50, p50 * 2.5)
        row = {"llm_p50_s": p50, "llm_p95_s": round(p50 * 2.5, 2),
               "llm_turn_p95_s": run_kind("llm", prof, nominal, n // 2, seed)["p95_s"],
               "quote_turn_p95_s": run_kind("quote", prof, nominal, n // 2, seed)["p95_s"]}
        row["c2_ok"], row["c3_ok"] = row["llm_turn_p95_s"] <= C2_P95, row["quote_turn_p95_s"] <= C3_P95
        out["sweep"].append(row)
    return out


def to_markdown(r: dict) -> str:
    L = ["> Latencia do LLM = HIPOTESE (perfis parametricos), nao medicao. /quote = modelo medido (politica B).", ""]
    for s, sc in SCENARIOS.items():
        qo = r["quote_only"][s]
        L += [f"**{sc['label']}** (so a /quote, sem LLM: p50 {qo['p50_s']}s, p95 {qo['p95_s']}s, p99 {qo['p99_s']}s)", "",
              "| Perfil LLM (p50/p95) | Turno sem cotacao p95 | Turno com cotacao p50 | p95 | p99 | 'um instante' | Handoff | "
              "Cotacao com LLM fora do caminho critico: p95 |",
              "|---|---|---|---|---|---|---|---|"]
        for pname, (a, b) in PROFILES.items():
            d = r["by_profile"][s][pname]
            L.append(f"| {pname} ({a}s/{b}s) | {d['llm']['p95_s']}s | {d['quote']['p50_s']}s | {d['quote']['p95_s']}s | "
                     f"{d['quote']['p99_s']}s | {d['quote']['hold_msg_pct']}% | {d['quote']['handoff_pct']}% | "
                     f"{d['quote_fast']['p95_s']}s |")
        L.append("")
    L += ["**Varredura do p50 do LLM (p95 = 2,5x p50), cenario nominal**", "",
          f"| LLM p50 | LLM p95 | Turno sem cotacao p95 | C2 (<= {C2_P95:.0f}s) | Turno com cotacao p95 | C3 (<= {C3_P95:.0f}s) |",
          "|---|---|---|---|---|---|"]
    for w in r["sweep"]:
        L.append(f"| {w['llm_p50_s']}s | {w['llm_p95_s']}s | {w['llm_turn_p95_s']}s | {'ok' if w['c2_ok'] else 'FALHA'} | "
                 f"{w['quote_turn_p95_s']}s | {'ok' if w['c3_ok'] else 'FALHA'} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=100_000)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args(argv)
    result = run_all(a.n, a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "e2e_latency_sim.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    md = to_markdown(result)
    (a.out / "e2e_latency_sim.md").write_text(md, encoding="utf-8")
    print(md)
    return result


if __name__ == "__main__":
    main()
