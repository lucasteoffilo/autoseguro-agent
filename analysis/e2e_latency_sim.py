"""Latencia fim a fim POR MENSAGEM: chamada ao LLM + /quote (politica B) + overhead.

ATENCAO: a latencia do LLM aqui e HIPOTESE, nao medicao (nenhuma chamada real foi feita). Cada perfil e um substituto parametrico:
p50 de UMA chamada = TTFT + tokens_de_saida / velocidade, com p95 = 2,5 x p50. NAO e a latencia de nenhum modelo especifico.
A /quote usa o modelo medido (analysis/latency_sim.py).

UM criterio de latencia (aprovado, em autoseguro.budgets): p95 do TURNO <= 5s sem cotacao e <= 12s com cotacao. O "um instante" aos 2,5s e o
teto de 20s sao mecanismos, nao criterios. O limite POR CHAMADA de LLM nao e um numero solto: `derive_llm_call_limit` o deriva do criterio,
e `project_turn_p95` projeta o p95 do turno a partir de latencias MEDIDAS (e o que o smoke-llm usa).

Tipos de turno:
  fast         resposta deterministica (fast-path estrito, desligado por padrao), sem LLM
  llm          1 chamada ao LLM (slots + resposta); o fast-path nao se aplica
  quote        1 chamada ao LLM e depois a /quote (LLM no caminho critico)
  quote_fast   igual a quote, mas o LLM sai do caminho critico (limite inferior: so a /quote)

Uso:  python -I analysis/e2e_latency_sim.py --out analysis/results [--n 100000] [--seed 11]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))          # sob `python -I` o diretorio do script nao entra no path
sys.path.insert(0, str(ROOT / "src"))
from analysis.latency_sim import SCENARIOS, one_quote  # noqa: E402
from autoseguro import budgets  # noqa: E402  fonte unica dos numeros

OVERHEAD = budgets.OVERHEAD_S
HOLD_AT = budgets.HOLD_AFTER_S
E2E_DEADLINE = budgets.TURN_CEILING_S
LLM_TIMEOUT = budgets.LLM_CALL_TIMEOUT_S
LLM_RETRY_BACKOFF = 0.3
C2_P95 = budgets.TURN_P95_NO_QUOTE_S        # turno sem cotacao
C3_P95 = budgets.TURN_P95_WITH_QUOTE_S      # turno com cotacao

# HIPOTESES: (TTFT p50 em s, tokens por segundo). p95 = P95_OVER_P50 x p50.
PROFILE_PARAMS = {"rapido": (0.35, 250.0), "medio": (0.60, 90.0), "lento": (1.00, 44.0)}
P95_OVER_P50 = 2.5

# Tokens de saida por chamada (HIPOTESES; o smoke-llm mede o real). Componentes: estrutura+slots (verboso 110, compacto ~55),
# facts_used (~8) e reply (sem teto ~80; ate 40 palavras ~65, a ~1,6 token/palavra).
OUT_TOKENS = {
    "so_slots_verboso": 110,           # {slots, intent}, 5 slots sempre presentes: a versao ANTES de o LLM redigir a resposta
    "reply_sem_teto": 190,             # + reply de ~50 palavras
    "reply_40_palavras": 183,          # reply <= 40 palavras + facts_used, com slots verbosos (110 + 8 + 65)
    "reply_40_slots_compactos": 128,   # idem com slots em LISTA, so o que o lead disse (55 + 8 + 65): o DESENHO ATUAL
}
DEFAULT_SCENARIO = "reply_40_slots_compactos"

TURNS_PER_CONVERSATION = 7.5   # mensagens do lead numa conversa tipica
QUOTE_TURNS = 1.5              # dessas, as que chamam a /quote
FAST_SHARE = 0.0               # o fast-path nasce DESLIGADO; a sensibilidade mostra quanto valeria ligar


def profile(name: str, out_tokens: int) -> tuple[float, float]:
    ttft, speed = PROFILE_PARAMS[name]
    p50 = ttft + out_tokens / speed
    return round(p50, 2), round(p50 * P95_OVER_P50, 2)


def mix_weights(fast_share: float) -> dict[str, float]:
    fast = fast_share * TURNS_PER_CONVERSATION
    return {"fast": fast, "llm": TURNS_PER_CONVERSATION - QUOTE_TURNS - fast, "quote": QUOTE_TURNS}


Latency = tuple[float, float] | Callable[[random.Random], float]  # (p50, p95) lognormal OU amostrador de latencias medidas


def _draw(rng: random.Random, prof: Latency) -> float:
    if callable(prof):
        return prof(rng)
    p50, p95 = prof
    return rng.lognormvariate(math.log(p50), math.log(p95 / p50) / 1.645)


def llm_step(rng: random.Random, prof: Latency) -> tuple[float, bool]:
    """Uma etapa de LLM com timeout e 1 retry. Retorna (tempo gasto, ok)."""
    spent = 0.0
    for attempt in range(budgets.LLM_MAX_ATTEMPTS):
        lat = _draw(rng, prof)
        if lat <= LLM_TIMEOUT:
            return spent + lat, True
        spent += LLM_TIMEOUT + (LLM_RETRY_BACKOFF if attempt == 0 else 0.0)
    return spent, False


def turn(rng: random.Random, kind: str, prof: Latency, scenario: dict) -> tuple[float, bool]:
    """Tempo ate a resposta final (resposta normal ou handoff) e se foi resposta normal."""
    t = OVERHEAD
    if kind == "fast":
        return t, True
    if kind in ("llm", "quote"):
        spent, ok = llm_step(rng, prof)
        t += spent
        if not ok:
            return t, False  # LLM caiu: handoff SAFETY_GUARD (componente: llm)
    if kind in ("quote", "quote_fast"):
        remaining = E2E_DEADLINE - t
        if remaining < budgets.QUOTE_MIN_ATTEMPT_S:
            return t, False
        res, elapsed, _, _ = one_quote(rng, scenario["fail"], scenario["slow"], budgets.QUOTE_ATTEMPT_TIMEOUT_S, budgets.QUOTE_MAX_CALLS,
                                       None, deadline=min(budgets.QUOTE_BUDGET_S, remaining))
        t += elapsed
        if res is None:
            return t, False  # QUOTE_UNAVAILABLE (componente: quote_api)
    return t, True


def q(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))]


def stats(times: list[float], oks: list[bool]) -> dict:
    n = len(times)
    return {"p50_s": round(q(times, 50), 2), "p95_s": round(q(times, 95), 2), "p99_s": round(q(times, 99), 2),
            "hold_msg_pct": round(sum(t > HOLD_AT for t in times) / n * 100, 1),
            "handoff_pct": round(oks.count(False) / n * 100, 2), "max_s": round(max(times), 2)}


def run_kind(kind: str, prof: Latency, scenario: dict, n: int, seed: int) -> dict:
    rng = random.Random(seed)
    res = [turn(rng, kind, prof, scenario) for _ in range(n)]
    return stats([r[0] for r in res], [r[1] for r in res])


def run_mix(prof: Latency, scenario: dict, n: int, seed: int, fast_share: float) -> dict:
    rng = random.Random(seed)
    w = mix_weights(fast_share)
    kinds, weights = list(w), list(w.values())
    res = [turn(rng, rng.choices(kinds, weights)[0], prof, scenario) for _ in range(n)]
    return stats([r[0] for r in res], [r[1] for r in res])


# --- derivacao do limite por chamada, a partir do criterio do turno ---------------------------------------------------
def derive_llm_call_limit(n: int = 30_000, seed: int = 11) -> dict:
    """Maior p50 (e p95 = 2,5 x p50) de UMA chamada de LLM para o p95 do TURNO ainda cumprir o criterio, por bissecao.
    O limite por chamada nao e escolhido: e consequencia do criterio do turno (5s sem cotacao, 12s com)."""
    nominal = SCENARIOS["nominal"]

    def largest_p50(kind: str, target: float) -> float:
        lo, hi = 0.1, 12.0
        for _ in range(14):
            mid = (lo + hi) / 2
            if run_kind(kind, (mid, mid * P95_OVER_P50), nominal, n, seed)["p95_s"] <= target:
                lo = mid
            else:
                hi = mid
        return lo

    a, b = largest_p50("llm", C2_P95), largest_p50("quote", C3_P95)
    return {"assumption": f"p95 da chamada = {P95_OVER_P50} x p50; cenario nominal da /quote",
            "no_quote_turn": {"criterion_p95_s": C2_P95, "llm_call_p50_max_s": round(a, 2), "llm_call_p95_max_s": round(a * P95_OVER_P50, 2)},
            "with_quote_turn": {"criterion_p95_s": C3_P95, "llm_call_p50_max_s": round(b, 2), "llm_call_p95_max_s": round(b * P95_OVER_P50, 2)},
            "binding_llm_call_p95_max_s": round(min(a, b) * P95_OVER_P50, 2),
            "binding_turn": "no_quote_turn" if a <= b else "with_quote_turn"}


def project_turn_p95(latencies_s: Sequence[float], *, n: int = 30_000, seed: int = 11, scenario: str = "nominal") -> dict:
    """p95 do TURNO projetado a partir de latencias de LLM MEDIDAS (reamostragem com reposicao), combinadas com o modelo da /quote."""
    lats = list(latencies_s)
    if not lats:
        raise ValueError("sem latencias medidas")
    sampler: Latency = lambda rng: rng.choice(lats)  # noqa: E731
    sc = SCENARIOS[scenario]
    return {"no_quote_p95_s": run_kind("llm", sampler, sc, n, seed)["p95_s"],
            "with_quote_p95_s": run_kind("quote", sampler, sc, n, seed)["p95_s"], "samples": len(lats), "scenario": scenario}


# --- execucao completa ------------------------------------------------------------------------------------------------
def run_all(n: int = 100_000, seed: int = 11, scenario: str = DEFAULT_SCENARIO, fast_share: float = FAST_SHARE) -> dict:
    out_tokens = OUT_TOKENS[scenario]
    profs = {name: profile(name, out_tokens) for name in PROFILE_PARAMS}
    out: dict = {"assumptions": {"scenario": scenario, "out_tokens": out_tokens, "fast_share": fast_share, "llm_profiles_p50_p95_s": profs,
                                 "out_tokens_scenarios": OUT_TOKENS, "overhead_s": OVERHEAD, "hold_at_s": HOLD_AT,
                                 "e2e_deadline_s": E2E_DEADLINE, "llm_timeout_s": LLM_TIMEOUT,
                                 "turn_mix_per_conversation": mix_weights(fast_share), "c2_p95_s": C2_P95, "c3_p95_s": C3_P95},
                 "by_profile": {}, "quote_only": {}, "sweep": [], "token_scenarios": {}, "fast_share_sensitivity": {}}
    for sname, sc in SCENARIOS.items():
        out["quote_only"][sname] = run_kind("quote_fast", (1.0, 2.0), sc, n, seed)  # LLM nao entra: so a /quote
        for pname, prof in profs.items():
            out["by_profile"].setdefault(sname, {})[pname] = {
                kind: run_kind(kind, prof, sc, n, seed) for kind in ("llm", "quote", "quote_fast")}
            out["by_profile"][sname][pname]["mix"] = run_mix(prof, sc, n, seed, fast_share)
    nominal, m = SCENARIOS["nominal"], n // 2
    for tname, toks in OUT_TOKENS.items():  # o reply curto resolve o perfil medio? (ajuste 1)
        row = {"out_tokens": toks}
        for pname in PROFILE_PARAMS:
            prof = profile(pname, toks)
            llm_p95 = run_kind("llm", prof, nominal, m, seed)["p95_s"]
            quote_p95 = run_kind("quote", prof, nominal, m, seed)["p95_s"]
            row[pname] = {"llm_p50_s": prof[0], "llm_p95_s": prof[1], "turn_no_quote_p95_s": llm_p95, "turn_with_quote_p95_s": quote_p95,
                          "mix_p95_s": run_mix(prof, nominal, m, seed, fast_share)["p95_s"],
                          "meets_no_quote": llm_p95 <= C2_P95, "meets_with_quote": quote_p95 <= C3_P95}
        out["token_scenarios"][tname] = row
    for pname in PROFILE_PARAMS:
        out["fast_share_sensitivity"][pname] = {str(fs): run_mix(profs[pname], nominal, m, seed, fs)["p95_s"] for fs in (0.0, 0.3, 0.4)}
    for p50 in (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0):
        prof = (p50, p50 * P95_OVER_P50)
        row = {"llm_p50_s": p50, "llm_p95_s": round(p50 * P95_OVER_P50, 2),
               "llm_turn_p95_s": run_kind("llm", prof, nominal, m, seed)["p95_s"],
               "quote_turn_p95_s": run_kind("quote", prof, nominal, m, seed)["p95_s"]}
        row["c2_ok"], row["c3_ok"] = row["llm_turn_p95_s"] <= C2_P95, row["quote_turn_p95_s"] <= C3_P95
        out["sweep"].append(row)
    out["derived_llm_call_limit"] = derive_llm_call_limit(seed=seed)
    return out


def to_markdown(r: dict) -> str:
    a = r["assumptions"]
    L = [f"> Latencia do LLM = HIPOTESE (TTFT + {a['out_tokens']} tokens de saida / velocidade; cenario '{a['scenario']}'), nao medicao. "
         f"/quote = modelo medido (politica B). Fast-path cobre {a['fast_share'] * 100:.0f}% dos turnos (desligado por padrao).", ""]
    for s, sc in SCENARIOS.items():
        qo = r["quote_only"][s]
        L += [f"**{sc['label']}** (so a /quote, sem LLM: p50 {qo['p50_s']}s, p95 {qo['p95_s']}s, p99 {qo['p99_s']}s)", "",
              "| Perfil LLM (p50/p95 de uma chamada) | Turno sem cotacao p95 | Turno com cotacao p50 | p95 | p99 | 'um instante' | Handoff | "
              "Mensagem qualquer: p95 |", "|---|---|---|---|---|---|---|---|"]
        for pname, (p50, p95) in a["llm_profiles_p50_p95_s"].items():
            d = r["by_profile"][s][pname]
            L.append(f"| {pname} ({p50}s/{p95}s) | {d['llm']['p95_s']}s | {d['quote']['p50_s']}s | {d['quote']['p95_s']}s | "
                     f"{d['quote']['p99_s']}s | {d['quote']['hold_msg_pct']}% | {d['quote']['handoff_pct']}% | {d['mix']['p95_s']}s |")
        L.append("")
    L += [f"**O reply curto resolve o perfil medio? p95 do turno, nominal (criterio: {C2_P95:.0f}s sem cotacao, {C3_P95:.0f}s com)**", "",
          "| Cenario de saida | Tokens | rapido: sem / com cotacao | medio: sem / com cotacao | lento: sem / com cotacao |", "|---|---|---|---|---|"]
    for tname, row in r["token_scenarios"].items():
        cells = []
        for pname in PROFILE_PARAMS:
            d = row[pname]
            cells.append(f"{d['turn_no_quote_p95_s']}s {'ok' if d['meets_no_quote'] else 'FALHA'} / "
                         f"{d['turn_with_quote_p95_s']}s {'ok' if d['meets_with_quote'] else 'FALHA'}")
        L.append(f"| {tname} | {row['out_tokens']} | " + " | ".join(cells) + " |")
    dl = r["derived_llm_call_limit"]
    L += ["", f"**Limite por chamada DERIVADO do criterio do turno** ({dl['assumption']})", "",
          f"- turno sem cotacao (p95 <= {dl['no_quote_turn']['criterion_p95_s']:.0f}s): chamada com p50 <= {dl['no_quote_turn']['llm_call_p50_max_s']}s, "
          f"p95 <= {dl['no_quote_turn']['llm_call_p95_max_s']}s",
          f"- turno com cotacao (p95 <= {dl['with_quote_turn']['criterion_p95_s']:.0f}s): chamada com p50 <= {dl['with_quote_turn']['llm_call_p50_max_s']}s, "
          f"p95 <= {dl['with_quote_turn']['llm_call_p95_max_s']}s",
          f"- **restricao ativa: {dl['binding_turn']}; p95 por chamada <= {dl['binding_llm_call_p95_max_s']}s**", "",
          "**Sensibilidade a cobertura do fast-path (p95 de uma mensagem qualquer, nominal)**", "", "| Perfil | 0% | 30% | 40% |", "|---|---|---|---|"]
    for pname, row in r["fast_share_sensitivity"].items():
        L.append(f"| {pname} | {row['0.0']}s | {row['0.3']}s | {row['0.4']}s |")
    L += ["", "**Varredura do p50 do LLM (p95 = 2,5x p50), cenario nominal**", "",
          f"| LLM p50 | LLM p95 | Turno sem cotacao p95 | <= {C2_P95:.0f}s | Turno com cotacao p95 | <= {C3_P95:.0f}s |", "|---|---|---|---|---|---|"]
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
