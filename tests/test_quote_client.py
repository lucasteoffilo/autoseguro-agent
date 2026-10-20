"""Cliente da /quote: matriz de falhas com relogio virtual (sem sleep), a propriedade de UMA chamada em voo e a reproducao da simulacao."""
from __future__ import annotations

import random
from datetime import date

import pytest

from analysis import latency_sim
from autoseguro import budgets
from autoseguro.quote_client import InvalidInput, Quote, QuoteClient, Refused, Unavailable
from autoseguro.slots import QuoteRequest
from tests.fakes import FakeTransport, Step, VirtualClock, err5xx, ok, ok_body, pydantic422, refused

REQ = QuoteRequest("completo", 35, 2022, "01310100", date(2026, 11, 1))        # dia 1: sem pro-rata
REQ_MID = QuoteRequest("completo", 35, 2022, "01310100", date(2026, 11, 15))   # meio do mes: a API deve devolver pro-rata


def run(steps, *, request=REQ, budget=budgets.QUOTE_BUDGET_S, hold_after=None, seed=1, on_hold=None):
    clock = VirtualClock()
    transport = FakeTransport(clock, steps)
    holds: list[float] = []
    callback = on_hold or (lambda: holds.append(round(clock.now(), 6)))
    out = QuoteClient(transport, clock, random.Random(seed)).quote(
        request, budget_s=budget, hold_after_s=hold_after, on_hold=callback if hold_after is not None else None)
    return out, transport, clock, holds


# --- caminho feliz e retry ----------------------------------------------------------------------------
def test_first_try_success():
    out, tr, _, _ = run([ok(0.1)])
    assert isinstance(out, Quote) and out.plano_id == "completo" and out.premio_mensal == 209.9
    assert tr.calls == 1 and out.elapsed_s == pytest.approx(0.1) and out.attempts[0].decision == "accept"
    assert out.raw["premio_mensal"] == 209.9  # a resposta da API segue inteira para persistir


def test_three_5xx_then_success_within_the_budget():
    out, tr, _, _ = run([err5xx(503), err5xx(502), err5xx(500), ok(0.1)])
    assert isinstance(out, Quote) and tr.calls == 4 and out.elapsed_s < budgets.QUOTE_BUDGET_S
    assert [a.decision for a in out.attempts] == ["retry", "retry", "retry", "accept"]
    assert [a.http_status for a in out.attempts] == [503, 502, 500, 200]
    assert [a.error_kind for a in out.attempts] == ["http_5xx", "http_5xx", "http_5xx", "none"]


def test_four_5xx_is_unavailable_before_the_budget_runs_out():
    out, tr, _, _ = run([err5xx(503)] * 4)
    assert isinstance(out, Unavailable) and out.reason == "attempts_exhausted" and out.component == "quote_api"
    assert tr.calls == 4 and out.elapsed_s < budgets.QUOTE_BUDGET_S and out.attempts[-1].decision == "stop_max_calls"


def test_backoff_grows_and_has_jitter():
    out, _, _, _ = run([err5xx()] * 4, seed=3)
    gaps = [b.started_s - (a.started_s + a.latency_s) for a, b in zip(out.attempts, out.attempts[1:])]
    base = budgets.QUOTE_BACKOFF_BASE_S
    for i, gap in enumerate(gaps):  # atraso k = base * 2^k * U(0.5, 1)
        assert 0.5 * base * 2**i - 1e-6 <= gap <= base * 2**i + 1e-6


# --- resposta lenta, mensagem de espera ----------------------------------------------------------------
def test_slow_8s_response_is_a_valid_quote_and_the_hold_fires_exactly_once():
    out, tr, _, holds = run([ok(8.0)], hold_after=budgets.HOLD_AFTER_S)
    assert isinstance(out, Quote) and tr.calls == 1 and out.elapsed_s == pytest.approx(8.0)
    assert holds == [pytest.approx(2.5)] and out.hold_fired and out.hold_error is None


def test_hold_does_not_fire_when_the_quote_is_fast():
    out, _, _, holds = run([ok(0.3)], hold_after=budgets.HOLD_AFTER_S)
    assert isinstance(out, Quote) and holds == [] and not out.hold_fired


def test_hold_fires_even_when_its_moment_falls_inside_a_backoff():
    out, _, _, holds = run([err5xx(503, 0.1), ok(0.1)], hold_after=0.2)
    assert isinstance(out, Quote) and holds == [pytest.approx(0.2)]


def test_hold_already_overdue_fires_before_the_first_call():
    _, _, _, holds = run([ok(0.1)], hold_after=0.0)
    assert holds == [0.0]


