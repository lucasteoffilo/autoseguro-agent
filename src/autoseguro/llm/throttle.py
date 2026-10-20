"""Limite de taxa, cota diaria e backoff de 429 para provedores com free tier (OpenRouter: 20 req/min e 50 req/dia sem creditos).

Duas decisoes conservadoras, porque os docs do OpenRouter NAO dizem se requisicao que falha conta na cota:
  - TODA requisicao que saiu da maquina e contada (sucesso, 429, 5xx, timeout), no log `quota.jsonl`;
  - a cota e por dia UTC, e o log persiste entre execucoes: rodar o smoke duas vezes no mesmo dia soma.
429: se o provedor diz que o limite e DIARIO, para (nao adianta insistir); senao espera `max(Retry-After, backoff exponencial)` e tenta de novo,
ate `max_retries`. O espacamento entre chamadas tem 5% de folga sobre 60/rpm.

Falha rapido, porque nao sabemos se requisicao que falha conta na cota:
  - ERRO DE PROTOCOLO (qualquer 4xx exceto 408 e 429: 400, 401, 402, 403, 404...) levanta `ProtocolError` NA HORA, sem repetir: o pedido e que esta
    errado, e repetir o mesmo pedido so gasta cota. O primeiro erro custa UMA requisicao, nao o plano inteiro.
  - Entram em backoff so o 429 por minuto e as falhas do servico (408 e 5xx). Se `max_consecutive_failures` chamadas seguidas ainda falham de
    transporte/servico depois do backoff (5xx, 408, 429 por minuto, timeout, conexao), levanta `ServiceUnstable`: um servico fora do ar nao pode
    consumir os 50 do dia em retentativas.
"""
from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from .base import LLMClient, LLMResult


class QuotaExhausted(RuntimeError):
    """A cota diaria acabou. Nenhuma requisicao foi feita."""


class ProtocolError(RuntimeError):
    """O provedor recusou o PEDIDO (4xx que nao e 408/429). Repetir o mesmo pedido nao adianta e gasta cota: interrompe na hora.

    A mensagem so tem o codigo e o detalhe que o provedor devolveu, e o detalhe ja sai mascarado do adaptador (a chave nunca esta nele)."""

    def __init__(self, result: LLMResult) -> None:
        self.result = result
        self.status = result.http_status
        super().__init__(f"erro de protocolo {result.error}" + (f": {result.detail}" if result.detail else ""))


class ServiceUnstable(RuntimeError):
    """Falhas de servico/transporte seguidas, mesmo depois do backoff. Para antes de queimar a cota em retentativas."""

    def __init__(self, result: LLMResult, failures: int) -> None:
        self.result, self.failures = result, failures
        super().__init__(f"{failures} falhas seguidas do servico (ultima: {result.error})" + (f": {result.detail}" if result.detail else ""))


def is_protocol_error(res: LLMResult) -> bool:
    """4xx que nao e transitorio. 408 (timeout do provedor) e 429 (limite) merecem nova tentativa; o resto, nao."""
    s = res.http_status
    return s is not None and 400 <= s < 500 and s not in (408, 429)


def is_backoff_status(res: LLMResult) -> bool:
    """429 e falhas do servico (408, 5xx): as unicas que entram em backoff."""
    s = res.http_status
    return s is not None and (s in (408, 429) or s >= 500)


def is_service_failure(res: LLMResult) -> bool:
    """Falha do servico ou do transporte, contada pelo disjuntor. Saida invalida, `max_tokens` e afins sao do MODELO: o servico respondeu."""
    return is_backoff_status(res) or res.error in ("timeout", "connection")


class RateLimiter:
    def __init__(self, rpm: int, *, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 safety: float = 1.05) -> None:
        self._rpm, self._clock, self._sleep = rpm, clock, sleep
        self._gap = 60.0 / rpm * safety
        self._window: deque[float] = deque()
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None and now < self._last + self._gap:
            self._sleep(self._last + self._gap - now)
            now = self._clock()
        while self._window and now - self._window[0] >= 60.0:
            self._window.popleft()
        if len(self._window) >= self._rpm:  # a janela deslizante de 60s nunca passa de `rpm` chamadas
            self._sleep(self._window[0] + 60.0 - now)
            now = self._clock()
            while self._window and now - self._window[0] >= 60.0:
                self._window.popleft()
        self._window.append(now)
        self._last = now


