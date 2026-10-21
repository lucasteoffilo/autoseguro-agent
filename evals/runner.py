"""Executa UMA conversa pelo orquestrador de producao (MockLLM -> GuardedLLM -> Orchestrator -> QuoteGate -> QuoteClient) e devolve o que os criterios precisam.

Dois backends para a /quote: o servico em processo (`VendoredTransport`, sem rede, determinístico) ou a API HTTP de teste (`--api`). Em ambos o ORACULO dos criterios e o servico
(nunca o proprio agente): o preco e a recusa que o agente disse sao conferidos contra uma chamada independente ao servico.
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from autoseguro.facts import FactBase
from autoseguro.llm.guarded import GuardedLLM
from autoseguro.mock_llm import MockLLM
from autoseguro.orchestrator import Orchestrator
from autoseguro.quote_client import QuoteClient, RawResponse, TransportConnectionError, UrllibTransport
from autoseguro.store import SequentialIds, Store
from evals.service import VendoredService, VendoredTransport, load_planos


class VirtualClock:
    """Relogio virtual: o backoff do cliente da /quote nao dorme de verdade nos evals."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += max(0.0, seconds)


class _Down:
    def wait(self, timeout_s: float) -> RawResponse | None:
        raise TransportConnectionError("fora do ar")

    def abandon(self) -> None:
        pass


class DownTransport:
    """A /quote fora do ar: toda chamada falha na conexao."""

    def start(self, payload: dict[str, Any]) -> _Down:
        return _Down()


@dataclass
class Backend:
    label: str
    today: date
    planos: dict[str, Any]
    oracle: Callable[[dict[str, Any]], tuple[int, dict[str, Any]]]     # payload -> (status, corpo), uma chamada INDEPENDENTE ao servico
    transport: Callable[[], Any]                                         # um transporte novo por conversa

    @classmethod
    def offline(cls, today: date) -> Backend:
        svc = VendoredService(today)
        return cls(f"servico vendorizado em processo (relogio {today.isoformat()})", today, load_planos(), svc.respond, lambda: VendoredTransport(today))

    @classmethod
    def http(cls, api_url: str, today: date) -> Backend:
        base = api_url.rstrip("/")
        with urllib.request.urlopen(base + "/planos", timeout=10) as r:   # noqa: S310
            planos = json.load(r)

        def oracle(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            req = urllib.request.Request(base + "/quote", data=json.dumps(payload).encode(), headers={"content-type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:   # noqa: S310
                    return r.status, json.load(r)
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read() or b"{}")

        return cls(f"API HTTP {base} (relogio do servidor, UTC)", today, planos, oracle, lambda: UrllibTransport(base))


# O que o roteiro do vendedor humano NUNCA pergunta e o agente precisa: a cobertura e a data de inicio. Nas conversas do dataset o harness responde SO isso, SO quando o agente
# pergunta (uma vez cada), para a conversa poder chegar a cotacao; tudo o mais e a fala do proprio lead. As respostas variam por conversa (hash do id) para cobrir os tres planos.
NEED_ANSWERS = ("só roubo e colisão", "quero cobrir terceiros e vidros também", "quero carro reserva e assistência 24h, a completa")


def _fill_in(cid: str, slot: str, today: date) -> str:
    h = int(hashlib.sha256(cid.encode()).hexdigest(), 16)
    if slot == "necessidade":
        return NEED_ANSWERS[h % 3]
    first = date(today.year + (today.month == 12), today.month % 12 + 1, 1)
    day = 15 if h % 4 == 0 else 1                      # um quarto comeca no meio do mes: primeiro pagamento proporcional
    return f"começando dia {day:02d}/{first.month:02d}/{first.year}"


@dataclass
class Result:
    id: str
    source: str                                   # synthetic | dataset
    status: str                                   # open | quoted | refused | handoff
    reason: str | None
    component: str | None
    detail: str | None
    turns: int
    terminal_per_turn: list[int]
    agent: list[dict[str, Any]]                   # kind, text, quote_id, meta
    lead: list[dict[str, Any]]                    # text (mascarado), meta
    quotes: list[dict[str, Any]]
    slots: dict[str, Any]
    package: dict[str, Any] | None
    stored_text: str                              # tudo que foi gravado, para a varredura de PII
    scripted: int = 0                             # respostas do HARNESS (cobertura, data) a perguntas do agente; o resto das mensagens do lead e do dataset
    elapsed_s: float = 0.0
    tags: list[str] = field(default_factory=list)

    @property
    def klass(self) -> str:
        return f"handoff:{self.reason}" if self.status == "handoff" else self.status


def run_conversation(backend: Backend, sid: str, lines: list[str] | tuple[str, ...], *, source: str = "synthetic", api: str = "service",
                     llm_failures: tuple[str | None, ...] = (), fill_in: bool = False) -> Result:
    clock = VirtualClock()
    transport = DownTransport() if api == "down" else backend.transport()
    base = FactBase.from_planos(backend.planos)
    store = Store(":memory:")
    orc = Orchestrator(llm=GuardedLLM(MockLLM(base, failures=list(llm_failures)), base), store=store, quote_client=QuoteClient(transport, clock), planos=backend.planos,
                       fact_base=base, ids=SequentialIds(), clock=clock, today=lambda: backend.today, mode="mock")
    trace = orc.start()
    per_turn: list[int] = []
    answered: set[str] = set()
    scripted = 0
    for line in lines:
        per_turn.append(len(orc.handle(trace, line).terminal))
        while fill_in:                                # a pergunta que o roteiro do vendedor nunca faz: o harness responde, uma vez por dado
            last = [m for m in store.messages(trace) if m["role"] == "agent" and m["kind"] != "hold"][-1]
            asked = json.loads(last["meta"]).get("asked") or []
            if len(asked) != 2 or asked[1] != "ask" or asked[0] not in ("necessidade", "data_inicio") or asked[0] in answered:
                break
            answered.add(asked[0])
            per_turn.append(len(orc.handle(trace, _fill_in(sid, asked[0], backend.today)).terminal))
            scripted += 1
    conv = store.conversation(trace) or {}
    msgs = store.messages(trace)
    result = Result(
        id=sid, source=source, status=conv.get("status", "open"), reason=conv.get("handoff_reason"), component=conv.get("failed_component"), detail=conv.get("handoff_detail"),
        turns=len(per_turn), terminal_per_turn=per_turn,
        agent=[{"kind": m["kind"], "text": m["text"], "quote_id": m["quote_id"], "meta": json.loads(m["meta"])} for m in msgs if m["role"] == "agent"],
        lead=[{"text": m["text"], "meta": json.loads(m["meta"])} for m in msgs if m["role"] == "lead"],
        quotes=store.quotes(trace), slots=json.loads(conv.get("slots") or "{}"),
        package=json.loads(conv["handoff_package"]) if conv.get("handoff_package") else None, stored_text=store.all_text(), scripted=scripted)
    store.close()
    return result
