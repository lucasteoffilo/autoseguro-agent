"""Cliente da /quote, politica B (ver docs/PLAN.md, secoes 3 e 4 e docs/FINDINGS.md).

  - timeout de 10s por tentativa (a resposta lenta da API leva 8s e e VALIDA), no maximo 4 chamadas, orcamento de 15s ou o
    prazo restante do turno, o que for menor;
  - retry SO em falha transitoria: 5xx, 429, timeout, erro de conexao e corpo invalido. Nunca em 400 nem em 422;
  - backoff exponencial com jitter; nunca dorme alem do orcamento;
  - UMA chamada em voo por vez, por construcao: so abre a seguinte depois de concluir ou abandonar a anterior. Nao ha hedging;
  - classifica pelo CORPO, nao pelo status: o 422 de regra de negocio (`cotacao_recusada`) e o 422 do pydantic (`detail`) sao coisas
    diferentes;
  - um 200 so vira `Quote` se passar por validacao estrita (plano igual ao pedido, preco finito > 0, campos presentes, pro-rata
    presente quando a data de inicio nao e dia 1). A API devolve 200 errado em varios casos; o preco so chega ao lead se for coerente;
  - cada tentativa fica registrada (`Attempt`) para a tabela `quote_attempts`.

O tempo e o transporte sao injetados: os testes usam relogio virtual (sem `sleep`) e um transporte roteirizado.
"""
from __future__ import annotations

import json
import math
import random
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from . import budgets
from .slots import QuoteRequest

_EPS = 1e-9

ErrorKind = Literal["none", "refused", "invalid_schema", "invalid_payload", "http_5xx", "http_429", "timeout", "connection",
                    "bad_body", "plan_mismatch", "unexpected_status"]
Decision = Literal["accept", "stop_refused", "stop_invalid", "stop_unexpected", "retry", "stop_max_calls", "stop_budget"]


# --- transporte e relogio (injetaveis) --------------------------------------------------------------
@dataclass(frozen=True)
class RawResponse:
    status: int
    body: bytes


class TransportConnectionError(Exception):
    """Falha de rede ao completar a chamada."""


class Pending(Protocol):
    def wait(self, timeout_s: float) -> RawResponse | None:
        """Espera ate `timeout_s`. None = ainda nao terminou. Levanta TransportConnectionError em falha de rede."""
        ...

    def abandon(self) -> None:
        """O cliente desistiu desta chamada: o resultado nao interessa mais (deixa de contar como 'em voo')."""
        ...


class Transport(Protocol):
    def start(self, payload: dict[str, Any]) -> Pending: ...


