"""llm-ping: preflight de UMA requisicao, antes do smoke de 31.

    make llm-ping

Confere, com uma unica chamada real e uma mensagem escrita a mao (sem PII):
  1. que a autenticacao nao foi rejeitada (sem 401/403). Isso NAO prova que a chave vale: so um 200 prova; um 404, por exemplo, nao diz nada;
  2. que o provedor ACEITA O PEDIDO COMO MONTADO (json_schema, require_parameters, raciocinio), que e o que mais pode dar errado;
  3. que o modelo devolve saida valida no schema LOCAL (o provedor nao e confiado para o formato);
  4. a latencia desta amostra. E UMA amostra: nao e p95, e a 1a chamada pode incluir partida a frio.

Garantias: exatamente 1 requisicao (sem retentativa: se der 429 ou 5xx, diz e para), contada em var/smoke/quota.jsonl junto com o smoke; o gate de
PII e o guardrail rodam como em tudo (GuardedLLM); a chave NUNCA e impressa, nem o valor, nem o prefixo, nem o tamanho: so "configurada" ou
"AUSENTE". Nao consulta GET /key (seria uma segunda requisicao).

Codigos de saida: 0 tudo certo | 1 respondeu, mas a saida e invalida | 2 configuracao/chave | 3 payload inseguro | 4 cota | 5 erro inesperado
                  | 6 erro de protocolo (pedido recusado) | 7 servico instavel ou sem resposta (429, 5xx, timeout, conexao).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from tools import smoke_llm  # noqa: E402  (reusa load_env/load_fact_base; os testes neutralizam load_env pelo modulo)
from autoseguro.llm.config import ConfigError, LLMConfig  # noqa: E402
from autoseguro.llm.diagnose import describe_request, explain_failure  # noqa: E402
from autoseguro.llm.factory import make_llm  # noqa: E402
from autoseguro.llm.guarded import UnsafePayload  # noqa: E402
from autoseguro.llm.prompt import build_user_message  # noqa: E402
from autoseguro.llm.redact import redact  # noqa: E402
from autoseguro.llm.throttle import QuotaExhausted, QuotaLog, RateLimiter, ThrottledLLM, is_backoff_status, is_protocol_error  # noqa: E402
from tools.smoke_messages import MESSAGES, SMOKE_TODAY  # noqa: E402

_LOCAL = ("127.0.0.1", "localhost", "::1")


def _mark(ok: bool | None) -> str:
    return {True: "ok", False: "FALHA", None: "?"}[ok]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=None, help="sobrescreve LLM_MODEL")
    ap.add_argument("--base-url", default=None, help="sobrescreve LLM_BASE_URL (usado nos testes, com um servidor local)")
    ap.add_argument("--timeout", type=float, default=30.0, help="prazo da chamada (mede a latencia; o orcamento do produto e 6s)")
    ap.add_argument("--daily-quota", type=int, default=None, help="forca o limite diario local; sem isto, o ultimo limite que o provedor informou (gravado pelo smoke)")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "var" / "smoke", help="onde fica quota.jsonl (o mesmo do smoke)")
    a = ap.parse_args(argv)

    base = smoke_llm.load_fact_base()
    smoke_llm.load_env(ROOT / ".env")
    env = dict(os.environ)
    if a.model:
        env["LLM_MODEL"] = a.model
    if a.base_url:
        env["LLM_BASE_URL"] = a.base_url
    env.setdefault("LLM_TIMEOUT_S", str(a.timeout))
    key = None
    try:
        cfg = LLMConfig.from_env(env)
    except ConfigError as exc:
        print(f"CONFIGURACAO INVALIDA: {redact(str(exc))}", file=sys.stderr)
        return 2
    key = cfg.api_key
    local = (urlparse(cfg.base_url or "").hostname or "") in _LOCAL
    print(f"provedor: {cfg.provider} | modelo: {cfg.model} | pedido: {describe_request(cfg)}")
    print(f"chave: {'configurada' if key else ('dispensada (servidor local)' if local else 'AUSENTE')}  (o valor, o prefixo e o tamanho nunca sao mostrados)")
    if not key and not local:
        print(redact(cfg.missing_key_message()), "Copie .env.example para .env.", file=sys.stderr)
        return 2

    free = cfg.model.endswith(":free")
    known = QuotaLog(a.out_dir / "quota.jsonl", 1).last_remote_limit()  # o ping nao consulta o /key (e UMA requisicao); usa o que o smoke gravou
    limit, limit_src = (a.daily_quota, "--daily-quota") if a.daily_quota is not None else (
        (known, "ultimo limite informado pelo provedor") if known else (smoke_llm.FREE_DAILY_LIMIT, "padrao"))
    quota = QuotaLog(a.out_dir / "quota.jsonl", limit if free else 10**9)
    if free:
        print(f"cota hoje (UTC): {quota.used_today()}/{quota.daily_limit} usadas (contagem local; limite: {limit_src})")
        if quota.remaining() < 1:
            print("ABORTADO: nao ha requisicao disponivel hoje. Nada foi enviado.", file=sys.stderr)
            return 4

    msg = MESSAGES[0]
    assert msg.source == "hand-written", "so mensagem escrita a mao pode sair da maquina"
    user = build_user_message(today=SMOKE_TODAY, known_slots=msg.known_slots, asked_slot=msg.asked_slot, history=msg.history, message=msg.text)
    lead_texts = [t for role, t in msg.history if role == "lead"] + [msg.text] + [f"{k} {v}" for k, v in msg.known_slots.items()]
    throttled: ThrottledLLM | None = None

    def wrap(adapter):
        nonlocal throttled  # sem retentativa e sem disjuntor: e UMA requisicao, e quem decide o que fazer com a falha e o usuario
        throttled = ThrottledLLM(adapter, limiter=RateLimiter(smoke_llm.FREE_RPM), quota=quota, max_retries=0, fail_fast_on_protocol_error=False,
                                 max_consecutive_failures=0)
        return throttled

    try:
        gres = make_llm(cfg, base, wrap=wrap).turn(user, lead_texts=lead_texts)  # o gate de PII roda aqui dentro, ANTES de qualquer chamada
    except UnsafePayload as exc:
        print(f"ABORTADO: {redact(str(exc), [key])}", file=sys.stderr)
        return 3
    except QuotaExhausted as exc:
        print(f"ABORTADO: {redact(str(exc), [key])}", file=sys.stderr)
        return 4
    except ConfigError as exc:
        print(f"CONFIGURACAO INVALIDA: {redact(str(exc), [key])}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - o ping nunca deve vazar a chave num traceback
        print(f"ERRO INESPERADO: {type(exc).__name__}: {redact(str(exc), [key], limit=300)}", file=sys.stderr)
        return 5

    res = gres.result
    answered = res.http_status is not None  # chegou uma resposta HTTP
    protocol = is_protocol_error(res)
    transient = is_backoff_status(res) or res.error in ("timeout", "connection")
    accepted = None if (transient and not protocol) else (not protocol)
    auth = None if not answered else res.http_status not in (401, 403)
    valid = None if accepted is not True else res.output is not None
    served = f" (servido por {res.served_model})" if res.served_model and res.served_model != cfg.model else ""

    print(f"\n=== llm-ping | {cfg.provider} | {cfg.model}{served}")
    print(f"  [{_mark(auth)}] autenticacao nao rejeitada (sem 401/403)" + (f", resposta HTTP {res.http_status}" if answered else ", sem resposta HTTP"))
    print(f"  [{_mark(accepted)}] pedido aceito como montado ({describe_request(cfg)})")
    print(f"  [{_mark(valid)}] saida valida no schema local")
    limit = smoke_llm._derived_limit()
    verdict = "" if not res.output else (f" dentro do limite derivado por chamada ({limit:.2f}s)" if res.latency_s <= limit else f" ACIMA do limite derivado por chamada ({limit:.2f}s)")
    print(f"  [--] latencia desta amostra: {res.latency_s:.2f}s{verdict}. E UMA amostra, nao um p95; a 1a chamada pode incluir partida a frio.")
    if res.usage:
        print(f"  tokens  entrada {res.usage.input_tokens}  saida {res.usage.output_tokens}  raciocinio {res.usage.reasoning_tokens}")
    if res.output:
        words = len(res.output.reply.split())
        print(f"  reply de {words} palavras | guardrail: {'aprovado' if gres.reply_ok else 'REPROVOU (' + ', '.join(sorted({v.rule for v in gres.violations})) + ')'}")
    spent = throttled.requests if throttled else 0
    after = quota.remaining() if free else None
    plan = 1 + len(MESSAGES) * 2
    print(f"  requisicoes enviadas: {spent}" + (f" | hoje {quota.used_today()}/{quota.daily_limit}" if free else ""))
    if free:
        print(f"  o smoke planeja {plan} requisicoes: " + (f"cabe (restam {after})" if after >= plan else f"NAO cabe (restam {after}); ele vai abortar antes de enviar"))

    if res.output is not None:
        print("\nPING OK. Proximo passo: make smoke-llm")
        return 0
    print(f"\nFALHA ({res.error}).", file=sys.stderr)
    if res.detail:
        print(f"  detalhe do provedor: {redact(res.detail, [key])}", file=sys.stderr)
    print(f"  causa provavel: {explain_failure(cfg, res.error, res.http_status, res.detail)}", file=sys.stderr)
    if res.http_status == 429 and res.quota_kind == "daily":
        return 4
    return 6 if protocol else 7 if transient else 1


if __name__ == "__main__":
    sys.exit(main())