def test_a_failing_hold_callback_never_loses_the_quote():
    def boom():
        raise RuntimeError("canal fora do ar")

    out, _, _, _ = run([ok(5.0)], hold_after=1.0, on_hold=boom)
    assert isinstance(out, Quote) and out.hold_fired and out.hold_error == "RuntimeError"


# --- classificacao pelo corpo -------------------------------------------------------------------------
def test_business_refusal_is_final_and_not_retried():
    out, tr, _, _ = run([refused("Veiculo com mais de 20 anos nao e aceito.")])
    assert isinstance(out, Refused) and out.motivo.startswith("Veiculo") and tr.calls == 1 and out.attempts[0].decision == "stop_refused"


def test_pydantic_422_is_invalid_input_and_never_a_refusal():
    out, tr, _, _ = run([pydantic422()])
    assert isinstance(out, InvalidInput) and out.kind == "schema" and out.detail == "body.idade: Field required" and tr.calls == 1


def test_invalid_input_detail_never_repeats_the_offending_value():
    step = Step(0.05, 422, {"detail": [{"type": "x", "loc": ["body", "cep"], "msg": "bad", "input": "SEGREDO-123"}]})
    out, _, _, _ = run([step])
    assert isinstance(out, InvalidInput) and "SEGREDO" not in out.detail


def test_400_payload_invalido_is_invalid_input_without_retry():
    out, tr, _, _ = run([Step(0.05, 400, {"error": "payload_invalido", "detalhe": "day is out of range for month"})])
    assert isinstance(out, InvalidInput) and out.kind == "payload" and tr.calls == 1


def test_business_422_and_pydantic_422_are_told_apart_by_body_not_by_status():
    a, _, _, _ = run([refused()])
    b, _, _, _ = run([pydantic422()])
    assert type(a) is Refused and type(b) is InvalidInput


def test_html_502_from_a_proxy_is_transient():
    out, _, _, _ = run([Step(0.1, 502, "<html>Bad Gateway</html>"), ok(0.1)])
    assert isinstance(out, Quote) and out.attempts[0].error_kind == "http_5xx"


def test_429_is_transient():
    out, _, _, _ = run([Step(0.1, 429, {"error": "rate"}), ok(0.1)])
    assert isinstance(out, Quote) and out.attempts[0].error_kind == "http_429"


def test_connection_error_is_retried():
    out, _, _, _ = run([Step(0.1, None), ok(0.1)])
    assert isinstance(out, Quote) and out.attempts[0].error_kind == "connection" and out.attempts[0].http_status is None


def test_unexpected_status_is_not_retried_and_is_unavailable():
    out, tr, _, _ = run([Step(0.1, 404, "{}")])
    assert isinstance(out, Unavailable) and out.reason == "unexpected_response" and tr.calls == 1


def test_a_200_that_is_not_json_is_never_a_quote():
    out, _, _, _ = run([Step(0.1, 200, "<html>ok</html>")] * 4)
    assert isinstance(out, Unavailable) and {a.error_kind for a in out.attempts} == {"bad_body"}


# --- um 200 incoerente NUNCA vira preco -----------------------------------------------------------------
def test_200_for_the_wrong_plan_is_discarded():
    out, _, _, _ = run([ok(plano="essencial"), ok(plano="completo")])
    assert isinstance(out, Quote) and out.plano_id == "completo" and out.attempts[0].error_kind == "plan_mismatch"


def test_200_for_the_wrong_plan_on_every_attempt_is_unavailable_not_a_quote():
    out, _, _, _ = run([ok(plano="essencial")] * 4)
    assert isinstance(out, Unavailable)


@pytest.mark.parametrize("bad", [
    {"premio_mensal": "209.90"}, {"premio_mensal": True}, {"premio_mensal": 0}, {"premio_mensal": -1}, {"premio_mensal": float("inf")},
    {"franquia": None}, {"coberturas": "colisao"}, {"multiplicadores": {"faixa_etaria": 1.0}}, {"carencia": {"dias": "30"}},
    {"moeda": "USD"}, {"plano_nome": None},
])
def test_malformed_200_is_retried_and_never_shown(bad):
    out, _, _, _ = run([Step(0.1, 200, ok_body(**bad)), ok(0.1)])
    assert isinstance(out, Quote) and out.attempts[0].error_kind == "bad_body" and out.premio_mensal == 209.9


def test_mid_month_start_requires_the_pro_rata_in_the_answer():
    out, _, _, _ = run([ok(0.1), ok(0.1, pro_rata=True)], request=REQ_MID)
    assert isinstance(out, Quote) and out.attempts[0].error_kind == "bad_body" and out.primeiro_pagamento == 111.95
    first_of_month, _, _, _ = run([ok(0.1)], request=REQ)  # dia 1: sem pro-rata e esta certo
    assert isinstance(first_of_month, Quote) and first_of_month.primeiro_pagamento is None


