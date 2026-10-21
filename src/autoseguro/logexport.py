"""Exporta o log de UMA execucao (uma conversa, pelo `trace_id`) em Markdown: transcricao, decisoes do agente, cotacoes com todas as tentativas da /quote, slots e o pacote de handoff.

Tudo vem do SQLite, onde so existe texto JA MASCARADO (inclusive o texto do modelo que o guardrail barrou, gravado mascarado e truncado, ou so a marca "texto omitido: pii"). Mesmo assim o Markdown passa por uma varredura antes de ser escrito (detector de PII do gate de envio, CPF com digitos
verificadores validos, chaves): se achar algo, NAO exporta (`ExportRefused`) e diz o tipo, nunca o trecho. A secao "Verificacoes" repete os criterios E3 do PLAN para o autor saber,
antes de copiar o log para o README, se esta execucao serve: LLM real registrado, cotacao ok, retry visivel, todo "R$" existe numa cotacao ok, sem PII.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .masker import cpf_is_valid
from .pii import find_pii
from .store import Store, money_in

_ELEVEN = re.compile(r"(?<![\d.-])\d{11}(?![\d.-])")


class ExportRefused(Exception):
    """O Markdown ainda tem PII ou segredo. `kinds` diz o tipo; o trecho nunca e mostrado."""

    def __init__(self, kinds: list[str]) -> None:
        super().__init__("exportacao recusada: " + ", ".join(kinds))
        self.kinds = kinds


def scan(text: str) -> list[str]:
    found = find_pii(text)
    if any(cpf_is_valid(m.group(0)) for m in _ELEVEN.finditer(text)):
        found.append("cpf_valido")
    return found


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ⏎ ")


def _fmt_meta(meta: dict[str, Any]) -> str:
    keep = ("intent", "reply_source", "facts_used", "violations", "asked", "precheck", "precheck_divergence", "precheck_kind", "refusal_kind", "media", "attempt",
            "llm_latency_s", "llm_error", "llm_error_detail", "llm_error_detail_omitted", "hold_fired", "quote_elapsed_s", "handoff_reason", "mask_kinds", "truncated")
    parts = []
    for k in keep:
        v = meta.get(k)
        if v in (None, [], False, ""):
            continue
        parts.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
    if meta.get("usage"):
        parts.append(f"tokens={meta['usage'].get('input_tokens')}→{meta['usage'].get('output_tokens')}")
    return "; ".join(parts) or "—"


# --- de onde veio cada texto que o lead leu --------------------------------------------------------------------------------------------------------
# Cada mensagem do agente (menos o "um instante") traz em `meta` o `reply_source` e, se o guardrail barrou o texto do modelo, as regras (`violations`). Seis origens:
BUCKETS = (
    ("llm", "Texto do modelo, entregue", "`llm`"),
    ("barrado", "Texto do modelo barrado pelo guardrail", "`template_fallback`"),
    ("sem_saida", "Sem saída utilizável do modelo (falha, filtro do provedor, saída inválida)", "`template_fallback`, `sem_saida`"),
    ("trocado_orquestrador", "Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII)", "`template_question`"),
    ("trocado_produto", "Trocado por desenho (a pergunta de necessidade e as confirmações são do produto)", "`template_question`"),
    ("template", "Template por desenho (risco, cotação, recusa, handoff, estado, mídia)", "`template_*`"),
)
CANDIDATES = ("llm", "barrado", "sem_saida", "trocado_orquestrador")   # as vezes em que o texto do modelo PODERIA ter chegado ao lead


@dataclass
class Origins:
    counts: Counter = field(default_factory=Counter)
    rules: Counter = field(default_factory=Counter)      # regra do guardrail -> quantas mensagens barrou
    sources: Counter = field(default_factory=Counter)    # reply_source dos templates por desenho

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def candidates(self) -> int:
        return sum(self.counts[b] for b in CANDIDATES)

    def __iadd__(self, other: Origins) -> Origins:
        self.counts += other.counts
        self.rules += other.rules
        self.sources += other.sources
        return self


def classify_reply(meta: dict[str, Any]) -> tuple[str, list[str]]:
    """(origem, regras do guardrail) de uma mensagem do agente, a partir do `meta` que o orquestrador gravou."""
    source, violations = meta.get("reply_source", ""), list(meta.get("violations") or [])
    if source == "llm":
        return "llm", []
    if source == "template_fallback":
        return ("sem_saida", []) if violations == ["sem_saida"] else ("barrado", violations)
    if source == "template_question":
        asked = meta.get("asked") or []
        return ("trocado_produto", []) if (len(asked) == 2 and (asked[1] == "confirm" or asked[0] == "necessidade")) else ("trocado_orquestrador", [])
    return "template", []


def origins_of(messages: list[dict[str, Any]]) -> Origins:
    o = Origins()
    for m in messages:
        if m["role"] != "agent" or m["kind"] == "hold":
            continue
        meta = json.loads(m["meta"])
        bucket, rules = classify_reply(meta)
        o.counts[bucket] += 1
        o.rules.update(rules)
        if bucket == "template":
            o.sources[meta.get("reply_source") or "sem reply_source"] += 1
    return o


BLOCKED_NOTE = ("Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu (\"grava o texto barrado pelo guardrail\", campo `blocked_reply` do `meta`); em banco anterior só a regra foi "
                "gravada e a linha diz \"não gravado\". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada (\"texto omitido: pii\").")


def blocked_rows(messages: list[dict[str, Any]], *, trace: str | None = None) -> list[str]:
    """Uma linha por texto do modelo que o guardrail barrou: a regra e o texto (ou por que nao ha texto)."""
    rows = []
    for m in messages:
        if m["role"] != "agent" or m["kind"] == "hold":
            continue
        meta = json.loads(m["meta"])
        bucket, rules = classify_reply(meta)
        if bucket != "barrado":
            continue
        if "blocked_reply" in meta:
            text = _cell(meta["blocked_reply"])
        elif meta.get("blocked_reply_omitted"):
            text = f"_texto omitido: {meta['blocked_reply_omitted']}_"
        else:
            text = "_não gravado: execução anterior ao commit que grava o texto barrado_"
        rows.append(f"| {(f'`{trace}` ' if trace else '')}{m['seq']} | {', '.join(rules)} | {text} |")
    return rows


def blocked_lines(messages: list[dict[str, Any]], *, trace: str | None = None) -> list[str]:
    rows = blocked_rows(messages, trace=trace)
    head = ["| " + ("Conversa " if trace else "") + "# | Regras | Texto do modelo barrado |", "|" + ("---|" if trace else "") + "---|---|---|"]
    return [f"> {BLOCKED_NOTE}", ""] + (head + rows if rows else ["_Nenhum texto do modelo foi barrado pelo guardrail._"])


def _pct(n: int, d: int) -> str:
    return "—" if d == 0 else f"{100 * n / d:.0f}%"


def origin_lines(o: Origins) -> list[str]:
    """A tabela de origens e a fracao do modelo, em Markdown."""
    detail = {"barrado": ", ".join(f"{r} ×{n}" for r, n in sorted(o.rules.items())), "template": ", ".join(f"{s} ×{n}" for s, n in sorted(o.sources.items()))}
    rows = ["| Origem | Mensagens | `reply_source` | Detalhe |", "|---|---|---|---|"]
    rows += [f"| {label} | {o.counts[key]} | {source} | {detail.get(key, '') or '—'} |" for key, label, source in BUCKETS]
    llm = o.counts["llm"]
    return rows + ["", f"**Fração do modelo:** {llm} de {o.total} respostas ao lead ({_pct(llm, o.total)}); {llm} de {o.candidates} em que o texto do modelo poderia ter chegado ({_pct(llm, o.candidates)}). "
                       f"**Barrados pelo guardrail:** {o.counts['barrado']} ({_pct(o.counts['barrado'], o.candidates)} das vezes em que o texto do modelo poderia ter chegado)."]


def export_markdown(store: Store, trace_id: str) -> str:
    rec = store.reconstruct(trace_id)
    conv, msgs, quotes, handoff = rec["conversation"], rec["messages"], rec["quotes"], rec["handoff"]
    unbacked = store.money_not_in_quotes(trace_id)
    ok_quotes = [q for q in quotes if q["status"] == "ok" and q["kind"] != "precheck"]
    retries = [(q["id"], a) for q in quotes for a in q["attempts"] if a["decision"] == "retry"]
    agent_money = [m for msg in msgs if msg["role"] == "agent" for m in money_in(msg["text"])]

    out = [f"# Log de execução — `{trace_id}`", "",
           f"- **LLM:** `{conv['llm_provider']}/{conv['llm_model']}` (modo `{conv['mode']}`) · **criada em** {conv['created_at']} · **atualizada em** {conv['updated_at']}",
           f"- **Desfecho:** `{conv['status']}`" + (f" · motivo `{conv['handoff_reason']}`" if conv["handoff_reason"] else "")
           + (f" · componente `{conv['failed_component']}`" if conv["failed_component"] else "") + (f" · detalhe `{conv['handoff_detail']}`" if conv["handoff_detail"] else ""),
           f"- **Mensagens:** {len(msgs)} · **cotações:** {len(quotes)} · **tentativas da `/quote`:** {sum(len(q['attempts']) for q in quotes)}", "",
           "## Verificações (critérios E3 do PLAN)", "",
           "| Verificação | Resultado |", "|---|---|",
           f"| LLM real registrado | {'sim' if conv['mode'] == 'real' else '**não** — modo `' + conv['mode'] + '` (para o log do README rode com `--llm real`)'} |",
           f"| Existe cotação `ok` | {'sim: ' + ', '.join(q['id'] for q in ok_quotes) if ok_quotes else '**não**'} |",
           f"| Existe falha seguida de retry visível | {'sim: ' + str(len(retries)) + ' tentativa(s) com decisão `retry`' if retries else '**não** (use uma semente/API que falhe antes de acertar)'} |",
           f"| Todo `R$` dito pelo agente existe numa cotação `ok` desta conversa | {'sim (' + str(len(agent_money)) + ' valor(es))' if not unbacked else '**NÃO**: ' + ', '.join(unbacked)} |",
           "| Sem PII nem segredo no texto exportado | (conferido ao final: a exportação é recusada se houver) |", "",
           "## De onde veio cada texto que o lead leu", "", *origin_lines(origins_of(msgs)), "", "### Textos do modelo barrados pelo guardrail", "", *blocked_lines(msgs), "",
           "## Transcrição", "", "| # | Quando (UTC) | Quem | Tipo | Texto (já mascarado) |", "|---|---|---|---|---|"]
    for m in msgs:
        out.append(f"| {m['seq']} | {m['ts'][11:23]} | {'lead' if m['role'] == 'lead' else 'agente'} | {m['kind']} | {_cell(m['text'])} |")

    out += ["", "## Decisões do agente, mensagem a mensagem", "", "| # | Tipo | Registro (`meta`) |", "|---|---|---|"]
    for m in msgs:
        out.append(f"| {m['seq']} | {m['role']}/{m['kind']} | {_cell(_fmt_meta(json.loads(m['meta'])))} |")

    out += ["", "## Cotações e tentativas da `/quote`", ""]
    if not quotes:
        out.append("_Nenhuma chamada à `/quote` nesta conversa._")
    for q in quotes:
        resp = json.loads(q["response"]) if q["response"] else None
        summary = ("—" if resp is None else f"mensalidade {q['premio_mensal']}, franquia {resp.get('franquia')}" + (f", primeiro pagamento {resp['primeiro_pagamento_pro_rata']['valor_primeiro_pagamento']}"
                   if resp.get("primeiro_pagamento_pro_rata") else "") if q["status"] == "ok" else json.dumps(resp, ensure_ascii=False))
        out += [f"### `{q['id']}` — {q['kind']} · {q['status']} · plano `{q['plano_id']}` · {q['elapsed_s']}s", "",
                f"- **Entrada normalizada enviada:** `{q['request']}`", f"- **Resposta:** {summary}", "",
                "| Tentativa | Início (s) | Latência (s) | HTTP | Erro | Decisão |", "|---|---|---|---|---|---|"]
        out += [f"| {a['n']} | {a['started_s']} | {a['latency_s']} | {a['http_status'] if a['http_status'] is not None else '—'} | {a['error_kind']} | {a['decision']} |" for a in q["attempts"]]
        out.append("")

    slots = json.loads(conv["slots"] or "{}")
    out += ["## Estado final dos slots", "", "| Slot | Estado | Valor | Evidência no texto do lead |", "|---|---|---|---|"]
    out += [f"| {s} | {v['status']} | {v['value'] if v['value'] is not None else '—'} | {_cell(v['evidence'] or v.get('reason') or '—')} |" for s, v in sorted(slots.items())] or ["| — | — | — | — |"]
    if handoff:
        out += ["", "## Pacote de handoff entregue ao humano", "", "```json", json.dumps(handoff, ensure_ascii=False, indent=2, sort_keys=True), "```"]
    text = "\n".join(out) + "\n"
    found = scan(text)
    if found:
        raise ExportRefused(sorted(set(found)))
    return text.replace("(conferido ao final: a exportação é recusada se houver)", "sim (varredura do texto exportado: 0 achados)")


def list_traces(store: Store) -> list[str]:
    """Todos os `trace_id` do banco, do mais antigo ao mais novo (a ordem em que as conversas foram abertas)."""
    with store._lock:
        return [r["trace_id"] for r in store._conn.execute("SELECT trace_id FROM conversations ORDER BY created_at, trace_id")]


def index_markdown(store: Store, traces: list[str], *, files: dict[str, str] | None = None) -> str:
    """Uma tabela com uma linha por conversa: desfecho, motivo, cotacoes, tentativas com retry, mensagens. So metadados (nada de texto de mensagem), mas passa pela mesma varredura."""
    rows = ["# Conversas exportadas", "", "| Conversa | Desfecho | Motivo / componente | LLM | Cotacoes (ok/recusa/fora) | Retries da /quote | Mensagens | Texto do modelo / respostas | Barrados | Arquivo |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    total = Origins()
    blocked: list[str] = []
    for t in traces:
        rec = store.reconstruct(t)
        c, qs = rec["conversation"], rec["quotes"]
        reason = (c["handoff_reason"] or "—") + (f" / {c['failed_component']}" if c["failed_component"] else "")
        status = {s: sum(1 for q in qs if q["status"] == s) for s in ("ok", "refused", "unavailable")}
        retries = sum(1 for q in qs for a in q["attempts"] if a["decision"] == "retry")
        o = origins_of(rec["messages"])
        total += o
        blocked += blocked_rows(rec["messages"], trace=t)
        rows.append(f"| `{t}` | {c['status']} | {reason} | {c['llm_provider']}/{c['llm_model']} | {status['ok']}/{status['refused']}/{status['unavailable']} | {retries} | {len(rec['messages'])} | "
                    f"{o.counts['llm']}/{o.total} | {o.counts['barrado']} | {('[' + files[t] + '](' + files[t] + ')') if files and t in files else '—'} |")
    rows += ["", f"## Total das {len(traces)} conversas: de onde veio cada texto que o lead leu", "", *origin_lines(total), "",
             "### Textos do modelo barrados pelo guardrail (todas as conversas)", "", f"> {BLOCKED_NOTE}", ""]
    rows += (["| Conversa # | Regras | Texto do modelo barrado |", "|---|---|---|", *blocked] if blocked else ["_Nenhum texto do modelo foi barrado pelo guardrail._"])
    text = "\n".join(rows) + "\n"
    found = scan(text)
    if found:
        raise ExportRefused(sorted(set(found)))
    return text


def latest_trace(store: Store, *, status: str | None = None) -> str | None:
    """O `trace_id` da conversa mais recente (opcionalmente com um desfecho), para `--trace latest`."""
    with store._lock:
        row = store._conn.execute("SELECT trace_id FROM conversations" + (" WHERE status = ?" if status else "") + " ORDER BY created_at DESC, trace_id DESC LIMIT 1",
                                  (status,) if status else ()).fetchone()
    return None if row is None else row["trace_id"]
