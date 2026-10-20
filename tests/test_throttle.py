"""Free tier (20 req/min, 50 req/dia): ritmo, cota diaria contada em log, 429 com backoff. Relogio e sleep virtuais, sem rede."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from autoseguro.llm.base import LLMResult
from autoseguro.llm.throttle import (ProtocolError, QuotaExhausted, QuotaLog, RateLimiter, ServiceUnstable, ThrottledLLM, is_backoff_status,
                                     is_protocol_error)


class VClock:
    def __init__(self) -> None:
        self.t = 1000.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        assert s >= 0
        self.sleeps.append(s)
        self.t += s


class Wall:
    """Relogio de parede (UTC) controlavel, para a virada do dia."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def ok() -> LLMResult:
    return LLMResult(None, None, 0.1, None, "stop", http_status=200)


def r429(kind: str = "rate", retry_after: float | None = None) -> LLMResult:
    return LLMResult(None, "http_429", 0.1, None, None, http_status=429, quota_kind=kind, retry_after_s=retry_after)


class Stub:
    provider, model, system_prompt = "openrouter", "vendor/model:free", "sistema"

    def __init__(self, results: list[LLMResult]) -> None:
        self.results, self.calls = list(results), 0

    def turn(self, user_message: str) -> LLMResult:
        self.calls += 1
        return self.results.pop(0) if self.results else ok()


def throttled(tmp_path: Path, stub: Stub, *, limit: int = 50, rpm: int = 20, retries: int = 3, base: float = 5.0, clk: VClock | None = None,
              wall: Wall | None = None):
    clk = clk or VClock()
    wall = wall or Wall(datetime(2026, 10, 20, 12, 0, tzinfo=UTC))
    quota = QuotaLog(tmp_path / "quota.jsonl", limit, now=wall)
    return ThrottledLLM(stub, limiter=RateLimiter(rpm, clock=clk.now, sleep=clk.sleep), quota=quota, max_retries=retries, backoff_base_s=base,
                        sleep=clk.sleep), quota, clk


# --- ritmo --------------------------------------------------------------------------------------------------------------------------------
def test_the_rate_limiter_never_exceeds_20_calls_in_any_60_second_window():
    clk = VClock()
    lim = RateLimiter(20, clock=clk.now, sleep=clk.sleep)
    stamps = []
    for _ in range(200):
        lim.wait()
        stamps.append(clk.now())
    for i, t in enumerate(stamps):
        assert sum(1 for s in stamps if t <= s < t + 60.0) <= 20, f"mais de 20 chamadas em 60s a partir da chamada {i}"
    assert min(b - a for a, b in zip(stamps, stamps[1:])) >= 3.0, "espacamento minimo de 60/rpm"


def test_the_spacing_has_a_five_percent_margin_over_60_over_rpm():
    clk = VClock()
    lim = RateLimiter(20, clock=clk.now, sleep=clk.sleep)
    lim.wait()
    lim.wait()
    assert clk.sleeps == [pytest.approx(3.15)]


def test_a_slow_caller_is_not_delayed_at_all():
    clk = VClock()
    lim = RateLimiter(20, clock=clk.now, sleep=clk.sleep)
    for _ in range(5):
        lim.wait()
        clk.t += 30.0
    assert clk.sleeps == []


def test_a_burst_that_fills_the_window_waits_for_it_to_slide():
    clk = VClock()
    lim = RateLimiter(5, clock=clk.now, sleep=clk.sleep, safety=0.0)  # sem espacamento minimo: so a janela
    for _ in range(5):
        lim.wait()
    lim.wait()  # a 6a so sai quando a 1a completar 60s
    assert clk.sleeps[-1] == pytest.approx(60.0)


# --- cota diaria -----------------------------------------------------------------------------------------------------------------------------
def test_quota_counts_per_utc_day_and_persists_across_instances(tmp_path):
    wall = Wall(datetime(2026, 10, 20, 23, 59, tzinfo=UTC))
    q = QuotaLog(tmp_path / "q.jsonl", 50, now=wall)
    for _ in range(3):
        q.record_request("openrouter", "m:free", "ok", 200)
    assert q.used_today() == 3 and q.remaining() == 47
    assert QuotaLog(tmp_path / "q.jsonl", 50, now=wall).used_today() == 3, "um 2o processo no mesmo dia continua de onde parou"
    wall.at += timedelta(minutes=2)  # 00:01 UTC do dia seguinte
    assert q.used_today() == 0 and q.remaining() == 50


