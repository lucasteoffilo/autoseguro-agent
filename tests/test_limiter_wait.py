"""Item 8: o tempo parado no limitador de taxa (e no backoff de 429) e medido na chamada, somado por turno e gravado no meta, para a latencia reportada ser a do sistema."""
from __future__ import annotations

import pytest

from autoseguro.llm.base import LLMResult
from autoseguro.llm.throttle import ProtocolError, RateLimiter, ServiceUnstable
from autoseguro.logexport import _fmt_meta, export_markdown
from tests.test_orchestrator import GREET, HAPPY, Harness, ScriptedLLM, reply_json
from tests.test_throttle import Stub, VClock, http, ok, r429, throttled


def test_the_rate_limiter_reports_how_long_it_made_the_caller_wait():
    clk = VClock()
    lim = RateLimiter(20, clock=clk.now, sleep=clk.sleep)
    assert lim.wait() == 0.0, "a primeira chamada nao espera"
    assert lim.wait() == pytest.approx(3.15), "a segunda espera o espacamento de 60/rpm com 5% de margem"
    clk.t += 30.0
    assert lim.wait() == 0.0, "quem demora por conta propria nao espera"


def test_the_window_wait_is_reported_too():
    clk = VClock()
    lim = RateLimiter(5, clock=clk.now, sleep=clk.sleep, safety=0.0)
    waits = [lim.wait() for _ in range(6)]
    assert waits[:5] == [0.0] * 5 and waits[5] == pytest.approx(60.0)


def test_a_throttled_call_carries_the_limiter_wait_in_its_result(tmp_path):
    t, _, _ = throttled(tmp_path, Stub([ok(), ok()]))
    first, second = t.turn("a"), t.turn("b")
    assert first.wait_s == 0.0 and second.wait_s == pytest.approx(3.15)


def test_the_429_backoff_sleeps_count_as_wait_on_top_of_the_limiters(tmp_path):
    t, _, clk = throttled(tmp_path, Stub([r429(), r429(), ok()]), base=5.0)
    res = t.turn("a")
    assert res.error is None and clk.sleeps == [5.0, 10.0], "primeira chamada sem espera do limitador; depois o backoff de 5 e de 10 s"
    assert res.wait_s == pytest.approx(15.0)
    again = t.turn("b")
    assert again.wait_s == pytest.approx(3.15), "a espera do turno anterior nao vaza para o seguinte"


def test_a_protocol_error_and_an_unstable_service_carry_the_wait_too(tmp_path):
    t, _, _ = throttled(tmp_path, Stub([ok(), http(400)]))
    t.turn("a")
    with pytest.raises(ProtocolError) as exc:
        t.turn("b")
    assert exc.value.result.wait_s == pytest.approx(3.15)
    t2, _, _ = throttled(tmp_path / "x", Stub([http(503)] * 9), retries=0)
    with pytest.raises(ServiceUnstable) as exc2:
        for _ in range(4):
            t2.turn("c")
    assert exc2.value.result.wait_s == pytest.approx(3.15)


class Waiting:
    """Um LLM que diz que esperou `waits[i]` segundos no limitador em cada chamada, e devolve uma resposta valida do ScriptedLLM."""

    def __init__(self, inner, waits):
        self.inner, self.waits = inner, list(waits)
        self.provider, self.model, self.system_prompt = inner.provider, inner.model, inner.system_prompt

    def turn(self, user_message):
        from dataclasses import replace
        res = self.inner.turn(user_message)
        return replace(res, wait_s=self.waits.pop(0) if self.waits else 0.0)


def test_the_turn_meta_records_the_limiter_wait_and_the_export_shows_it():
    inner = ScriptedLLM(reply_json("Qual é o ano do modelo do seu carro?"))
    h = Harness(llm=Waiting(inner, [3.15]))
    h.say(GREET)
    assert h.meta(h.agent[0])["limiter_wait_s"] == 3.15
    assert "limiter_wait_s=3.15" in export_markdown(h.store, h.trace)


def test_a_turn_with_no_wait_has_no_field():
    h = Harness()
    h.run(*HAPPY[:2])
    assert all("limiter_wait_s" not in h.meta(m) for m in h.agent)
    assert "limiter_wait_s" not in _fmt_meta({"limiter_wait_s": 0.0})


def test_the_wait_is_summed_over_the_attempts_of_one_turn():
    from autoseguro.mock_llm import MockLLM
    from tests.test_orchestrator import BASE
    inner = MockLLM(BASE, failures=["content_filter"])             # 1a tentativa filtrada pelo provedor, 2a boa: o turno soma as duas esperas
    h = Harness(llm=Waiting(inner, [3.15, 4.0]))
    h.say(GREET)
    assert len(inner.calls) == 2 and h.meta(h.agent[0])["attempt"] == 2
    assert h.meta(h.agent[0])["limiter_wait_s"] == pytest.approx(7.15)


def test_a_wait_in_the_turn_that_ends_in_a_handoff_is_recorded_too():
    from tests.test_orchestrator import RaisingLLM
    exc = ProtocolError(LLMResult(None, "http_401", 0.1, None, None, http_status=401, wait_s=3.15))
    h = Harness(llm=RaisingLLM(exc))
    h.say(GREET)
    assert h.conv["handoff_detail"].startswith("protocolo:401") and h.meta(h.agent[0])["limiter_wait_s"] == 3.15
