"""smoke-llm: mede o LLM real com 15 mensagens ESCRITAS A MAO e SEM PII, antes de construir o agente em cima dele.

    make llm-ping                  # ANTES: 1 requisicao real (autenticacao, pedido aceito, saida valida, latencia da amostra)
    make smoke-llm                 # le LLM_* do ambiente ou de .env (ignorado pelo git); padrao: OpenRouter, modelo gratuito
    make smoke-llm-dry             # encanamento completo com um LLM de mentira, sem chave e sem rede

Cabe no free tier do OpenRouter (20 req/min, 50 req/dia sem creditos): 1 modelo, 2 repeticoes = 1 aquecimento + 15 x 2 = 31 requisicoes.
Respeita o rpm, conta CADA requisicao (inclusive as que falham) em var/smoke/quota.jsonl, confere a cota real em GET /key, trata 429 com
backoff e para se o limite for DIARIO. Aborta ANTES de gastar se a cota nao cobre o plano.

FALHA RAPIDO: nao sabemos se requisicao que falha conta na cota, entao o primeiro erro de PROTOCOLO (400, 401, 402, 403, 404... qualquer 4xx
menos 408 e 429) aborta na hora e custa UMA requisicao, nao 31. So o 429 por minuto e as falhas do servico (408, 5xx) entram em backoff; se
elas persistem em `--max-consecutive-failures` chamadas seguidas, aborta tambem.

Garantias: (1) cada mensagem e `hand-written`; (2) o gate de PII roda em TODO payload, ACIMA do adaptador (GuardedLLM), e a execucao ABORTA
se achar algo; (3) este script nao tem acesso ao dataset; (4) a chave nunca e impressa, gravada nem repetida em erro: tudo que sai passa por `redact`.
O relatorio vai para var/smoke/ (ignorado pelo git). 15 mensagens NAO certificam taxas: e um alarme contra problema grosseiro, nao um benchmark.

Codigos de saida: 0 passa (ou dry-run) | 1 nao passa | 2 configuracao/chave | 3 payload inseguro | 4 cota insuficiente | 5 erro inesperado
                  | 6 erro de protocolo (abortou na hora) | 7 servico instavel (backoff nao resolveu).
"""
from __future__ import annotations

import argparse
import functools
import json
import math
import os
import random
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from analysis import cost_model  # noqa: E402
from analysis.e2e_latency_sim import derive_llm_call_limit, project_turn_p95  # noqa: E402
from autoseguro import budgets  # noqa: E402
from autoseguro.facts import FactBase, strip_accents  # noqa: E402
from autoseguro.fastpath import fast_extract  # noqa: E402
from autoseguro.guardrail import Violation, check_reply  # noqa: E402
from autoseguro.llm.base import LLMResult, Usage  # noqa: E402
from autoseguro.llm.config import ConfigError, LLMConfig  # noqa: E402
from autoseguro.llm.diagnose import explain_failure  # noqa: E402
from autoseguro.llm.factory import make_llm  # noqa: E402
from autoseguro.llm.guarded import GuardedLLM, GuardedResult, UnsafePayload, assert_safe_to_send  # noqa: E402,F401  (reexportados)
from autoseguro.llm.prompt import build_system_prompt, build_user_message  # noqa: E402
from autoseguro.llm.redact import redact  # noqa: E402
from autoseguro.llm.schema import SlotValue, TurnOutput  # noqa: E402
from autoseguro.templates import RISK_INTENTS, Reply, select_reply  # noqa: E402
from autoseguro.llm.throttle import ProtocolError, QuotaExhausted, QuotaLog, RateLimiter, ServiceUnstable, ThrottledLLM  # noqa: E402
from tools.smoke_messages import MESSAGES, SMOKE_TODAY, SmokeMessage  # noqa: E402

MODEL_PRICE_KEY = {"claude-haiku-5-5": "haiku-5-5", "claude-sonnet-5-5": "sonnet-5-5", "claude-opus-5-5": "opus-5-5"}
FREE_DAILY_LIMIT, FREE_RPM = 50, 20