def test_the_quota_log_holds_no_secret_prompt_or_reply(tmp_path):
    q = QuotaLog(tmp_path / "q.jsonl", 50, now=Wall(datetime(2026, 10, 20, tzinfo=UTC)))
    q.record_request("openrouter", "m:free", "http_429", 429)
    q.mark_exhausted("openrouter", "m:free")
    for line in (tmp_path / "q.jsonl").read_text().splitlines():
        assert set(json.loads(line)) <= {"ts", "kind", "provider", "model", "outcome", "status"}


def test_every_request_that_left_the_machine_is_counted_even_the_failures(tmp_path):
    # o 500 e repetido com backoff (e a repeticao tambem sai da maquina, entao tambem conta)
    stub = Stub([LLMResult(None, "timeout", 1.0, None, None), LLMResult(None, "http_500", 0.1, None, None, http_status=500), ok(),
                 LLMResult(None, "connection", 0.1, None, None), ok()])
    t, quota, _ = throttled(tmp_path, stub)
    for _ in range(4):
        t.turn("x")
    assert quota.used_today() == 5 and t.requests == 5
    outcomes = [json.loads(line)["outcome"] for line in (tmp_path / "quota.jsonl").read_text().splitlines()]
    assert outcomes == ["timeout", "http_500", "ok", "connection", "ok"]


def test_it_stops_before_spending_when_the_daily_quota_is_gone(tmp_path):
    stub = Stub([])
    t, quota, _ = throttled(tmp_path, stub, limit=3)
    for _ in range(3):
        t.turn("x")
    with pytest.raises(QuotaExhausted, match="3 requisicoes"):
        t.turn("x")
    assert stub.calls == 3, "a 4a chamada nao pode ter saido"


def test_a_new_utc_day_restores_the_quota(tmp_path):
    wall = Wall(datetime(2026, 10, 20, 23, 59, tzinfo=UTC))
    stub = Stub([])
    t, quota, _ = throttled(tmp_path, stub, limit=1, wall=wall)
    t.turn("x")
    with pytest.raises(QuotaExhausted):
        t.turn("x")
    wall.at += timedelta(minutes=2)
    t.turn("x")
    assert stub.calls == 2


# --- 429 --------------------------------------------------------------------------------------------------------------------------------------
def test_a_per_minute_429_backs_off_and_retries_and_every_attempt_is_counted(tmp_path):
    stub = Stub([r429("rate"), ok()])
    t, quota, clk = throttled(tmp_path, stub, base=5.0)
    res = t.turn("x")
    assert res.error is None and stub.calls == 2 and t.retries == 1 and quota.used_today() == 2
    assert 5.0 in clk.sleeps, "espera o backoff base antes de tentar de novo"


def test_backoff_is_exponential_and_capped(tmp_path):
    stub = Stub([r429("rate")] * 4)
    t, _, clk = throttled(tmp_path, stub, retries=3, base=5.0)
    res = t.turn("x")
    waits = [s for s in clk.sleeps if s in (5.0, 10.0, 20.0)]
    assert waits == [5.0, 10.0, 20.0] and res.error == "http_429" and stub.calls == 4, "gasta max_retries e devolve o ultimo 429"


def test_retry_after_from_the_provider_wins_over_a_smaller_backoff_and_is_capped(tmp_path):
    t, _, clk = throttled(tmp_path, Stub([r429("rate", retry_after=30.0), ok()]), base=5.0)
    t.turn("x")
    assert 30.0 in clk.sleeps
    t2, _, clk2 = throttled(tmp_path / "b", Stub([r429("rate", retry_after=500.0), ok()]), base=5.0)
    t2.turn("x")
    assert max(clk2.sleeps) <= 60.0, "limite de 60s mesmo se o provedor pedir mais"


