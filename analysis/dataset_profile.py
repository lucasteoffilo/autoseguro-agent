"""Perfil agregado do dataset de conversas.

Garantia de projeto: a saida contem SO numeros e rotulos de enum (tipos de mensagem, desfechos).
Nenhum texto de mensagem e impresso ou gravado. tests/test_analysis.py confere isso contra o dataset.

O parquet e dado externo: rode com -I e passe o caminho como argumento.
    python -I analysis/dataset_profile.py --parquet PATH --out analysis/results/dataset_profile.json [--ref-year 2026]

`--ref-year` e o ano usado como "hoje" para a idade do veiculo (a API usa o ano do relogio do servidor).
As regras de elegibilidade e de preco sao lidas de vendor/quote-service/data/plans.json, nao copiadas aqui.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PLANS = json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8"))
RULES = PLANS["regras"]
BASE_MONTHLY = {p["id"]: p["base_mensal"] for p in PLANS["planos"]}
HIGH_RISK = set(RULES["regiao_cep"]["prefixos_alto_risco"])
REGION_MULT = RULES["regiao_cep"]["multiplicador"]


def _mult(ranges: list[dict], value: int, lo: str, hi: str) -> float | None:
    """Multiplicador da faixa; None quando a regra recusa ou nenhuma faixa cobre o valor."""
    for r in ranges:
        if r[lo] <= value <= r[hi]:
            return None if r.get("recusar") else r["multiplicador"]
    return None


def _pct(part: float, whole: float, nd: int = 1) -> float:
    return round(float(part) / float(whole) * 100, nd) if whole else 0.0


def _py(obj):
    """Converte tipos numpy/pandas para tipos nativos antes de serializar."""
    if hasattr(obj, "item"):
        return obj.item()
    raise TypeError(f"nao serializavel: {type(obj)}")


def structure(df: pd.DataFrame) -> dict:
    per = df.groupby("conversation_id").size()
    outcomes = df.drop_duplicates("conversation_id").conversation_outcome.value_counts()
    return {
        "rows": len(df),
        "conversations": df.conversation_id.nunique(),
        "columns": list(df.columns),
        "null_cells": int(df.isna().sum().sum()),
        "channels": sorted(df.channel.unique().tolist()),
        "message_type": df.message_type.value_counts().to_dict(),
        "msgs_per_conversation": {"min": per.min(), "median": per.median(), "max": per.max()},
        "outcome_pct": {k: _pct(v, outcomes.sum()) for k, v in outcomes.items()},
    }


def ordering(df: pd.DataFrame) -> dict:
    g = df.sort_values(["conversation_id", "message_index"]).copy()
    g["ts"] = pd.to_datetime(g.timestamp)
    g["delta"] = g.groupby("conversation_id").ts.diff()
    neg = g.delta < pd.Timedelta(0)
    n_conv = g.conversation_id.nunique()
    n_bad = g[neg].conversation_id.nunique()
    return {
        "duplicate_conversation_message_index": int(df.duplicated(["conversation_id", "message_index"]).sum()),
        "conversations_with_time_regression": n_bad,
        "conversations_with_time_regression_pct": _pct(n_bad, n_conv),
        "messages_with_negative_delta": int(neg.sum()),
        "timestamp_min": str(g.ts.min()),
        "timestamp_max": str(g.ts.max()),
        "timezone_aware": g.ts.dt.tz is not None,
    }


def leakage(df: pd.DataFrame) -> dict:
    cols = ["conversation_outcome", "lead_idade_informada", "veiculo_texto"]
    first = df[df.message_index == 0]
    return {
        "max_distinct_values_per_conversation": {c: df.groupby("conversation_id")[c].nunique().max() for c in cols},
        "first_message_already_carries_labels": bool(first[cols].notna().all().all()),
    }


def build_conv(df: pd.DataFrame, ref_year: int) -> pd.DataFrame:
    """Uma linha por conversa, com elegibilidade calculada pelas regras reais da API."""
    conv = df.drop_duplicates("conversation_id").set_index("conversation_id").copy()
    conv["ano"] = conv.veiculo_texto.str.extract(r"((?:19|20)\d{2})")[0].astype(float)
    conv["idade"] = conv.lead_idade_informada
    conv["idade_veic"] = ref_year - conv.ano
    conv["m_idade"] = [_mult(RULES["faixa_etaria"], int(i), "idade_min", "idade_max") for i in conv.idade]
    conv["m_veic"] = [_mult(RULES["idade_veiculo"], int(a), "anos_min", "anos_max") if a == a else None
                      for a in conv.idade_veic]
    conv["rec_idade"] = conv.m_idade.isna()
    conv["rec_veic"] = conv.m_veic.isna()
    conv["inelegivel"] = conv.rec_idade | conv.rec_veic
    # CEP so pelo rotulo: um regex "solto" casa com o final dos telefones (ver pii()).
    cep = (df[df.sender_role == "lead"].message_body.str.extract(r"(?i)cep\s*(\d{5})-\d{3}")[0]
           .groupby(df.conversation_id).first())
    conv["cep_pref"] = cep.str[:2]
    conv["alto_risco"] = conv.cep_pref.isin(HIGH_RISK)
    return conv


def vehicle_and_age(df: pd.DataFrame, conv: pd.DataFrame, ref_year: int) -> dict:
    clean = conv.veiculo_texto.str.match(r"^\S+ [\w\- ]+ (19|20)\d{2}$").mean()
    n = len(conv)
    near_edge = conv.idade_veic.isin([20, 21]) | conv.idade.isin([75, 76])
    ine = conv[conv.inelegivel]
    return {
        "ref_year": ref_year,
        "veiculo_texto_clean_format_share": round(float(clean), 3),
        "veiculo_ano": {"min": conv.ano.min(), "max": conv.ano.max()},
        "idade": {"min": conv.idade.min(), "max": conv.idade.max()},
        "age_refused_pct": _pct(conv.rec_idade.sum(), n),
        "vehicle_refused_pct": _pct(conv.rec_veic.sum(), n),
        "ineligible_pct": _pct(conv.inelegivel.sum(), n),
        "ineligible_conversations": conv.inelegivel.sum(),
        "ineligible_by_outcome": ine.conversation_outcome.value_counts().to_dict(),
        "near_edge_conversations": near_edge.sum(),
        "high_risk_cep_pct": _pct(conv.alto_risco.sum(), conv.cep_pref.notna().sum()),
    }


def pii(df: pd.DataFrame) -> dict:
    body = df.message_body
    lead = df[df.sender_role == "lead"]
    vend = df[df.sender_role == "vendedor"]
    n_conv = df.conversation_id.nunique()
    pats = {
        "cpf_punctuated": r"\d{3}\.\d{3}\.\d{3}-\d{2}",
        "cpf_11_digits": r"(?<!\d)\d{11}(?!\d)",
        "email": r"[\w.+-]+@[\w-]+\.[\w.]+",
        "phone_plus55": r"\+55 \d{2} 9\d{4}-\d{4}",
        "plate_mercosul": r"\b[A-Z]{3}\d[A-Z]\d{2}\b",
        "cep_labelled": r"(?i)cep\s*\d{5}-\d{3}",
    }
    out = {}
    for name, p in pats.items():
        hit = body.str.contains(p, regex=True)
        out[name] = {"messages": hit.sum(), "conversations": df[hit].conversation_id.nunique(),
                     "conversation_share_pct": _pct(df[hit].conversation_id.nunique(), n_conv)}
    label = lead.message_body.str.extract(r"(?i)\b(cpf) \d")[0].dropna()
    out["cpf_label_spelling_in_lead_msgs"] = label.value_counts().to_dict()
    out["unlabelled_cep_regex_false_hits_on_phones"] = lead.message_body.str.contains(
        r"\+55 \d{2} 9\d{4}-\d{3}").sum()
    out["distinct_lead_names"] = lead.sender_name.nunique()
    out["vendor_msgs_greeting_by_first_name"] = vend.message_body.str.match(r"^Ola \w+,").sum()
    out["conversations_with_media_pct"] = _pct(df[df.message_type != "text"].conversation_id.nunique(), n_conv)
    return out


def vendor_price(df: pd.DataFrame, conv: pd.DataFrame) -> dict:
    vend = df[df.sender_role == "vendedor"]
    q = vend[vend.message_body.str.contains(r"plano \w+ por R\$")].copy()
    ex = q.message_body.str.extract(r"plano (\w+) por R\$ (\d+),(\d+)")
    q["plano"] = ex[0].str.lower()
    q["preco_vend"] = ex[1].astype(float) + ex[2].astype(float) / 100
    claims = q.message_body.str.extract(r"Cobre ([\w, ]+)\.")[0]
    q = q.set_index("conversation_id")[["plano", "preco_vend"]]
    j = q.join(conv[["idade", "idade_veic", "m_idade", "m_veic", "alto_risco", "inelegivel"]])
    el = j[~j.inelegivel].copy()
    el["real"] = [BASE_MONTHLY[p] * mi * mv * (REGION_MULT if r else 1.0)
                  for p, mi, mv, r in zip(el.plano, el.m_idade, el.m_veic, el.alto_risco)]
    ratio = el.preco_vend / el.real
    return {
        "vendor_quoted_conversations": len(q),
        "distinct_vendor_prices": q.preco_vend.nunique(),
        "distinct_coverage_claims": claims.nunique(),
        "vendor_price_mean_by_plan": q.groupby("plano").preco_vend.mean().round(1).to_dict(),
        "eligible_conversations_compared": len(el),
        "vendor_over_api_ratio": {"min": round(ratio.min(), 2), "median": round(ratio.median(), 2),
                                  "max": round(ratio.max(), 2)},
        "vendor_within_5pct_of_api_share": round(float((abs(ratio - 1) < 0.05).mean()), 3),
        "rank_corr_vendor_vs_api_price": round(float(el.preco_vend.rank().corr(el.real.rank())), 3),
        "rank_corr_vendor_price_vs_age": round(float(el.preco_vend.rank().corr(el.idade.rank())), 3),
    }, q


def outcome_signal(conv: pd.DataFrame, q: pd.DataFrame) -> dict:
    c = conv.join(q)
    c["ganho"] = c.conversation_outcome == "ganho"

    def rate(by) -> dict:
        return {str(k): round(float(v), 3) for k, v in c.groupby(by, observed=True).ganho.mean().items()}

    return {
        "overall_win_rate": round(float(c.ganho.mean()), 3),
        "win_rate_by_plan": rate("plano"),
        "win_rate_by_ineligible": rate("inelegivel"),
        "win_rate_by_high_risk_cep": rate("alto_risco"),
        "win_rate_by_price_band": rate(pd.cut(c.preco_vend, [0, 160, 260, 400])),
        "win_rate_by_age_band": rate(pd.cut(c.idade, [17, 29, 59, 75, 90])),
        "ineligible_but_won": int((c.ganho & c.inelegivel).sum()),
    }


def diversity(df: pd.DataFrame) -> dict:
    body = df.message_body
    lead = df[df.sender_role == "lead"]
    norm = lead.message_body.str.replace(r"\d", "#", regex=True)
    top10 = norm.value_counts().head(10).sum()
    scenario_words = {  # palavras NOSSAS: o que o dataset nao cobre e o agente precisa tratar
        "human_request": r"humano|atendente|gerente|supervis",
        "claim": r"sinistro|acidente|bati",
        "complaint": r"reclam|procon|absurdo|pessimo",
        "cancellation": r"cancel",
        "grace_period": r"car[eê]ncia",
        "system_error": r"erro|instab|fora do ar|indisponiv",
        "deductible_mention": r"franquia",
    }
    return {
        "lead_messages": len(lead),
        "distinct_lead_texts_digits_normalised": norm.nunique(),
        "top10_texts_share_of_lead_msgs_pct": _pct(top10, len(lead)),
        "scenario_keyword_hits": {k: int(body.str.contains(p, case=False, regex=True).sum())
                                  for k, p in scenario_words.items()},
        "media_messages_by_type": df[df.message_type != "text"].message_type.value_counts().to_dict(),
    }


def profile(parquet: Path, ref_year: int) -> dict:
    df = pd.read_parquet(parquet)
    conv = build_conv(df, ref_year)
    price, q = vendor_price(df, conv)
    return {
        "structure": structure(df),
        "ordering": ordering(df),
        "conversation_level_columns_replicated": leakage(df),
        "vehicle_and_age": vehicle_and_age(df, conv, ref_year),
        "pii": pii(df),
        "vendor_price_vs_api": price,
        "outcome_signal": outcome_signal(conv, q),
        "diversity_and_missing_scenarios": diversity(df),
    }


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parquet", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--ref-year", type=int, default=2026)
    a = ap.parse_args(argv)
    result = profile(a.parquet, a.ref_year)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=_py) + "\n", encoding="utf-8")
    v, e, o = result["vehicle_and_age"], result["vendor_price_vs_api"], result["ordering"]
    print(f"{a.out}: {result['structure']['rows']} msgs, {result['structure']['conversations']} conversas | "
          f"inelegiveis {v['ineligible_pct']}% | preco vendedor ~ API (+-5%): {e['vendor_within_5pct_of_api_share']} | "
          f"conversas c/ timestamp voltando: {o['conversations_with_time_regression_pct']}%")
    return result


if __name__ == "__main__":
    main()
