"""Persistencia em SQLite (PLAN, secao 9): 4 tabelas, cada uma responde a uma pergunta de rastreabilidade. So texto JA MASCARADO entra aqui.

  conversations   como terminou (open, quoted, refused, handoff + motivo + componente), em que estado de slots, e que pacote foi entregue ao humano
  messages        o que foi dito, por quem, em que ordem; ja processada (dedupe por external_id); que cotacao exibe; o que o LLM e o guardrail fizeram (meta)
  quotes          que cotacao o lead recebeu, para que entrada normalizada, com que status e valor (cotacao, alternativa ou recusa)
  quote_attempts  como a /quote chegou a esse resultado: cada tentativa, status HTTP, tempo, por que parou

Nunca persistido: texto cru, CPF, e-mail, telefone, nome, placa, prompts. O caller entrega texto ja mascarado; um teste varre o arquivo do banco.
Tudo liga por `trace_id`. A invariante do principio 1 ("o agente nunca inventa preco") e uma consulta: `money_not_in_quotes`.
"""
from __future__ import annotations

import itertools
import json
import re
import sqlite3
import threading
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .handoff import DeliveryReceipt, HandoffPackage, SinkUnavailable

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  trace_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  mode TEXT NOT NULL,                     -- mock | real | external (entrega de handoff sem conversa)
  llm_provider TEXT, llm_model TEXT,
  status TEXT NOT NULL CHECK (status IN ('open','quoted','refused','handoff')),
  handoff_reason TEXT, failed_component TEXT, handoff_detail TEXT,
  slots TEXT NOT NULL DEFAULT '{}',       -- JSON: estado do SlotLedger (valores verificados e pendencias; so texto mascarado)
  llm_blocked_streak INTEGER NOT NULL DEFAULT 0,
  handoff_package TEXT,                   -- JSON entregue ao humano (HandoffPackage.to_dict)
  handoff_delivered_at TEXT, handoff_external_ref TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL REFERENCES conversations(trace_id),
  seq INTEGER NOT NULL,
  ts TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('lead','agent')),
  kind TEXT NOT NULL,                     -- text | hold | question | confirmation | quote | refusal | handoff | fallback | closed
  text TEXT NOT NULL,                     -- JA MASCARADO
  status TEXT NOT NULL,                   -- processed (lead) | sent (agente)
  quote_id TEXT REFERENCES quotes(id),    -- a cotacao que esta mensagem exibe
  external_id TEXT,                       -- id da mensagem no canal, para dedupe
  meta TEXT NOT NULL DEFAULT '{}',        -- JSON: mask_kinds, intent, reply_source, facts_used, violations, usage, llm_error, attempt
  UNIQUE (trace_id, seq),
  UNIQUE (trace_id, external_id)
);
CREATE TABLE IF NOT EXISTS quotes (
  id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL REFERENCES conversations(trace_id),
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('quote','alternative')),
  status TEXT NOT NULL CHECK (status IN ('ok','refused','invalid','unavailable')),
  request TEXT NOT NULL,                  -- JSON: a entrada NORMALIZADA enviada a /quote
  response TEXT,                          -- JSON: o corpo 200 como veio, ou {"motivo": ...} da recusa
  plano_id TEXT, premio_mensal REAL, elapsed_s REAL
);
CREATE TABLE IF NOT EXISTS quote_attempts (
  id TEXT PRIMARY KEY,
  quote_id TEXT NOT NULL REFERENCES quotes(id),
  trace_id TEXT NOT NULL REFERENCES conversations(trace_id),
  n INTEGER NOT NULL, started_s REAL NOT NULL, latency_s REAL NOT NULL,
  http_status INTEGER, error_kind TEXT NOT NULL, decision TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_messages_trace ON messages(trace_id, seq);
CREATE INDEX IF NOT EXISTS ix_quotes_trace ON quotes(trace_id);
"""

_BRL = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})")


def money_in(text: str) -> list[str]:
    """Todo valor em reais escrito em `text`, na forma canonica ("R$ 1.234,56")."""
    return [f"R$ {m}" for m in _BRL.findall(text)]


def utc_now() -> datetime:
    return datetime.now(UTC)


def brl(value: float) -> str:
    """12345.6 -> 'R$ 12.345,60'. A unica forma de escrever dinheiro numa mensagem: sempre a partir de um numero da resposta da API."""
    s = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


class SequentialIds:
    """Ids legiveis e deterministas (cenarios e testes): trc_0001, msg_000001, qte_0001, att_000001."""

    def __init__(self) -> None:
        self._c = {k: itertools.count(1) for k in ("trc", "msg", "qte", "att")}

    def new(self, kind: str) -> str:
        width = 4 if kind in ("trc", "qte") else 6
        return f"{kind}_{next(self._c[kind]):0{width}d}"


class RandomIds:
    def new(self, kind: str) -> str:
        return f"{kind}_{uuid.uuid4().hex[:12]}"


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


class Store:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # --- escrita ------------------------------------------------------------------------------------------------------------------------------
    def open_conversation(self, trace_id: str, *, mode: str, provider: str | None, model: str | None, now: datetime) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO conversations (trace_id, created_at, updated_at, mode, llm_provider, llm_model, status) VALUES (?,?,?,?,?,?, 'open')",
                (trace_id, now.isoformat(), now.isoformat(), mode, provider, model))

    def update_conversation(self, trace_id: str, now: datetime, **fields: Any) -> None:
        allowed = {"status", "handoff_reason", "failed_component", "handoff_detail", "slots", "llm_blocked_streak"}
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"campos nao atualizaveis: {sorted(bad)}")
        if "slots" in fields and not isinstance(fields["slots"], str):
            fields["slots"] = _j(fields["slots"])
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE conversations SET {sets + ', ' if sets else ''}updated_at = ? WHERE trace_id = ?", (*fields.values(), now.isoformat(), trace_id))

    def add_message(self, trace_id: str, msg_id: str, *, role: str, kind: str, text: str, ts: datetime, status: str, quote_id: str | None = None,
                    external_id: str | None = None, meta: Mapping[str, Any] | None = None) -> str:
        with self._lock, self._conn:
            seq = self._conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE trace_id = ?", (trace_id,)).fetchone()[0]
            self._conn.execute(
                "INSERT INTO messages (id, trace_id, seq, ts, role, kind, text, status, quote_id, external_id, meta) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (msg_id, trace_id, seq, ts.isoformat(), role, kind, text, status, quote_id, external_id, _j(dict(meta or {}))))
        return msg_id

    def add_quote(self, trace_id: str, quote_id: str, *, kind: str, status: str, request: Mapping[str, Any], response: Any, plano_id: str | None,
                  premio_mensal: float | None, elapsed_s: float, now: datetime) -> str:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO quotes (id, trace_id, created_at, kind, status, request, response, plano_id, premio_mensal, elapsed_s) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (quote_id, trace_id, now.isoformat(), kind, status, _j(dict(request)), None if response is None else _j(response), plano_id, premio_mensal, elapsed_s))
        return quote_id

    def add_attempt(self, trace_id: str, quote_id: str, att_id: str, *, n: int, started_s: float, latency_s: float, http_status: int | None,
                    error_kind: str, decision: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO quote_attempts (id, quote_id, trace_id, n, started_s, latency_s, http_status, error_kind, decision) VALUES (?,?,?,?,?,?,?,?,?)",
                (att_id, quote_id, trace_id, n, started_s, latency_s, http_status, error_kind, decision))

    # --- leitura ------------------------------------------------------------------------------------------------------------------------------
    def conversation(self, trace_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM conversations WHERE trace_id = ?", (trace_id,)).fetchone()
        return None if row is None else dict(row)

    def message_by_external(self, trace_id: str, external_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM messages WHERE trace_id = ? AND external_id = ?", (trace_id, external_id)).fetchone()
        return None if row is None else dict(row)

    def agent_messages_after(self, trace_id: str, seq: int) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM messages WHERE trace_id = ? AND seq > ? AND role = 'agent' ORDER BY seq", (trace_id, seq))]

    def messages(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM messages WHERE trace_id = ? ORDER BY seq", (trace_id,))]

    def quotes(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            out = [dict(r) for r in self._conn.execute("SELECT * FROM quotes WHERE trace_id = ? ORDER BY created_at, id", (trace_id,))]
            for q in out:
                q["attempts"] = [dict(r) for r in self._conn.execute("SELECT * FROM quote_attempts WHERE quote_id = ? ORDER BY n", (q["id"],))]
        return out

    def reconstruct(self, trace_id: str) -> dict[str, Any]:
        """A historia inteira de uma conversa pelo trace_id: estado, mensagens na ordem, cotacoes com as tentativas, e o pacote de handoff."""
        conv = self.conversation(trace_id)
        if conv is None:
            raise KeyError(trace_id)
        return {"conversation": conv, "messages": self.messages(trace_id), "quotes": self.quotes(trace_id),
                "handoff": json.loads(conv["handoff_package"]) if conv["handoff_package"] else None}

    def money_not_in_quotes(self, trace_id: str) -> list[str]:
        """A INVARIANTE DO PRECO: todo "R$" escrito pelo agente existe na resposta de uma cotacao 'ok' da MESMA conversa. Devolve os que NAO existem (tem que ser [])."""
        allowed: set[str] = set()
        for q in self.quotes(trace_id):
            if q["status"] != "ok" or not q["response"]:
                continue
            resp = json.loads(q["response"])
            values = [resp.get("premio_mensal"), resp.get("franquia"), (resp.get("primeiro_pagamento_pro_rata") or {}).get("valor_primeiro_pagamento")]
            allowed |= {brl(float(v)) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)}
        shown = [m for msg in self.messages(trace_id) if msg["role"] == "agent" for m in money_in(msg["text"])]
        return [m for m in shown if m not in allowed]

    def all_text(self) -> str:
        """Todo o texto armazenado (para a varredura de PII nos testes)."""
        with self._lock:
            parts = [r[0] for r in self._conn.execute("SELECT text || ' ' || meta FROM messages")]
            parts += [r[0] or "" for r in self._conn.execute("SELECT COALESCE(slots,'') || ' ' || COALESCE(handoff_package,'') || ' ' || COALESCE(handoff_detail,'') FROM conversations")]
            parts += [r[0] or "" for r in self._conn.execute("SELECT request || ' ' || COALESCE(response,'') FROM quotes")]
        return "\n".join(parts)


class SqliteSink:
    """Destino padrao do handoff (HandoffSink): grava o pacote na propria conversa. Idempotente por trace_id; falha do banco e transitoria."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def deliver(self, package: HandoffPackage) -> DeliveryReceipt:
        s = self._store
        try:
            with s._lock, s._conn:
                row = s._conn.execute("SELECT handoff_package, handoff_delivered_at, handoff_external_ref FROM conversations WHERE trace_id = ?",
                                      (package.trace_id,)).fetchone()
                if row is not None and row["handoff_package"]:  # reentrega: devolve o MESMO recibo e nao grava nada
                    return DeliveryReceipt(package.trace_id, "delivered", datetime.fromisoformat(row["handoff_delivered_at"]), row["handoff_external_ref"])
                now = utc_now()
                ref = f"sqlite:{package.trace_id}"
                if row is None:  # pacote de uma conversa que este banco nao conhece: cria a linha minima, para o pacote nao se perder
                    s._conn.execute("INSERT INTO conversations (trace_id, created_at, updated_at, mode, status) VALUES (?,?,?, 'external', 'handoff')",
                                    (package.trace_id, now.isoformat(), now.isoformat()))
                s._conn.execute(
                    "UPDATE conversations SET handoff_package = ?, handoff_delivered_at = ?, handoff_external_ref = ?, handoff_reason = COALESCE(handoff_reason, ?), "
                    "failed_component = COALESCE(failed_component, ?), updated_at = ? WHERE trace_id = ?",
                    (_j(package.to_dict()), now.isoformat(), ref, package.reason.value,
                     None if package.failed_component is None else package.failed_component.value, now.isoformat(), package.trace_id))
                return DeliveryReceipt(package.trace_id, "delivered", now, ref)
        except sqlite3.OperationalError as exc:  # banco travado ou indisponivel: o handoff fica pendente e a entrega e repetida
            raise SinkUnavailable(str(exc)) from exc