class QuotaLog:
    """Contador diario (UTC) persistido em JSONL. Nao guarda segredo, prompt nem resposta: so quando, provedor, modelo e desfecho."""

    def __init__(self, path: Path, daily_limit: int, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.path, self.daily_limit, self._now = path, daily_limit, now

    def _today_rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        today, rows = self._now().date().isoformat(), []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and str(row.get("ts", ""))[:10] == today:
                rows.append(row)
        return rows

    def used_today(self) -> int:
        return sum(1 for r in self._today_rows() if r.get("kind") == "request")

    def exhausted_today(self) -> bool:
        return any(r.get("kind") == "daily_limit_hit" for r in self._today_rows())

    def remaining(self) -> int:
        return 0 if self.exhausted_today() else max(0, self.daily_limit - self.used_today())

    def utc_day(self) -> date:
        return self._now().date()

    def _append(self, row: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": self._now().isoformat(), **row}, ensure_ascii=False) + "\n")

    def record_request(self, provider: str, model: str, outcome: str, status: int | None) -> None:
        self._append({"kind": "request", "provider": provider, "model": model, "outcome": outcome, "status": status})

    def mark_exhausted(self, provider: str, model: str) -> None:
        self._append({"kind": "daily_limit_hit", "provider": provider, "model": model})


class ThrottledLLM:
    """Envolve um adaptador: respeita o rpm, conta cada requisicao, para na cota e trata o 429. O gate e o guardrail ficam POR FORA."""

    def __init__(self, inner: LLMClient, *, limiter: RateLimiter, quota: QuotaLog, max_retries: int = 3, backoff_base_s: float = 5.0,
                 backoff_cap_s: float = 60.0, sleep: Callable[[float], None] = time.sleep,
                 on_event: Callable[[str], None] | None = None, fail_fast_on_protocol_error: bool = True,
                 max_consecutive_failures: int = 3) -> None:
        self._inner, self._limiter, self._quota = inner, limiter, quota
        self._max_retries, self._base, self._cap, self._sleep, self._on_event = max_retries, backoff_base_s, backoff_cap_s, sleep, on_event
        self._fail_fast, self._max_consecutive = fail_fast_on_protocol_error, max_consecutive_failures
        self.requests = 0
        self.retries = 0
        self.consecutive_failures = 0

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def system_prompt(self) -> str:
        return self._inner.system_prompt

    def __repr__(self) -> str:
        return f"ThrottledLLM({self._inner!r})"

    def turn(self, user_message: str) -> LLMResult:
        attempt = 0
        while True:
            if self._quota.remaining() <= 0:
                raise QuotaExhausted(f"cota diaria de {self._quota.daily_limit} requisicoes esgotada (dia UTC {self._quota.utc_day()})")
            self._limiter.wait()
            res = self._inner.turn(user_message)
            self.requests += 1
            self._quota.record_request(self.provider, self.model, res.error or "ok", res.http_status)
            if self._on_event:
                self._on_event(f"requisicao {self._quota.used_today()}/{self._quota.daily_limit} hoje ({res.error or 'ok'})")
            if res.http_status == 429 and res.quota_kind == "daily":
                self._quota.mark_exhausted(self.provider, self.model)
                return res
            if self._fail_fast and is_protocol_error(res):
                raise ProtocolError(res)  # ja foi contada acima; nada de repetir
            if is_backoff_status(res) and attempt < self._max_retries:
                wait = min(self._cap, max(res.retry_after_s or 0.0, self._base * 2**attempt))
                self.retries += 1
                if self._on_event:
                    self._on_event(f"{res.http_status}: espera {wait:.1f}s e tenta de novo ({attempt + 1}/{self._max_retries})")
                self._sleep(wait)
                attempt += 1
                continue
            return self._settle(res)

    def _settle(self, res: LLMResult) -> LLMResult:
        """Resultado final da chamada (depois do backoff): alimenta o disjuntor de falhas seguidas do servico."""
        self.consecutive_failures = self.consecutive_failures + 1 if is_service_failure(res) else 0
        if self._max_consecutive and self.consecutive_failures >= self._max_consecutive:
            raise ServiceUnstable(res, self.consecutive_failures)
        return res