def load_env(path: Path) -> None:
    """Le KEY=VALUE de um .env sem sobrescrever o que ja esta no ambiente. Nunca imprime valores.

    Se o arquivo nao puder ser lido (ex.: uma regra de sandbox ou de permissao nega a leitura), segue com o ambiente como esta."""
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        if value:
            os.environ.setdefault(key.strip(), value)


def load_fact_base() -> FactBase:
    return FactBase.from_planos(json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8")))


def norm(slot: str, value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if slot in ("idade", "veiculo_ano"):
        return str(int(digits)) if digits else value.strip().lower()
    if slot == "cep":
        return digits
    return value.strip().lower()


# --- LLM de mentira (--dry-run e testes) --------------------------------------------------------------------------
class DryRunLLM:
    """Responde com o gabarito, so para provar o encanamento. Os numeros que ele gera NAO valem nada."""

    provider = "dry-run"

    def __init__(self, model: str, fact_base: FactBase, seed: int = 1) -> None:
        self.model, self.system_prompt = model, build_system_prompt(fact_base)
        self._rng = random.Random(seed)
        self._by_text = {m.text: m for m in MESSAGES}

    def turn(self, user_message: str) -> LLMResult:
        msg = next((m for t, m in self._by_text.items() if user_message.endswith(t)), None)
        assert msg is not None, "mensagem desconhecida no dry-run"
        slots = [SlotValue(s, v, False) for s, v in msg.expected.items()] + [SlotValue(s, "?", True) for s in msg.expect_ambiguous]
        carencia = "carencia" in msg.must_cite
        reply = ("Roubo e furto só passam a valer 30 dias depois do início da vigência." if carencia else "Anotado! Pode me contar mais um pouco?")
        out = TurnOutput(tuple(slots), sorted(msg.intents)[0], ("carencia",) if carencia else (), reply)
        return LLMResult(out, None, self._rng.lognormvariate(math.log(0.9), 0.4), Usage(2400, 130), "end_turn", served_model=self.model)


# --- execucao e pontuacao ---------------------------------------------------------------------------------------------
@dataclass
class CallRecord:
    msg_id: str
    model: str
    repeat: int
    warmup: bool
    error: str | None
    latency_s: float
    usage: dict | None
    output: dict | None
    score: dict
    served_model: str | None = None
    http_status: int | None = None


def score_call(msg: SmokeMessage, res: LLMResult, base: FactBase, violations: tuple[Violation, ...] | None = None, reply: Reply | None = None) -> dict:
    s: dict = {"valid": res.output is not None}
    if res.output is None:
        return s
    out, wrong_silent, kinds = res.output, 0, {}
    ambiguous = out.ambiguous()
    for slot, want in msg.expected.items():
        got = out.entries(slot)
        if not got:
            kinds[slot] = "omitted"
        elif norm(slot, got[0].value) == norm(slot, want) and slot not in ambiguous:
            kinds[slot] = "correct"
        elif norm(slot, got[0].value) == norm(slot, want):
            kinds[slot] = "correct_flagged"
        elif slot in ambiguous:
            kinds[slot] = "wrong_flagged"
        else:
            kinds[slot] = "SILENT_WRONG"
            wrong_silent += 1
    for slot in msg.expect_ambiguous:
        if out.entries(slot) and slot not in ambiguous:
            kinds[slot] = "SILENT_VALUE_ON_AMBIGUOUS"
            wrong_silent += 1
        else:
            kinds[slot] = "ok_flagged_or_absent"
    for slot in {e.slot for e in out.slots} - set(msg.expected) - set(msg.expect_ambiguous):
        if slot not in ambiguous:
            kinds[slot] = "SILENT_EXTRA"
            wrong_silent += 1
    if violations is None:
        violations = check_reply(out.reply, facts_used=out.facts_used, base=base, lead_texts=lead_texts_of(msg))
    plain = strip_accents(out.reply).lower()
    if reply is None:  # o que de fato chega ao lead: template nas intencoes de risco, LLM (sob o guardrail) nas neutras
        reply = select_reply(GuardedResult(res, violations), base, lead_text=msg.text)
    delivered = strip_accents(reply.text).lower()
    risk_message = msg.intents <= RISK_INTENTS
    fast = fast_extract(msg.asked_slot, msg.text, today=SMOKE_TODAY)
    llm_value = out.value(msg.asked_slot) if msg.asked_slot else None
    s.update(slot_outcomes=kinds, silent_wrong=wrong_silent, intent_ok=out.intent in msg.intents,
             guardrail_ok=not violations, violations=sorted({v.rule for v in violations}),
             forbidden_leak=[f for f in msg.forbidden_in_reply if strip_accents(f).lower() in plain],
             cited_required=set(msg.must_cite) <= set(out.facts_used), reply_words=len(out.reply.split()),
             # --- o que foi ENTREGUE ao lead (os criterios usam estes; as chaves acima descrevem o que o LLM escreveu, mesmo quando foi descartado) ---
             llm_reply=out.intent not in RISK_INTENTS, delivered_source=reply.source, delivered_text=reply.text,
             delivered_forbidden_leak=[f for f in msg.forbidden_in_reply if strip_accents(f).lower() in delivered],
             delivered_cited_required=set(msg.must_cite) <= set(reply.facts_used),
             risk_message=risk_message, risk_recognized=(out.intent in RISK_INTENTS) if risk_message else None,
             fast_value=fast, fast_diverges=bool(fast is not None and (llm_value is None or norm(msg.asked_slot, llm_value) != norm(msg.asked_slot, fast))))
    return s


def lead_texts_of(msg: SmokeMessage) -> list[str]:
    return [t for role, t in msg.history if role == "lead"] + [msg.text] + [f"{k} {v}" for k, v in msg.known_slots.items()]


def run_model(llm: GuardedLLM, base: FactBase, messages, repeats: int, progress=None) -> list[CallRecord]:
    """Uma chamada de aquecimento (a 1a com um esquema novo pode pagar compilacao ou partida a frio) fica FORA das estatisticas."""
    assert isinstance(llm, GuardedLLM), "o smoke so aceita um cliente guardado (gate de PII + guardrail): use make_llm()"
    records: list[CallRecord] = []
    plan = [(messages[0], 0, True)] + [(m, r, False) for r in range(1, repeats + 1) for m in messages]
    for i, (msg, rep, warm) in enumerate(plan, 1):
        assert msg.source == "hand-written", f"{msg.id}: so mensagens escritas a mao podem sair da maquina"
        user = build_user_message(today=SMOKE_TODAY, known_slots=msg.known_slots, asked_slot=msg.asked_slot, history=msg.history, message=msg.text)
        gres = llm.turn(user, lead_texts=lead_texts_of(msg))  # o gate de PII roda aqui dentro, ANTES de qualquer chamada
        res = gres.result
        records.append(CallRecord(msg.id, llm.model, rep, warm, res.error, res.latency_s,
                                  None if res.usage is None else res.usage.__dict__,
                                  None if res.output is None else {"slots": [s.__dict__ for s in res.output.slots], "intent": res.output.intent,
                                                                   "facts_used": list(res.output.facts_used), "reply": res.output.reply},
                                  score_call(msg, res, base, gres.violations), res.served_model, res.http_status))
        if progress:
            progress(i, len(plan), msg.id, res.error, res.latency_s)
    return records


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p / 100 * len(xs)))] if xs else float("nan")


