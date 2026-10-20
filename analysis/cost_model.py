"""Custo por conversa: tokens medios, modelo por passo e dolares.

ATENCAO: os tokens por chamada sao ESTIMATIVAS DE PROJETO (o prompt ainda nao existe), com incerteza de +-35%.
Os precos sao dados (skill claude-api, tabela em cache de 2026-10-06): CONFERIR antes de decidir. Nenhuma chamada
real foi feita. A medicao real vem do `usage` de cada resposta, registrado em messages.meta (ver docs/PLAN.md).

Passos que chamam LLM (todos com saida estruturada e effort baixo):
  extracao+intencao   a cada mensagem do lead que o fast-path (regex) nao resolve
  escalonamento       repete a chamada num modelo maior quando a extracao vem invalida/ambigua (taxa abaixo)
Passos SEM LLM por desenho: redacao das mensagens (template), resumo do handoff (deterministico a partir dos slots).

Uso:  python -I analysis/cost_model.py --out analysis/results
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# USD por 1M de tokens. Haiku 5.5: vale para prompts <= 100K tokens (acima disso, 0.50/2.50).
PRICES = {
    "haiku-5-5": {"inp": 0.10, "out": 0.50, "read": 0.10},
    "sonnet-5-5": {"inp": 2.00, "out": 10.00, "read": 0.10},
    "opus-5-5": {"inp": 4.00, "out": 20.00, "read": 0.05},
}
WRITE_5M, WRITE_1H = 1.25, 2.0   # multiplicadores sobre o preco de entrada

# ESTIMATIVAS por chamada de extracao
TOK = {"static_prefix": 1500,  # sistema + schema + regras + few-shots (identico em todas as conversas: cacheavel)
       "state": 150,           # slots ja coletados (JSON)
       "history": 250,         # janela das ultimas ~6 mensagens, mascaradas
       "message": 40,          # mensagem atual
       "output": 110}          # JSON estruturado
CALLS = {"com fast-path (5 chamadas)": 5, "sem fast-path (8 chamadas)": 8, "conversa dificil (12 chamadas)": 12}
ESCALATION_RATE = 0.10
THINKING_EXTRA_OUT = 250       # sensibilidade: raciocinio residual cobrado como saida


def call_usd(model: str, cache: bool, hit: float = 0.0, extra_out: int = 0) -> float:
    p, d = PRICES[model], TOK["state"] + TOK["history"] + TOK["message"]
    s = TOK["static_prefix"]
    if cache:
        inp = s * p["inp"] * (hit * p["read"] + (1 - hit) * WRITE_5M) + d * p["inp"]
    else:
        inp = (s + d) * p["inp"]
    return (inp + (TOK["output"] + extra_out) * p["out"]) / 1e6


def strategy_call_usd(strategy: str, cache: bool, hit: float, extra_out: int) -> float:
    if strategy == "haiku":
        return call_usd("haiku-5-5", cache, hit, extra_out)
    if strategy == "haiku+sonnet":  # a escalonada vai a outro modelo = outro cache; assume sem cache (pior caso)
        return call_usd("haiku-5-5", cache, hit, extra_out) + ESCALATION_RATE * call_usd("sonnet-5-5", False, 0, extra_out)
    if strategy == "sonnet":
        return call_usd("sonnet-5-5", cache, hit, extra_out)
    return call_usd("opus-5-5", cache, hit, extra_out)


def cache_break_even_hit_rate(write_mult: float = WRITE_5M, read_mult: float = 0.10) -> float:
    """Taxa de acerto a partir da qual cachear o prefixo compensa o premio de escrita."""
    return (write_mult - 1) / (write_mult - read_mult)


def tokens_per_conversation(n_calls: int, hit: float) -> dict:
    s, d, o = TOK["static_prefix"], TOK["state"] + TOK["history"] + TOK["message"], TOK["output"]
    return {"input_total": n_calls * (s + d), "input_from_cache": round(n_calls * s * hit), "output_total": n_calls * o}


def run_all() -> dict:
    cache_modes = {"sem cache": (False, 0.0), "cache, hit 95% (trafego continuo)": (True, 0.95),
                   "cache, hit 0% (trafego raro: so paga a escrita)": (True, 0.0)}
    out: dict = {"assumptions": {"prices_usd_per_mtok": PRICES, "tokens_per_call": TOK, "calls_per_conversation": CALLS,
                                 "escalation_rate": ESCALATION_RATE, "write_5m_mult": WRITE_5M, "write_1h_mult": WRITE_1H,
                                 "thinking_extra_out_sensitivity": THINKING_EXTRA_OUT},
                 "cache_break_even_hit_rate": round(cache_break_even_hit_rate(), 3), "tokens": {}, "usd_per_conversation": {}}
    for cname, n in CALLS.items():
        out["tokens"][cname] = {"hit_95": tokens_per_conversation(n, 0.95), "hit_0": tokens_per_conversation(n, 0.0)}
    for strat in ("haiku", "haiku+sonnet", "sonnet", "opus"):
        for cname, n in CALLS.items():
            for mname, (cache, hit) in cache_modes.items():
                for think, extra in (("sem thinking", 0), ("thinking residual", THINKING_EXTRA_OUT)):
                    usd = n * strategy_call_usd(strat, cache, hit, extra)
                    out["usd_per_conversation"][f"{strat} | {cname} | {mname} | {think}"] = round(usd, 5)
    return out


def to_markdown(r: dict) -> str:
    L = ["> Tokens = ESTIMATIVA (+-35%); precos = tabela da skill claude-api (2026-10-06). Valores em USD; converter pelo cambio do dia.", "",
         f"Cache do prefixo estatico so compensa com taxa de acerto > **{r['cache_break_even_hit_rate'] * 100:.1f}%** "
         "(abaixo disso o premio de escrita de 1,25x custa mais que poupa).", "",
         "**Tokens por conversa (hit de cache 95%)**", "", "| Conversa | Entrada total | Dela, lida do cache | Saida |", "|---|---|---|---|"]
    for c, t in r["tokens"].items():
        L.append(f"| {c} | {t['hit_95']['input_total']:,} | {t['hit_95']['input_from_cache']:,} | {t['hit_95']['output_total']:,} |")
    L += ["", "**USD por conversa (sem thinking residual)**", "",
          "| Estrategia | Conversa | Sem cache | Cache hit 95% | Cache hit 0% | Por 1.000 conversas (hit 95%) |", "|---|---|---|---|---|---|"]
    u = r["usd_per_conversation"]
    names = {"haiku": "Haiku 5.5", "haiku+sonnet": "Haiku 5.5 + 10% escalonado p/ Sonnet 5.5", "sonnet": "Sonnet 5.5", "opus": "Opus 5.5"}
    for strat, label in names.items():
        for c in CALLS:
            k = lambda m: u[f"{strat} | {c} | {m} | sem thinking"]  # noqa: E731
            L.append(f"| {label} | {c} | ${k('sem cache'):.4f} | ${k('cache, hit 95% (trafego continuo)'):.4f} | "
                     f"${k('cache, hit 0% (trafego raro: so paga a escrita)'):.4f} | ${k('cache, hit 95% (trafego continuo)') * 1000:.2f} |")
    t = lambda s: u[f"{s} | sem fast-path (8 chamadas) | sem cache | thinking residual"]  # noqa: E731
    L += ["", f"Sensibilidade (conversa de 8 chamadas, sem cache): thinking residual de {THINKING_EXTRA_OUT} tokens/chamada leva o Haiku 5.5 de "
          f"${u['haiku | sem fast-path (8 chamadas) | sem cache | sem thinking']:.4f} para ${t('haiku'):.4f} e o Sonnet 5.5 de "
          f"${u['sonnet | sem fast-path (8 chamadas) | sem cache | sem thinking']:.4f} para ${t('sonnet'):.4f}."]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    result = run_all()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "cost_model.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    md = to_markdown(result)
    (a.out / "cost_model.md").write_text(md, encoding="utf-8")
    print(md)
    return result


if __name__ == "__main__":
    main()