# --- prazo, timeout e teto --------------------------------------------------------------------------------
def test_attempt_timeout_is_10s_then_retry_fits_in_the_remaining_budget():
    out, tr, _, _ = run([Step(12.0, 200, ok_body()), ok(0.2)])
    assert isinstance(out, Quote) and out.attempts[0].error_kind == "timeout" and out.attempts[0].latency_s == pytest.approx(10.0)
    assert tr.calls == 2 and 10.0 < out.elapsed_s < budgets.QUOTE_BUDGET_S


def test_budget_shorter_than_the_slow_response_ends_exactly_at_the_budget_and_says_so():
    out, tr, _, _ = run([Step(8.0, 200, ok_body())], budget=6.0)
    assert isinstance(out, Unavailable) and out.reason == "budget_exhausted" and out.last_error == "timeout"
    assert tr.calls == 1 and out.elapsed_s == pytest.approx(6.0)


def test_budget_below_the_minimum_attempt_makes_no_call_at_all():
    out, tr, _, _ = run([ok(0.1)], budget=0.5)
    assert isinstance(out, Unavailable) and out.reason == "budget_exhausted" and tr.calls == 0 and out.elapsed_s == 0.0


def test_a_retry_that_would_not_fit_in_the_budget_is_not_started():
    out, tr, _, _ = run([err5xx(503, 2.0), ok(0.1)], budget=3.0)  # sobra 1,0s: backoff + tentativa minima nao cabem
    assert isinstance(out, Unavailable) and out.reason == "budget_exhausted" and tr.calls == 1 and out.attempts[-1].decision == "stop_budget"


def test_the_remaining_turn_budget_is_what_the_client_respects():
    """O orquestrador passa o que sobrou do teto de 20s do turno: o cliente nunca ultrapassa."""
    out, _, _, _ = run([Step(30.0, 200, ok_body())] * 4, budget=4.0)
    assert out.elapsed_s <= 4.0 + 1e-6


# --- rastreabilidade ----------------------------------------------------------------------------------------
def test_every_attempt_is_recorded_for_the_quote_attempts_table():
    out, _, _, _ = run([err5xx(503), Step(12.0, 200, ok_body()), ok(0.1)])
    assert [a.n for a in out.attempts] == [1, 2, 3]
    assert all(a.started_s >= 0 and a.latency_s >= 0 for a in out.attempts)
    assert out.attempts[0].started_s == 0.0 and out.attempts[1].started_s > out.attempts[0].latency_s


# --- A PROPRIEDADE: nunca mais de uma chamada em voo -----------------------------------------------------------
def random_steps(rng: random.Random, n: int = 6) -> list[Step]:
    steps = []
    for _ in range(n):
        r = rng.random()
        if r < 0.25:
            steps.append(err5xx(rng.choice((500, 502, 503)), rng.uniform(0.04, 0.2)))
        elif r < 0.35:
            steps.append(ok(8.0 + rng.uniform(0, 0.05)))                      # a resposta lenta e valida
        elif r < 0.40:
            steps.append(Step(rng.uniform(10.5, 14.0), 200, ok_body()))       # estoura o timeout da tentativa
        elif r < 0.45:
            steps.append(Step(0.1, None))                                     # erro de conexao
        elif r < 0.50:
            steps.append(Step(0.1, 200, "<html>"))                            # corpo invalido
        elif r < 0.53:
            steps.append(refused())
        elif r < 0.55:
            steps.append(pydantic422())
        elif r < 0.57:
            steps.append(Step(0.1, 404, "{}"))
        elif r < 0.60:
            steps.append(ok(0.1, plano="essencial"))                          # 200 para o plano errado
        else:
            steps.append(ok(rng.uniform(0.04, 0.25)))
    return steps


SCRIPTED_MATRIX = [
    [ok(0.1)], [err5xx()] * 4, [err5xx(), err5xx(), err5xx(), ok()], [ok(8.0)], [Step(12.0, 200, ok_body()), ok(0.2)],
    [Step(0.1, None), Step(0.1, None), ok()], [refused()], [pydantic422()], [Step(8.0, 200, ok_body())] * 4,
    [ok(plano="essencial")] * 4, [Step(0.1, 200, "<html>")] * 4,
]