def test_a_daily_429_stops_everything_and_is_never_retried(tmp_path):
    stub = Stub([r429("daily")])
    t, quota, _ = throttled(tmp_path, stub)
    res = t.turn("x")
    assert res.quota_kind == "daily" and stub.calls == 1 and t.retries == 0 and quota.exhausted_today()
    with pytest.raises(QuotaExhausted):
        t.turn("x")
    assert stub.calls == 1
    assert QuotaLog(tmp_path / "quota.jsonl", 50, now=quota._now).remaining() == 0, "outro processo, no mesmo dia, tambem para"


def test_timeouts_and_connection_errors_are_not_retried_here(tmp_path):
    """Nao ha como saber se o pedido chegou ao servidor, e cada retentativa custaria o prazo inteiro: so conta e segue."""
    for err in ("timeout", "connection"):
        stub = Stub([LLMResult(None, err, 1.0, None, None)])
        t, quota, _ = throttled(tmp_path / err, stub)
        assert t.turn("x").error == err and stub.calls == 1 and t.retries == 0 and quota.used_today() == 1


# --- falha rapido: erro de protocolo custa UMA requisicao ----------------------------------------------------------------------------------
def http(status: int, detail: str | None = None) -> LLMResult:
    return LLMResult(None, f"http_{status}", 0.1, None, None, http_status=status, detail=detail)


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 405, 409, 410, 413, 422])
def test_a_protocol_error_aborts_on_the_spot_and_costs_exactly_one_request(tmp_path, status):
    stub = Stub([http(status, "detalhe do provedor")] + [ok()] * 30)
    t, quota, clk = throttled(tmp_path, stub)
    with pytest.raises(ProtocolError) as e:
        t.turn("x")
    assert stub.calls == 1, "nao repete o mesmo pedido"
    assert quota.used_today() == 1 and t.requests == 1 and t.retries == 0, "a requisicao que falhou e contada, e so ela"
    assert clk.sleeps == [], "sem backoff: o pedido e que esta errado"
    assert e.value.status == status and e.value.result.error == f"http_{status}" and "detalhe do provedor" in str(e.value)
    assert [json.loads(line)["outcome"] for line in (tmp_path / "quota.jsonl").read_text().splitlines()] == [f"http_{status}"]


def test_after_a_protocol_error_the_next_call_is_not_blocked_by_the_wrapper_but_the_caller_already_stopped(tmp_path):
    """O wrapper nao trava sozinho (quem chamou decide); o que ele garante e nao repetir por conta propria."""
    stub = Stub([http(404)])
    t, _, _ = throttled(tmp_path, stub)
    with pytest.raises(ProtocolError):
        t.turn("x")
    assert stub.calls == 1


@pytest.mark.parametrize("status", [408, 500, 502, 503, 504, 529])
def test_server_failures_back_off_exponentially_and_then_succeed(tmp_path, status):
    stub = Stub([http(status), http(status), ok()])
    t, quota, clk = throttled(tmp_path, stub, base=5.0)
    assert t.turn("x").error is None
    assert stub.calls == 3 and t.retries == 2 and quota.used_today() == 3, "cada tentativa conta"
    assert [s for s in clk.sleeps if s in (5.0, 10.0)] == [5.0, 10.0]


def test_a_persistent_5xx_gives_up_after_max_retries_and_returns_the_last_failure(tmp_path):
    stub = Stub([http(503)] * 4)
    t, _, _ = throttled(tmp_path, stub, retries=3)
    res = t.turn("x")
    assert res.error == "http_503" and stub.calls == 4 and t.retries == 3


def test_only_429_and_5xx_enter_backoff(tmp_path):
    """Contraprova do fail-fast: nenhum 4xx (fora 408/429) dorme nem repete."""
    for status in (400, 401, 403, 404):
        t, _, clk = throttled(tmp_path / str(status), Stub([http(status)]))
        with pytest.raises(ProtocolError):
            t.turn("x")
        assert clk.sleeps == [] and t.retries == 0


