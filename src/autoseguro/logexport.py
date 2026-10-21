"""Exporta o log de UMA execucao (uma conversa, pelo `trace_id`) em Markdown: transcricao, decisoes do agente, cotacoes com todas as tentativas da /quote, slots e o pacote de handoff.

Tudo vem do SQLite, onde so existe texto JA MASCARADO. Mesmo assim o Markdown passa por uma varredura antes de ser escrito (detector de PII do gate de envio, CPF com digitos
verificadores validos, chaves): se achar algo, NAO exporta (`ExportRefused`) e diz o tipo, nunca o trecho. A secao "Verificacoes" repete os criterios E3 do PLAN para o autor saber,
antes de copiar o log para o README, se esta execucao serve: LLM real registrado, cotacao ok, retry visivel, todo "R$" existe numa cotacao ok, sem PII.
"""
from __future__ import annotations

import json
import re
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
            "llm_latency_s", "llm_error", "hold_fired", "quote_elapsed_s", "handoff_reason", "mask_kinds", "truncated")
    parts = []
    for k in keep:
        v = meta.get(k)
        if v in (None, [], False, ""):
            continue
        parts.append(f"{k}={json.dumps(v, ensure_ascii=False)}")
    if meta.get("usage"):
        parts.append(f"tokens={meta['usage'].get('input_tokens')}→{meta['usage'].get('output_tokens')}")
    return "; ".join(parts) or "—"


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


def latest_trace(store: Store, *, status: str | None = None) -> str | None:
    """O `trace_id` da conversa mais recente (opcionalmente com um desfecho), para `--trace latest`."""
    with store._lock:
        row = store._conn.execute("SELECT trace_id FROM conversations" + (" WHERE status = ?" if status else "") + " ORDER BY created_at DESC, trace_id DESC LIMIT 1",
                                  (status,) if status else ()).fetchone()
    return None if row is None else row["trace_id"]