def test_never_more_than_one_call_in_flight():
    """Comportamento, nao texto: em NENHUMA cotacao o cliente tem mais de uma chamada em voo. Vale para a matriz roteirizada e para
    1.500 roteiros aleatorios (3 prazos x 500 sementes), e as chamadas nunca passam de 4 nem o tempo do prazo."""
    cases = [(steps, budgets.QUOTE_BUDGET_S, i) for i, steps in enumerate(SCRIPTED_MATRIX)]
    for seed in range(500):
        rng = random.Random(seed)
        for budget in (budgets.QUOTE_BUDGET_S, 6.0, 3.0):
            cases.append((random_steps(rng), budget, seed))
    for steps, budget, seed in cases:
        out, tr, _, _ = run(steps, budget=budget, seed=seed, hold_after=budgets.HOLD_AFTER_S)
        assert tr.max_inflight == 1, f"mais de uma chamada em voo (seed {seed}, prazo {budget})"
        assert tr.inflight == 0, "sobrou chamada em voo ao terminar"
        assert tr.calls == len(out.attempts) <= budgets.QUOTE_MAX_CALLS
        assert out.elapsed_s <= budget + 1e-6, f"estourou o prazo (seed {seed})"
        assert isinstance(out, (Quote, Refused, InvalidInput, Unavailable)), "toda cotacao termina com um resultado terminal"


def test_the_in_flight_instrument_can_see_two_calls_when_there_are_two():
    """Controle negativo: se o contador fosse cego, o teste acima seria verde por nada. Duas chamadas simultaneas TEM que aparecer."""
    clock = VirtualClock()
    tr = FakeTransport(clock, [ok(1.0), ok(1.0)])
    first, second = tr.start({}), tr.start({})
    assert tr.max_inflight == 2 and tr.inflight == 2
    first.abandon()
    second.wait(5.0)
    assert tr.inflight == 0


class _HedgingClient(QuoteClient):
    """DEFEITUOSO DE PROPOSITO: dispara uma segunda chamada aos 2s SEM abandonar a primeira. E exatamente o que a decisao descartou."""

    def _await(self, pending, end, hold):
        resp = pending.wait(min(2.0, end - self._clock.now()))
        if resp is not None:
            return resp, ""
        self._transport.start({})  # hedge: a primeira continua em voo
        return super()._await(pending, end, hold)


def test_the_in_flight_test_fails_for_a_client_that_hedges():
    """Controle negativo no CLIENTE (nao so no instrumento): se alguem acrescentar hedging, `max_inflight` passa a ser 2 e o teste
    `test_never_more_than_one_call_in_flight` reprova. Sem isto, a propriedade poderia estar 'verde' por construcao."""
    clock = VirtualClock()
    tr = FakeTransport(clock, [ok(8.0), ok(0.1)])
    out = _HedgingClient(tr, clock, random.Random(1)).quote(REQ)
    assert isinstance(out, Quote) and tr.max_inflight == 2


def test_a_quote_is_only_returned_when_it_is_coherent_with_the_request():
    for seed in range(300):
        out, tr, _, _ = run(random_steps(random.Random(seed)), seed=seed)
        if isinstance(out, Quote):
            assert out.plano_id == REQ.plano_id and out.premio_mensal > 0 and out.raw["moeda"] == "BRL"


# --- reproducao da simulacao com o cliente REAL ---------------------------------------------------------------------
def _sim_step(rng: random.Random) -> Step:
    r = rng.random()
    if r < 0.20:
        return err5xx(rng.choice((500, 502, 503)), rng.uniform(0.04, 0.20))
    if r < 0.30:
        return ok(8.0 + rng.uniform(0, 0.05))
    return ok(rng.uniform(0.04, 0.25))


def test_real_client_reproduces_the_policy_b_simulation():
    """Amarra o numero do PLAN (politica B) ao codigo que vai para producao: mesma distribuicao, mesmos p50/p95/chamadas/falha."""
    n, seed = 12_000, 7
    rng = random.Random(seed)
    times, calls, failures = [], 0, 0
    for i in range(n):
        out, tr, _, _ = run([_sim_step(rng) for _ in range(4)], seed=i)
        calls += tr.calls
        if isinstance(out, Quote):
            times.append(out.elapsed_s)
        else:
            failures += 1
    times.sort()
    p50, p95 = times[int(0.50 * len(times))], times[int(0.95 * len(times))]
    sim = latency_sim.simulate("nominal", "B", n, seed)
    assert abs(p50 - sim["p50_s"]) < 0.1, (p50, sim["p50_s"])
    assert abs(p95 - sim["p95_s"]) < 0.5, (p95, sim["p95_s"])
    assert abs(calls / n - sim["calls_per_quote"]) < 0.05
    assert abs(failures / n * 100 - sim["no_quote_in_budget_pct"]) < 0.3


def test_simulation_policy_b_uses_the_same_numbers_as_the_product():
    b = latency_sim.POLICIES["B"]
    assert (b["timeout"], latency_sim.DEADLINE, latency_sim.MAX_CALLS) == (
        budgets.QUOTE_ATTEMPT_TIMEOUT_S, budgets.QUOTE_BUDGET_S, budgets.QUOTE_MAX_CALLS)