@functools.lru_cache(maxsize=1)
def _derived_limit() -> float:
    return derive_llm_call_limit(n=15_000)["binding_llm_call_p95_max_s"]


def summarize(records: list[CallRecord], model: str) -> dict:
    rs = [r for r in records if not r.warmup]
    ok = [r for r in rs if r.score.get("valid")]
    lat = [r.latency_s for r in rs if r.error is None]
    neutral = [r for r in ok if r.score.get("llm_reply", True)]   # replies redigidos pelo LLM (as intencoes de risco saem por template)
    risk = [r for r in ok if r.score.get("risk_message")]
    words = [r.score["reply_words"] for r in neutral]
    usage = [r.usage for r in rs if r.usage]
    price = cost_model.PRICES.get(MODEL_PRICE_KEY.get(model, ""), None)
    per_call_usd = 0.0 if model.endswith(":free") else None
    if price and usage:
        per_call_usd = sum((u["input_tokens"] * price["inp"] + u["cache_read_tokens"] * price["inp"] * price["read"]
                            + u["cache_write_tokens"] * price["inp"] * cost_model.WRITE_5M + u["output_tokens"] * price["out"]) / 1e6
                           for u in usage) / len(usage)
    fast_applies = [r for r in ok if r.score["fast_value"] is not None]
    projection = project_turn_p95(lat) if lat else None
    mean = lambda key: round(sum(u[key] for u in usage) / len(usage)) if usage else None  # noqa: E731
    s = {
        "model": model, "served_models": sorted({r.served_model for r in records if r.served_model}), "calls": len(rs),
        "errors": {e: sum(r.error == e for r in rs) for e in sorted({r.error for r in rs if r.error})},
        "warmup_latency_s": next((round(r.latency_s, 2) for r in records if r.warmup), None),
        "latency_s": {"p50": round(pct(lat, 50), 2), "p95": round(pct(lat, 95), 2), "p99": round(pct(lat, 99), 2), "max": round(max(lat), 2)} if lat else None,
        "projected_turn_p95_s": projection,
        "mean_input_tokens": mean("input_tokens"), "mean_output_tokens": mean("output_tokens"), "mean_cache_read_tokens": mean("cache_read_tokens"),
        "mean_reasoning_tokens": mean("reasoning_tokens") if usage and "reasoning_tokens" in usage[0] else None,
        "output_tokens_per_s": round(sum(r.usage["output_tokens"] / r.latency_s for r in rs if r.usage and r.latency_s) / max(1, len(usage)), 1) if usage else None,
        "usd_per_call": None if per_call_usd is None else round(per_call_usd, 6),
        "valid_output_rate": round(len(ok) / len(rs), 3) if rs else 0.0,
        "silent_wrong": sum(r.score["silent_wrong"] for r in ok),
        "omissions": sum(v == "omitted" for r in ok for v in r.score["slot_outcomes"].values()),
        "intent_accuracy": round(sum(r.score["intent_ok"] for r in ok) / len(ok), 3) if ok else 0.0,
        "neutral_replies": len(neutral),
        "guardrail_pass_rate": round(sum(r.score["guardrail_ok"] for r in neutral) / len(neutral), 3) if neutral else 1.0,
        "guardrail_violations": {rule: sum(rule in r.score["violations"] for r in neutral) for rule in sorted({v for r in neutral for v in r.score["violations"]})},
        "risk_calls": len(risk),
        "risk_recognition_rate": round(sum(bool(r.score["risk_recognized"]) for r in risk) / len(risk), 3) if risk else None,
        "delivered": {src: sum(r.score.get("delivered_source", "llm") == src for r in ok) for src in sorted({r.score.get("delivered_source", "llm") for r in ok})},
        "llm_reply_on_risk_turns_would_leak": sum(len(r.score["forbidden_leak"]) for r in ok if not r.score.get("llm_reply", True)),
        "forbidden_leaks": sum(len(r.score.get("delivered_forbidden_leak", r.score["forbidden_leak"])) for r in ok),
        "required_fact_cited": all(r.score.get("delivered_cited_required", r.score["cited_required"]) for r in ok),
        "reply_words": {"mean": round(sum(words) / len(words), 1), "p95": pct(words, 95), "max": max(words),
                        "share_le_target": round(sum(w <= budgets.REPLY_TARGET_WORDS for w in words) / len(words), 3)} if words else None,
        "fast_path": {"applicable_calls": len(fast_applies), "abstained_calls": len(ok) - len(fast_applies),
                      "divergences": sum(r.score["fast_diverges"] for r in ok)},
        "derived_llm_call_limit_p95_s": _derived_limit(),
    }
    s["checks"] = {
        "0 extracoes erradas em silencio": s["silent_wrong"] == 0,
        "saida estruturada valida em 100%": s["valid_output_rate"] == 1.0,
        f"p95 projetado do turno sem cotacao <= {budgets.TURN_P95_NO_QUOTE_S:.0f}s": bool(projection and projection["no_quote_p95_s"] <= budgets.TURN_P95_NO_QUOTE_S),
        f"p95 projetado do turno com cotacao <= {budgets.TURN_P95_WITH_QUOTE_S:.0f}s": bool(projection and projection["with_quote_p95_s"] <= budgets.TURN_P95_WITH_QUOTE_S),
        "guardrail aprova >= 80% dos replies redigidos pelo LLM (as intencoes de risco saem por template)": s["guardrail_pass_rate"] >= 0.8,
        "intencao de risco reconhecida em 100% das mensagens de risco": s["risk_recognition_rate"] in (None, 1.0),
        f"reply curto: >= 90% com <= {budgets.REPLY_TARGET_WORDS} palavras e nenhum acima de {budgets.REPLY_HARD_MAX_WORDS}":
            bool(words) and s["reply_words"]["share_le_target"] >= 0.9 and max(words) <= budgets.REPLY_HARD_MAX_WORDS,
        "nenhum reply com termo proibido": s["forbidden_leaks"] == 0,
    }
    s["passes"] = all(s["checks"].values())
    s["fast_path_verdict"] = "REMOVER (divergiu do LLM)" if s["fast_path"]["divergences"] else "sem divergencia nesta amostra (ainda precisa de ganho medido para ligar)"
    return s