def test_fail_fast_can_be_turned_off_and_then_the_failure_is_returned_not_raised(tmp_path):
    clk = VClock()
    quota = QuotaLog(tmp_path / "q.jsonl", 50, now=Wall(datetime(2026, 10, 20, 12, tzinfo=UTC)))
    t = ThrottledLLM(Stub([http(404)]), limiter=RateLimiter(20, clock=clk.now, sleep=clk.sleep), quota=quota, sleep=clk.sleep,
                     fail_fast_on_protocol_error=False)
    assert t.turn("x").error == "http_404" and quota.used_today() == 1


def test_a_protocol_error_reported_inside_a_200_is_also_fail_fast(tmp_path):
    """O adaptador traduz `{"error": {"code": 404}}` dentro de um HTTP 200 para http_status=404: mesmo caminho."""
    t, _, _ = throttled(tmp_path, Stub([LLMResult(None, "http_404", 0.1, None, None, http_status=404)]))
    with pytest.raises(ProtocolError):
        t.turn("x")


def test_a_daily_429_is_still_not_an_exception_and_not_a_protocol_error(tmp_path):
    t, quota, _ = throttled(tmp_path, Stub([r429("daily")]))
    assert t.turn("x").quota_kind == "daily" and quota.exhausted_today()


# --- disjuntor: servico fora do ar nao pode comer a cota ---------------------------------------------------------------------------------------
def test_three_consecutive_service_failures_trip_the_breaker(tmp_path):
    stub = Stub([http(503)] * 40)
    t, quota, _ = throttled(tmp_path, stub, retries=1)
    t.turn("x")
    t.turn("x")
    with pytest.raises(ServiceUnstable) as e:
        t.turn("x")
    assert e.value.failures == 3 and stub.calls == 6, "3 chamadas x (1 + 1 retentativa) = 6, e para: nao queima os 50"
    assert quota.used_today() == 6


def test_a_success_resets_the_breaker(tmp_path):
    stub = Stub([http(503), http(503), ok(), http(503), http(503), ok()])
    t, _, _ = throttled(tmp_path, stub, retries=0)
    for _ in range(6):
        t.turn("x")  # nunca 3 seguidas
    assert t.consecutive_failures == 0


@pytest.mark.parametrize("bad", ["invalid_output:JSONDecodeError", "max_tokens", "no_text", "content_filter"])
def test_model_level_failures_do_not_trip_the_breaker(tmp_path, bad):
    """Saida invalida e do MODELO (o servico respondeu): e exatamente o que o smoke existe para medir, nao um motivo para abortar."""
    stub = Stub([LLMResult(None, bad, 0.1, None, None, http_status=200)] * 10)
    t, _, _ = throttled(tmp_path, stub)
    for _ in range(10):
        assert t.turn("x").error == bad


def test_timeouts_and_connection_errors_count_for_the_breaker(tmp_path):
    stub = Stub([LLMResult(None, "timeout", 1.0, None, None), LLMResult(None, "connection", 1.0, None, None), LLMResult(None, "timeout", 1.0, None, None)])
    t, _, _ = throttled(tmp_path, stub)
    t.turn("x")
    t.turn("x")
    with pytest.raises(ServiceUnstable):
        t.turn("x")


def test_the_breaker_can_be_disabled(tmp_path):
    clk = VClock()
    quota = QuotaLog(tmp_path / "q.jsonl", 50, now=Wall(datetime(2026, 10, 20, 12, tzinfo=UTC)))
    t = ThrottledLLM(Stub([http(503)] * 9), limiter=RateLimiter(20, clock=clk.now, sleep=clk.sleep), quota=quota, sleep=clk.sleep, max_retries=0,
                     max_consecutive_failures=0)
    for _ in range(9):
        assert t.turn("x").error == "http_503"


def test_classification_helpers():
    assert [is_protocol_error(http(s)) for s in (400, 401, 403, 404, 408, 429, 500)] == [True, True, True, True, False, False, False]
    assert [is_backoff_status(http(s)) for s in (400, 404, 408, 429, 500, 503)] == [False, False, True, True, True, True]
    assert not is_protocol_error(LLMResult(None, "timeout", 1.0, None, None)) and not is_protocol_error(ok())
