"""Custo por conversa: tokens medios, modelo por passo e dolares.

ATENCAO: os tokens por chamada sao ESTIMATIVAS DE PROJETO (o prompt ainda nao existe), com incerteza de +-35%.
Os precos sao dados (skill claude-api, tabela em cache de 2026-10-06): CONFERIR antes de decidir. Nenhuma chamada
real foi feita. A medicao real vem do `usage` de cada resposta, registrado em messages.meta (ver docs/PLAN.md).

Desenho: UMA chamada por mensagem do lead que o fast-path estrito nao resolve, com saida estruturada
{slots, intent, reply}: o LLM extrai os slots E redige a resposta de conversa na mesma chamada. Escalonamento: repete a chamada
num modelo maior quando a saida vem invalida/ambigua (taxa abaixo). Mensagens de cotacao e de handoff sao template
(carregam numero e promessa), sem LLM.

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

# ESTIMATIVAS por chamada.
TOK_SLOTS_ONLY = {"static_prefix": 1500,  # ANTES: sistema + schema + regras + few-shots
                  "state": 150, "history": 250, "message": 40,
                  "output": 110}          # {slots, intent}
TOK = {"static_prefix": 2000,  # DEPOIS: + persona e tom, fatos do /planos, regras do guardrail, few-shots com resposta
       "state": 150,           # slots ja coletados (JSON)
       "history": 250,         # janela das ultimas ~6 mensagens, mascaradas
       "message": 40,          # mensagem atual
       "output": 190}          # 110 de {slots, intent} + ~80 de reply
CALLS = {"com fast-path (5 chamadas)": 5, "sem fast-path (8 chamadas)": 8, "conversa dificil (12 chamadas)": 12}
ESCALATION_RATE = 0.10
THINKING_EXTRA_OUT = 250       # sensibilidade: raciocinio residual cobrado como saida


def call_usd(model: str, cache: bool, hit: float = 0.0, extra_out: int = 0, tok: dict | None = None) -> float:
    tok = tok or TOK
    p, d = PRICES[model], tok["state"] + tok["history"] + tok["message"]
    s = tok["static_prefix"]
    if cache:
        inp = s * p["inp"] * (hit * p["read"] + (1 - hit) * WRITE_5M) + d * p["inp"]
    else:
        inp = (s + d) * p["inp"]
    return (inp + (tok["output"] + extra_out) * p["out"]) / 1e6


def strategy_call_usd(strategy: str, cache: bool, hit: float, extra_out: int, tok: dict | None = None) -> float:
    if strategy == "haiku":
        return call_usd("haiku-5-5", cache, hit, extra_out, tok)
    if strategy == "haiku+sonnet":  # a escalonada vai a outro modelo = outro cache; assume sem cache (pior caso)
        return call_usd("haiku-5-5", cache, hit, extra_out, tok) + ESCALATION_RATE * call_usd("sonnet-5-5", False, 0, extra_out, tok)
    if strategy == "sonnet":
        return call_usd("sonnet-5-5", cache, hit, extra_out, tok)
    return call_usd("opus-5-5", cache, hit, extra_out, tok)


def cache_break_even_hit_rate(write_mult: float = WRITE_5M, read_mult: float = 0.10) -> float:
    """Taxa de acerto a partir da qual cachear o prefixo compensa o premio de escrita."""
    return (write_mult - 1) / (write_mult - read_mult)


def tokens_per_conversation(n_calls: int, hit: float, tok: dict | None = None) -> dict:
    tok = tok or TOK
    s, d, o = tok["static_prefix"], tok["state"] + tok["history"] + tok["message"], tok["output"]
    return {"input_total": n_calls * (s + d), "input_from_cache": round(n_calls * s * hit), "output_total": n_calls * o}


def run_all() -> dict:
    cache_modes = {"sem cache": (False, 0.0), "cache, hit 95% (trafego continuo)": (True, 0.95),
                   "cache, hit 0% (trafego raro: so paga a escrita)": (True, 0.0)}
    out: dict = {"assumptions": {"prices_usd_per_mtok": PRICES, "tokens_per_call": TOK, "tokens_per_call_before_reply": TOK_SLOTS_ONLY,
                                 "calls_per_conversation": CALLS, "escalation_rate": ESCALATION_RATE,
                                 "write_5m_mult": WRITE_5M, "write_1h_mult": WRITE_1H, "thinking_extra_out_sensitivity": THINKING_EXTRA_OUT},
                 "cache_break_even_hit_rate": round(cache_break_even_hit_rate(), 3), "tokens": {}, "usd_per_conversation": {},
                 "before_after_reply_in_llm": {}}
    for cname, n in CALLS.items():
        out["tokens"][cname] = {"hit_95": tokens_per_conversation(n, 0.95), "hit_0": tokens_per_conversation(n, 0.0),
                                "hit_95_before": tokens_per_conversation(n, 0.95, TOK_SLOTS_ONLY)}
    for strat in ("haiku", "haiku+sonnet", "sonnet", "opus"):
        for cname, n in CALLS.items():
            for mname, (cache, hit) in cache_modes.items():
                for think, extra in (("sem thinking", 0), ("thinking residual", THINKING_EXTRA_OUT)):
                    usd = n * strategy_call_usd(strat, cache, hit, extra)
                    out["usd_per_conversation"][f"{strat} | {cname} | {mname} | {think}"] = round(usd, 5)
    n8 = CALLS["sem fast-path (8 chamadas)"]
    for strat in ("haiku", "haiku+sonnet", "sonnet"):
        for mname in ("sem cache", "cache, hit 95% (trafego continuo)"):
            cache, hit = cache_modes[mname]
            before = n8 * strategy_call_usd(strat, cache, hit, 0, TOK_SLOTS_ONLY)
            after = n8 * strategy_call_usd(strat, cache, hit, 0, TOK)
            out["before_after_reply_in_llm"][f"{strat} | {mname}"] = {
                "before_usd": round(before, 5), "after_usd": round(after, 5), "delta_pct": round((after / before - 1) * 100, 1)}
    return out


def to_markdown(r: dict) -> str:
    L = ["> Tokens = ESTIMATIVA (+-35%); precos = tabela da skill claude-api (2026-10-06). Valores em USD; converter pelo cambio do dia.", "",
         f"Cache do prefixo estatico so compensa com taxa de acerto > **{r['cache_break_even_hit_rate'] * 100:.1f}%** "
         "(abaixo disso o premio de escrita de 1,25x custa mais que poupa).", "",
         "**Tokens por conversa (LLM redige a resposta; hit de cache 95%)**", "",
         "| Conversa | Entrada total | Dela, lida do cache | Saida | Saida antes (so slots) |", "|---|---|---|---|---|"]
    for c, t in r["tokens"].items():
        L.append(f"| {c} | {t['hit_95']['input_total']:,} | {t['hit_95']['input_from_cache']:,} | {t['hit_95']['output_total']:,} | "
                 f"{t['hit_95_before']['output_total']:,} |")
    L += ["", "**USD por conversa (sem thinking residual)**", "",
          "| Estrategia | Conversa | Sem cache | Cache hit 95% | Cache hit 0% | Por 1.000 conversas (hit 95%) |", "|---|---|---|---|---|---|"]
    u = r["usd_per_conversation"]
    names = {"haiku": "Haiku 5.5", "haiku+sonnet": "Haiku 5.5 + 10% escalonado p/ Sonnet 5.5", "sonnet": "Sonnet 5.5", "opus": "Opus 5.5"}
    for strat, label in names.items():
        for c in CALLS:
            k = lambda m: u[f"{strat} | {c} | {m} | sem thinking"]  # noqa: E731
            L.append(f"| {label} | {c} | ${k('sem cache'):.4f} | ${k('cache, hit 95% (trafego continuo)'):.4f} | "
                     f"${k('cache, hit 0% (trafego raro: so paga a escrita)'):.4f} | ${k('cache, hit 95% (trafego continuo)') * 1000:.2f} |")
    L += ["", "**Impacto de o LLM redigir a resposta na mesma chamada (conversa de 8 chamadas)**", "",
          "| Estrategia / cache | Antes (so slots) | Depois (com reply) | Variacao |", "|---|---|---|---|"]
    for k, v in r["before_after_reply_in_llm"].items():
        L.append(f"| {k} | ${v['before_usd']:.4f} | ${v['after_usd']:.4f} | +{v['delta_pct']}% |")
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
