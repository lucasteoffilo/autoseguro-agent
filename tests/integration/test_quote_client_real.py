"""Cliente da /quote contra a API REAL de teste (docker-compose.test.yml, porta 8100, sem falhas injetadas). `make test-integration`.

Prova que a classificacao pelo CORPO bate com as formas reais de resposta (os dois 422 em especial), e nao so com as que eu imaginei nos testes
de relogio virtual.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

from autoseguro.quote_client import InvalidInput, Quote, QuoteClient, Refused
from autoseguro.slots import QuoteRequest

pytestmark = pytest.mark.integration
URL = os.getenv("QUOTE_API_URL", "http://localhost:8100")


def _next_month_day(day: int) -> date:
    first = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)
    return first.replace(day=day)


@pytest.fixture(scope="module")
def client():
    return QuoteClient.http(URL)


def req(**over) -> QuoteRequest:
    base = dict(plano_id="completo", idade=35, veiculo_ano=date.today().year - 4, cep="01310100", data_inicio=_next_month_day(1))
    base.update(over)
    return QuoteRequest(**base)


def test_a_real_quote_comes_back_validated_and_in_one_attempt(client):
    out = client.quote(req())
    assert isinstance(out, Quote) and out.plano_id == "completo" and out.premio_mensal == 209.9
    assert len(out.attempts) == 1 and out.attempts[0].http_status == 200 and out.carencia_dias == 30 and out.primeiro_pagamento is None


def test_mid_month_start_returns_the_pro_rata(client):
    out = client.quote(req(data_inicio=_next_month_day(15)))
    assert isinstance(out, Quote) and out.primeiro_pagamento is not None and 0 < out.primeiro_pagamento < out.premio_mensal


def test_business_refusal_is_a_refusal(client):
    out = client.quote(req(idade=80))
    assert isinstance(out, Refused) and "75" in out.motivo and len(out.attempts) == 1


def test_unknown_plan_arrives_as_a_refusal_shape_but_is_our_input_error(client):
    """A API manda 'plano inexistente' no MESMO formato da recusa de regra. Por isso o agente valida o plano antes (slots.normalize_plano)."""
    out = client.quote(req(plano_id="gold"))
    assert isinstance(out, Refused) and "inexistente" in out.motivo


def test_pydantic_422_is_invalid_input_not_a_refusal(client):
    out = client.quote(req(idade=201))
    assert isinstance(out, InvalidInput) and out.kind == "schema" and out.detail.startswith("body.idade")


def test_high_risk_cep_applies_the_regional_loading(client):
    plain, risky = client.quote(req()), client.quote(req(cep="07000000"))
    assert isinstance(plain, Quote) and isinstance(risky, Quote)
    assert risky.multiplicadores["regiao"] == 1.3 and risky.premio_mensal == pytest.approx(plain.premio_mensal * 1.3, rel=1e-3)
