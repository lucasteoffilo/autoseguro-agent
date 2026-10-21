"""Os quatro cenarios da Etapa 2b com o MockLLM e a API de cotacao de teste: cotacao feliz, recusa, /quote fora do ar, pedido de humano.

Cada cenario roda pelo MESMO caminho de producao (`cli.build_orchestrator`: GuardedLLM -> Orchestrator -> QuoteGate -> QuoteClient HTTP) e grava no SQLite.
A transcricao e os registros impressos saem do BANCO (texto ja mascarado), nao do que o lead digitou: e a prova de que o que foi gravado e o que se ve.

    make api-test-up && make demo           # imprime tudo e grava var/scenarios/*.txt

O que e dado do lead (CPF, nome) e SINTETICO e montado em tempo de execucao por tests/synthetic_pii.py (nenhum literal de PII existe em arquivo do repo).
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from autoseguro.cli import build_orchestrator  # noqa: E402
from autoseguro.store import SequentialIds  # noqa: E402
from tests import synthetic_pii  # noqa: E402

API = "http://localhost:8100"
DEAD_QUOTE_API = "http://127.0.0.1:9"       # porta de descarte: a conexao e recusada na hora
SAMPLES = synthetic_pii.values()

SCENARIOS = [
    ("1-cotacao-feliz", API, None, [
        f"oi! sou a Maria Silva, meu cpf é {SAMPLES['cpf']}, quero cotar o seguro do meu carro",
        "é um onix 2019, tenho 34 anos e moro no cep 30130-010",
        "quero cobrir roubo, colisão, terceiros e vidros",
        "pode começar segunda que vem",
        "sim",
        "valeu!"]),
    ("2-recusa", API, None, [
        "oi, quero um seguro pro meu fusca",
        "é um fusca 1998, tenho 45 anos e moro no cep 01310-100",
        "só roubo e colisão",
        "começando dia 01/11/2026",
        "e se eu escolher outro plano?"]),
    ("3-quote-fora-do-ar", API, DEAD_QUOTE_API, [
        "oi",
        "é um onix 2019, tenho 34 anos e moro no cep 30130-010",
        "só roubo e colisão",
        "começando dia 01/11/2026"]),
    ("4-pedido-de-humano", API, None, [
        "oi",
        "é um onix 2019 e eu tenho 34 anos",
        "prefiro falar com uma pessoa",
        "alô?"]),
]


def api_is_up() -> bool:
    try:
        with urllib.request.urlopen(API + "/health", timeout=3) as r:  # noqa: S310
            return r.status == 200
    except OSError:
        return False


def short(text: str, n: int = 90) -> str:
    one = text.replace("\n", " ⏎ ")
    return one if len(one) <= n else one[: n - 1] + "…"


def render_transcript(store, trace: str) -> list[str]:
    out = []
    for m in store.messages(trace):
        who = "lead  " if m["role"] == "lead" else "agente"
        tag = "" if m["role"] == "lead" else f" [{m['kind']}]"
        lines = m["text"].splitlines() or [""]
        out.append(f"{who}>{tag} {lines[0]}")
        out += [f"        {line}" for line in lines[1:]]
    return out


def render_records(store, trace: str) -> list[str]:
    rec = store.reconstruct(trace)
    c = rec["conversation"]
    out = ["", "-- conversations --"]
    keys = ("trace_id", "mode", "llm_provider", "llm_model", "status", "handoff_reason", "failed_component", "handoff_detail", "llm_blocked_streak",
            "handoff_delivered_at", "handoff_external_ref")
    out += [f"  {k:<22} {c[k]}" for k in keys]
    out.append(f"  {'slots':<22} " + json.dumps({s: v["value"] if v["status"] != "pending" else f"pendente({v['reason']})" for s, v in json.loads(c['slots']).items()}, ensure_ascii=False))
    out += ["", "-- messages (id | seq | role | kind | status | quote_id | external_id) --"]
    for m in rec["messages"]:
        meta = json.loads(m["meta"])
        extra = {k: meta[k] for k in ("mask_kinds", "intent", "reply_source", "violations", "attempt", "hold_fired", "handoff_reason") if meta.get(k) not in (None, [], False)}
        out.append(f"  {m['id']} | {m['seq']:>2} | {m['role']:<5} | {m['kind']:<12} | {m['status']:<9} | {m['quote_id'] or '-':<8} | {m['external_id'] or '-'}")
        out.append(f"      {short(m['text'])}")
        if extra:
            out.append(f"      meta {json.dumps(extra, ensure_ascii=False)}")
    out += ["", "-- quotes (id | kind | status | plano | mensalidade | s) e quote_attempts (id | n | inicio | duracao | http | erro | decisao) --"]
    if not rec["quotes"]:
        out.append("  (nenhuma)")
    for q in rec["quotes"]:
        out.append(f"  {q['id']} | {q['kind']} | {q['status']} | {q['plano_id']} | {q['premio_mensal']} | {q['elapsed_s']}s")
        out.append(f"      request  {q['request']}")
        out.append(f"      response {short(q['response'] or '-', 140)}")
        for a in q["attempts"]:
            out.append(f"      {a['id']} | n={a['n']} | +{a['started_s']}s | {a['latency_s']}s | http={a['http_status']} | {a['error_kind']} | {a['decision']}")
    out += ["", "-- handoff_package --"]
    out += [("  " + line) for line in (json.dumps(rec["handoff"], ensure_ascii=False, indent=2).splitlines() if rec["handoff"] else ["(nenhum: a conversa nao foi a um humano)"])]
    out += ["", f"-- invariante do preco: R$ escritos pelo agente que nao estao em quotes.response: {store.money_not_in_quotes(trace)}"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "var" / "scenarios")
    args = ap.parse_args(argv)
    if not api_is_up():
        print(f"A API de teste nao responde em {API}. Suba com: make api-test-up", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    db = args.out / "scenarios.db"
    for f in args.out.glob("scenarios.db*"):
        f.unlink()
    ids = SequentialIds()
    report: list[str] = []
    for name, planos_api, quote_api, lead_lines in SCENARIOS:
        orc, store, info = build_orchestrator(llm_mode="mock", api_url=planos_api, quote_url=quote_api, db_path=db, ids=ids)
        trace = orc.start()
        results = [orc.handle(trace, line) for line in lead_lines]
        block = [f"{'=' * 100}", f"CENARIO {name}   (LLM {info['llm']}, /quote em {info['quote_api']}, trace {trace})", "=" * 100, "",
                 "-- transcricao (lida do SQLite: texto ja mascarado) --"]
        block += render_transcript(store, trace)
        block += [f"", f"   turnos: {len(results)} | mensagens terminais por turno: {[len(r.terminal) for r in results]} | segundos por turno: {[round(r.elapsed_s, 2) for r in results]}"]
        block += render_records(store, trace)
        if name.startswith("1-"):
            first = orc._llm.inner.calls[0].split("mensagem do lead:\n", 1)[1]
            block += ["", "-- o que o LLM RECEBEU na 1a mensagem (o texto ja mascarado; o CPF e o nome do lead nao saem do mascarador) --", f"  {first}"]
        report += block + [""]
        store.close()
    text = "\n".join(report)
    (args.out / "scenarios.txt").write_text(text, encoding="utf-8")
    print(text)
    print(f"[gravado em {args.out / 'scenarios.txt'} e {db}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