class RealClock:
    def now(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class _ThreadPending:
    def __init__(self, fn: Callable[[], RawResponse]) -> None:
        self._done = threading.Event()
        self._resp: RawResponse | None = None
        self._exc: Exception | None = None
        threading.Thread(target=self._run, args=(fn,), daemon=True).start()

    def _run(self, fn: Callable[[], RawResponse]) -> None:
        try:
            self._resp = fn()
        except TransportConnectionError as exc:
            self._exc = exc
        except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/IO da thread vira erro de conexao
            self._exc = TransportConnectionError(type(exc).__name__)
        finally:
            self._done.set()

    def wait(self, timeout_s: float) -> RawResponse | None:
        if not self._done.wait(max(0.0, timeout_s)):
            return None
        if self._exc is not None:
            raise self._exc
        return self._resp

    def abandon(self) -> None:
        """A thread termina sozinha pelo timeout do socket; o resultado e descartado."""


class UrllibTransport:
    """HTTP real, so com a biblioteca padrao. Cada chamada roda numa thread para o cliente poder esperar com prazo."""

    def __init__(self, base_url: str, *, socket_timeout_s: float = budgets.QUOTE_ATTEMPT_TIMEOUT_S + 2.0) -> None:
        self._url = base_url.rstrip("/") + "/quote"
        self._timeout = socket_timeout_s

    def start(self, payload: dict[str, Any]) -> Pending:
        req = urllib.request.Request(self._url, data=json.dumps(payload).encode(), headers={"content-type": "application/json"},
                                     method="POST")

        def call() -> RawResponse:
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as r:  # noqa: S310 - URL vem de configuracao
                    return RawResponse(r.status, r.read())
            except urllib.error.HTTPError as exc:  # 4xx/5xx sao RESPOSTAS, nao falhas de rede
                return RawResponse(exc.code, exc.read())
            except (urllib.error.URLError, OSError) as exc:
                raise TransportConnectionError(type(exc).__name__) from exc

        return _ThreadPending(call)


# --- politica e resultados --------------------------------------------------------------------------
@dataclass(frozen=True)
class Policy:
    attempt_timeout_s: float = budgets.QUOTE_ATTEMPT_TIMEOUT_S
    max_calls: int = budgets.QUOTE_MAX_CALLS
    backoff_base_s: float = budgets.QUOTE_BACKOFF_BASE_S
    min_attempt_s: float = budgets.QUOTE_MIN_ATTEMPT_S


@dataclass(frozen=True)
class Attempt:
    n: int
    started_s: float          # desde o inicio da cotacao
    latency_s: float
    http_status: int | None   # None: timeout ou erro de conexao
    error_kind: ErrorKind
    decision: Decision


@dataclass(frozen=True, kw_only=True)
class _Outcome:
    attempts: tuple[Attempt, ...]
    elapsed_s: float
    hold_fired: bool = False
    hold_error: str | None = None


@dataclass(frozen=True, kw_only=True)
class Quote(_Outcome):
    plano_id: str
    plano_nome: str
    premio_mensal: float
    franquia: float
    coberturas: tuple[str, ...]
    multiplicadores: dict[str, float]
    carencia_dias: int
    carencia_coberturas: tuple[str, ...]
    primeiro_pagamento: float | None   # valor do primeiro pagamento pro-rata, quando existe
    pro_rata: dict[str, Any] | None
    raw: dict[str, Any]                # resposta da API como veio, para persistir em `quotes.response`


@dataclass(frozen=True, kw_only=True)
class Refused(_Outcome):
    """422 `cotacao_recusada`: decisao de negocio da API (idade, veiculo, plano). Nao e falha."""

    motivo: str


@dataclass(frozen=True, kw_only=True)
class InvalidInput(_Outcome):
    """Entrada recusada pela validacao (pydantic 422 ou 400): erro nosso, nao do lead e nem da API."""

    kind: Literal["schema", "payload"]
    detail: str


@dataclass(frozen=True, kw_only=True)
class Unavailable(_Outcome):
    """Sem cotacao dentro do orcamento. O componente que falhou e a API: vai junto do motivo no log e no pacote de handoff."""

    reason: Literal["attempts_exhausted", "budget_exhausted", "unexpected_response"]
    last_error: str
    component: str = "quote_api"


QuoteOutcome = Quote | Refused | InvalidInput | Unavailable


# --- classificacao (pura) ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _Verdict:
    kind: Literal["ok", "refused", "invalid", "retry", "fatal"]
    error_kind: ErrorKind
    detail: str = ""
    sub: Literal["schema", "payload"] = "schema"
    data: dict[str, Any] | None = None


def _json(body: bytes) -> Any:
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _quote_problem(b: Any, req: QuoteRequest) -> str | None:
    """None se o 200 e coerente; senao o nome do problema. Um 200 incoerente NUNCA vira preco."""
    if not isinstance(b, dict):
        return "not_object"
    if b.get("plano_id") != req.plano_id:
        return "plan_mismatch"
    if not isinstance(b.get("plano_nome"), str):
        return "plano_nome"
    if not _is_num(b.get("premio_mensal")) or b["premio_mensal"] <= 0:
        return "premio_mensal"
    if not _is_num(b.get("franquia")):
        return "franquia"
    if not (isinstance(b.get("coberturas"), list) and all(isinstance(c, str) for c in b["coberturas"])):
        return "coberturas"
    m = b.get("multiplicadores")
    if not (isinstance(m, dict) and all(_is_num(m.get(k)) for k in ("faixa_etaria", "idade_veiculo", "regiao"))):
        return "multiplicadores"
    c = b.get("carencia")
    if not (isinstance(c, dict) and isinstance(c.get("dias"), int) and not isinstance(c["dias"], bool)
            and isinstance(c.get("coberturas"), list)):
        return "carencia"
    if b.get("moeda") != "BRL":
        return "moeda"
    if req.data_inicio is not None and req.data_inicio.day != 1:  # a API so calcula pro-rata fora do dia 1; sem ele o preco nao e coerente
        pr = b.get("primeiro_pagamento_pro_rata")
        if not (isinstance(pr, dict) and all(_is_num(pr.get(k)) for k in ("valor_primeiro_pagamento", "dias_cobrados", "dias_no_mes"))):
            return "pro_rata"
    return None


def classify(resp: RawResponse, req: QuoteRequest) -> _Verdict:
    s, body = resp.status, _json(resp.body)
    if s == 200:
        problem = _quote_problem(body, req)
        if problem is None:
            return _Verdict("ok", "none", data=body)
        return _Verdict("retry", "plan_mismatch" if problem == "plan_mismatch" else "bad_body", problem)
    if s == 422:
        if isinstance(body, dict) and body.get("error") == "cotacao_recusada" and isinstance(body.get("motivo"), str):
            return _Verdict("refused", "refused", body["motivo"])
        if isinstance(body, dict) and isinstance(body.get("detail"), list):
            first = body["detail"][0] if body["detail"] else {}
            loc = ".".join(str(p) for p in first.get("loc", [])) if isinstance(first, dict) else ""
            msg = first.get("msg", "") if isinstance(first, dict) else ""
            return _Verdict("invalid", "invalid_schema", f"{loc}: {msg}", "schema")  # sem o `input`: nao repete dado do lead
        return _Verdict("retry", "bad_body", "422_inesperado")
    if s == 400:
        if isinstance(body, dict) and body.get("error") == "payload_invalido":
            return _Verdict("invalid", "invalid_payload", str(body.get("detalhe", "")), "payload")
        return _Verdict("fatal", "unexpected_status", "400_inesperado")
    if s == 429:
        return _Verdict("retry", "http_429")
    if s >= 500:
        return _Verdict("retry", "http_5xx")
    return _Verdict("fatal", "unexpected_status", f"status_{s}")


def _quote_fields(b: dict[str, Any]) -> dict[str, Any]:
    pr = b.get("primeiro_pagamento_pro_rata")
    return dict(
        plano_id=b["plano_id"], plano_nome=b["plano_nome"], premio_mensal=float(b["premio_mensal"]), franquia=float(b["franquia"]),
        coberturas=tuple(b["coberturas"]), multiplicadores={k: float(v) for k, v in b["multiplicadores"].items()},
        carencia_dias=b["carencia"]["dias"], carencia_coberturas=tuple(b["carencia"]["coberturas"]),
        primeiro_pagamento=float(pr["valor_primeiro_pagamento"]) if isinstance(pr, dict) else None,
        pro_rata=dict(pr) if isinstance(pr, dict) else None, raw=b)


class _Hold:
    """Dispara o callback de 'um instante' uma unica vez, no instante `at`, mesmo no meio de uma chamada bloqueada."""

    def __init__(self, at: float, callback: Callable[[], None]) -> None:
        self.at, self._callback = at, callback
        self.fired, self.error = False, None

    def fire_if_due(self, now: float) -> None:
        if not self.fired and now >= self.at - _EPS:
            self.fired = True
            try:
                self._callback()
            except Exception as exc:  # noqa: BLE001 - a mensagem de espera e best-effort; nunca pode perder a cotacao
                self.error = type(exc).__name__


# --- o cliente --------------------------------------------------------------------------------------
class QuoteClient:
    def __init__(self, transport: Transport, clock: Any = None, rng: random.Random | None = None, policy: Policy | None = None) -> None:
        self._transport = transport
        self._clock = clock or RealClock()
        self._rng = rng or random.Random()
        self._policy = policy or Policy()

    @classmethod
    def http(cls, base_url: str) -> QuoteClient:
        return cls(UrllibTransport(base_url))

    def quote(self, request: QuoteRequest, *, budget_s: float = budgets.QUOTE_BUDGET_S, hold_after_s: float | None = None,
              on_hold: Callable[[], None] | None = None) -> QuoteOutcome:
        """Devolve SEMPRE um resultado terminal, dentro de `budget_s`. `hold_after_s`: segundos desde AGORA em que `on_hold` deve
        disparar se ainda nao houver resultado (o orquestrador desconta o que o turno ja gastou)."""
        clock, pol = self._clock, self._policy
        t0 = clock.now()
        deadline = t0 + budget_s
        hold = _Hold(t0 + hold_after_s, on_hold) if hold_after_s is not None and on_hold is not None else None
        payload = request.to_payload()
        attempts: list[Attempt] = []
        last_error = "none"

        def done(cls: type, **fields: Any) -> Any:
            return cls(attempts=tuple(attempts), elapsed_s=clock.now() - t0, hold_fired=bool(hold and hold.fired),
                       hold_error=hold.error if hold else None, **fields)

        while True:
            if len(attempts) >= pol.max_calls:
                return done(Unavailable, reason="attempts_exhausted", last_error=last_error)
            remaining = deadline - clock.now()
            if remaining < pol.min_attempt_s:
                return done(Unavailable, reason="budget_exhausted", last_error=last_error)

            n, started = len(attempts) + 1, clock.now()
            if hold:
                hold.fire_if_due(started)
            pending = self._transport.start(payload)  # a anterior ja terminou ou foi abandonada: nunca ha duas em voo
            resp, transport_error = self._await(pending, started + min(pol.attempt_timeout_s, remaining), hold)
            latency = clock.now() - started
            verdict = _Verdict("retry", transport_error) if resp is None else classify(resp, request)  # type: ignore[arg-type]
            status = None if resp is None else resp.status

            def record(decision: Decision) -> None:
                attempts.append(Attempt(n, started - t0, latency, status, verdict.error_kind, decision))

            if verdict.kind == "ok":
                record("accept")
                return done(Quote, **_quote_fields(verdict.data or {}))
            if verdict.kind == "refused":
                record("stop_refused")
                return done(Refused, motivo=verdict.detail)
            if verdict.kind == "invalid":
                record("stop_invalid")
                return done(InvalidInput, kind=verdict.sub, detail=verdict.detail)
            if verdict.kind == "fatal":
                record("stop_unexpected")
                return done(Unavailable, reason="unexpected_response", last_error=verdict.error_kind)

            last_error = verdict.error_kind  # falha transitoria
            if n >= pol.max_calls:
                record("stop_max_calls")
                continue
            delay = pol.backoff_base_s * 2 ** (n - 1) * self._rng.uniform(0.5, 1.0)
            if clock.now() + delay + pol.min_attempt_s > deadline:
                record("stop_budget")
                return done(Unavailable, reason="budget_exhausted", last_error=last_error)
            record("retry")
            self._sleep(delay, hold)

    def _await(self, pending: Pending, end: float, hold: _Hold | None) -> tuple[RawResponse | None, str]:
        clock = self._clock
        while True:
            now = clock.now()
            wait_for = end - now
            if hold and not hold.fired:
                wait_for = min(wait_for, max(0.0, hold.at - now))
            try:
                resp = pending.wait(max(0.0, wait_for))
            except TransportConnectionError:
                return None, "connection"
            if resp is not None:
                return resp, ""
            now = clock.now()
            if hold:
                hold.fire_if_due(now)
            if now >= end - _EPS:
                pending.abandon()
                return None, "timeout"

    def _sleep(self, delay: float, hold: _Hold | None) -> None:
        clock = self._clock
        end = clock.now() + delay
        if hold and not hold.fired and hold.at < end:  # o instante de espera cai no meio do backoff: dorme ate la, avisa, segue
            clock.sleep(max(0.0, hold.at - clock.now()))
            hold.fire_if_due(clock.now())
        clock.sleep(max(0.0, end - clock.now()))