def print_report(summaries: list[dict], dry: bool) -> None:
    if dry:
        print("\n*** DRY-RUN: LLM de mentira. Estes numeros provam o ENCANAMENTO e nao valem nada como medicao. ***")
    for s in summaries:
        served = f" (servido por {', '.join(s['served_models'])})" if s["served_models"] and s["served_models"] != [s["model"]] else ""
        print(f"\n=== {s['model']}{served} | {s['calls']} chamadas (aquecimento {s['warmup_latency_s']}s, fora das estatisticas)")
        if s["errors"]:
            print(f"  ERROS: {s['errors']}")
        if s["latency_s"]:
            l, p = s["latency_s"], s["projected_turn_p95_s"]
            print(f"  latencia por chamada  p50 {l['p50']}s  p95 {l['p95']}s  p99 {l['p99']}s  max {l['max']}s   (limite derivado do criterio: p95 <= {s['derived_llm_call_limit_p95_s']}s)")
            print(f"  p95 do TURNO projetado  sem cotacao {p['no_quote_p95_s']}s (criterio {budgets.TURN_P95_NO_QUOTE_S:.0f}s)   com cotacao {p['with_quote_p95_s']}s (criterio {budgets.TURN_P95_WITH_QUOTE_S:.0f}s)")
        print(f"  tokens medios  entrada {s['mean_input_tokens']}  saida {s['mean_output_tokens']}  raciocinio {s['mean_reasoning_tokens']}  saida/s {s['output_tokens_per_s']}   US$/chamada {s['usd_per_call']}")
        print(f"  extracao  erros silenciosos {s['silent_wrong']}   omissoes {s['omissions']}   intent {s['intent_accuracy']}   saida valida {s['valid_output_rate']}")
        print(f"  guardrail aprova {s['guardrail_pass_rate']} (de {s['neutral_replies']} replies do LLM)  violacoes {s['guardrail_violations']}   reply {s['reply_words']}")
        print(f"  entregue ao lead {s['delivered']} | intencao de risco reconhecida {s['risk_recognition_rate']} em {s['risk_calls']} chamadas "
              f"| termos proibidos que o LLM teria escrito nas turnos de risco: {s['llm_reply_on_risk_turns_would_leak']}")
        print(f"  fast-path {s['fast_path']}  ->  {s['fast_path_verdict']}")
        for name, ok in s["checks"].items():
            print(f"    [{'ok' if ok else 'FALHA'}] {name}")
        print(f"  VEREDITO: {'PASSA' if s['passes'] else 'NAO PASSA'}   (15 mensagens: alarme, nao benchmark)")


def remote_free_remaining(cfg: LLMConfig, timeout_s: float = 10.0) -> int | None:
    """Cota REAL do dia segundo o OpenRouter (GET /key -> data.free_model_daily_requests.remaining). None se nao deu para saber."""
    if cfg.provider != "openrouter" or not cfg.base_url or not cfg.api_key:
        return None
    req = urllib.request.Request(cfg.base_url.rstrip("/") + "/key", headers={"Authorization": f"Bearer {cfg.api_key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:  # noqa: S310 - URL validada na configuracao
            data = json.loads(r.read()).get("data", {})
        remaining = data.get("free_model_daily_requests", {}).get("remaining")
        return remaining if isinstance(remaining, int) and not isinstance(remaining, bool) else None
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return None


def _report_abort(kind: str, res: LLMResult, cfg: LLMConfig, key: str | None, done: int, planned: int, throttled: ThrottledLLM | None,
                  quota: QuotaLog, free: bool, *, fast: bool) -> None:
    """Aborto do smoke por falha do provedor: diz o que aconteceu, a causa provavel e QUANTAS requisicoes foram gastas. Tudo mascarado."""
    spent = throttled.requests if throttled else 0
    lines = [f"ABORTADO por {kind} ({res.error}) na chamada {done + 1} de {planned}."]
    if res.detail:
        lines.append(f"  detalhe do provedor: {res.detail}")
    lines.append(f"  causa provavel: {explain_failure(cfg, res.error, res.http_status, res.detail)}")
    today = f" (hoje {quota.used_today()}/{quota.daily_limit})" if free else ""
    rest = planned - done - 1
    lines.append(f"  requisicoes gastas nesta execucao: {spent}{today}. As {rest} restantes do plano NAO foram enviadas"
                 + (" (um erro de protocolo nao se repete: custa uma requisicao, nao o plano)." if fast else "."))
    print(redact("\n".join(lines), [key]), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None, help="sobrescreve LLM_MODEL")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--rpm", type=int, default=FREE_RPM, help="requisicoes por minuto (padrao: o limite do free tier)")
    ap.add_argument("--daily-quota", type=int, default=FREE_DAILY_LIMIT, help="requisicoes por dia UTC, so para modelos :free")
    ap.add_argument("--max-retries", type=int, default=3, help="tentativas extras ao receber 429 por minuto")
    ap.add_argument("--backoff-base-s", type=float, default=5.0, help="espera base do backoff de 429 e 5xx (dobra a cada tentativa)")
    ap.add_argument("--max-consecutive-failures", type=int, default=3,
                    help="aborta depois de N chamadas seguidas que ainda falham de servico/transporte apos o backoff (0 desliga)")
    ap.add_argument("--timeout", type=float, default=30.0, help="prazo por chamada NO SMOKE (mede a distribuicao; o orcamento do produto e 6s)")
    ap.add_argument("--no-remote-check", action="store_true", help="nao consulta GET /key")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "var" / "smoke")
    ap.add_argument("--base-url", default=None, help="sobrescreve LLM_BASE_URL (usado nos testes, com um servidor local)")
    a = ap.parse_args(argv)

    base = load_fact_base()
    load_env(ROOT / ".env")
    env = dict(os.environ)
    if a.model:
        env["LLM_MODEL"] = a.model
    if a.base_url:
        env["LLM_BASE_URL"] = a.base_url
    env.setdefault("LLM_TIMEOUT_S", str(a.timeout))
    key = None
    try:
        cfg = LLMConfig.from_env(env)
        key = cfg.api_key
        if not a.dry_run and not cfg.api_key and (urlparse(cfg.base_url or "").hostname or "") not in ("127.0.0.1", "localhost"):
            print(cfg.missing_key_message(), "Copie .env.example para .env, ou rode `make smoke-llm-dry`.", file=sys.stderr)
            return 2
    except ConfigError as exc:
        print(f"CONFIGURACAO INVALIDA: {redact(str(exc))}", file=sys.stderr)
        return 2

    messages, planned = MESSAGES, 1 + len(MESSAGES) * a.repeats
    free = cfg.model.endswith(":free")
    quota = QuotaLog(a.out_dir / "quota.jsonl", a.daily_quota if free else 10**9)
    throttled: ThrottledLLM | None = None
    done = 0  # chamadas concluidas; se algo abortar, a chamada que falhou e done + 1
    print(f"provedor: {cfg.provider} | modelo: {cfg.model} | saida estruturada: {cfg.structured_output} | raciocinio: {cfg.reasoning_effort or 'nao enviado'}")
    try:
        if a.dry_run:
            llm = GuardedLLM(DryRunLLM(cfg.model, base), base)
        else:
            if free:
                remote = None if a.no_remote_check else remote_free_remaining(cfg)
                available = min(x for x in (quota.remaining(), remote) if x is not None)
                print(f"cota hoje (UTC): local {quota.used_today()}/{quota.daily_limit} usadas | OpenRouter diz restar {remote if remote is not None else 'desconhecido'}")
                if available < planned:
                    print(f"ABORTADO: o plano precisa de {planned} requisicoes e restam {available}. Nada foi enviado.", file=sys.stderr)
                    return 4
            else:
                print("modelo nao-:free: sem cota diaria local (o limite de rpm continua valendo)")

            def wrap(adapter):
                nonlocal throttled
                throttled = ThrottledLLM(adapter, limiter=RateLimiter(a.rpm), quota=quota, max_retries=a.max_retries, backoff_base_s=a.backoff_base_s,
                                         on_event=lambda m: print(f"    {m}"), fail_fast_on_protocol_error=True,
                                         max_consecutive_failures=a.max_consecutive_failures)
                return throttled

            llm = make_llm(cfg, base, wrap=wrap)

        def progress(i: int, n: int, mid: str, err: str | None, lat: float) -> None:
            nonlocal done
            done = i
            print(f"  [{i}/{n}] {mid:34s} {'ok' if err is None else err:14s} {lat:5.1f}s")

        records = run_model(llm, base, messages, a.repeats, progress=progress)
    except UnsafePayload as exc:
        print(f"ABORTADO: {redact(str(exc), [key])}", file=sys.stderr)
        return 3
    except ProtocolError as exc:
        _report_abort("erro de protocolo", exc.result, cfg, key, done, planned, throttled, quota, free, fast=True)
        return 6
    except ServiceUnstable as exc:
        _report_abort(f"servico instavel ({exc.failures} falhas seguidas)", exc.result, cfg, key, done, planned, throttled, quota, free, fast=False)
        return 7
    except QuotaExhausted as exc:
        print(f"ABORTADO: {redact(str(exc), [key])}. As chamadas feitas ate aqui ficam em {a.out_dir / 'quota.jsonl'}", file=sys.stderr)
        return 4
    except ConfigError as exc:
        print(f"CONFIGURACAO INVALIDA: {redact(str(exc), [key])}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - o smoke nunca deve vazar a chave num traceback
        print(f"ERRO INESPERADO: {type(exc).__name__}: {redact(str(exc), [key], limit=300)}", file=sys.stderr)
        return 5

    summary = summarize(records, cfg.model)
    print_report([summary], a.dry_run)
    requests = throttled.requests if throttled else None
    if throttled:
        print(f"\nrequisicoes enviadas nesta execucao: {requests} (retries por 429: {throttled.retries}) | hoje: {quota.used_today()}/{quota.daily_limit}")
    a.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ("-dry" if a.dry_run else "")
    path = a.out_dir / f"smoke-{stamp}.json"
    host = cfg.base_url.split("//")[-1].split("/")[0] if cfg.base_url else None
    report = {"dry_run": a.dry_run, "today": SMOKE_TODAY.isoformat(),
              "provider": "dry-run" if a.dry_run else cfg.provider, "model": cfg.model, "served_models": summary["served_models"],
              "config": {"base_url_host": host, "structured_output": cfg.structured_output, "reasoning_effort": cfg.reasoning_effort,
                         "max_tokens": cfg.max_tokens, "timeout_s": cfg.timeout_s, "temperature": cfg.temperature},
              "requests_sent": requests, "retries_on_429": throttled.retries if throttled else None,
              "quota": {"limit": quota.daily_limit if free else None, "used_today": quota.used_today() if free else None},
              "summary": summary, "calls": [r.__dict__ for r in records]}
    path.write_text(redact(json.dumps(report, ensure_ascii=False, indent=2, default=str), [key]) + "\n", encoding="utf-8")
    shown = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f"relatorio completo (com cada reply, para ler a olho): {shown}")
    return 0 if summary["passes"] or a.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
