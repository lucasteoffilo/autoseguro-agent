"""As QUOTE_SEED documentadas (README e docs/DEMO.md): o que cada uma faz nas primeiras chamadas a /quote e que a previsao reproduz o sorteio do servico.

A conferencia contra a API de verdade (sem LLM) e `tools/probe_seed.py`; aqui se prova, sem rede, que a previsao usa o mesmo sorteio do codigo vendorizado e que as sementes escolhidas
tem a forma prometida."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.probe_seed import FAILURE_RATE, SLOW_RATE, SLOW_SECONDS, classify, predict

ROOT = Path(__file__).resolve().parent.parent
RETRY_SEED, SLOW_SEED = 91, 80   # a 1a /quote falha com 5xx e a 2a passa | a 1a /quote demora 8s e passa


def test_the_prediction_uses_the_same_draw_as_the_vendored_service():
    src = (ROOT / "vendor" / "quote-service" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'os.getenv("QUOTE_FAILURE_RATE", "0.20")' in src and 'os.getenv("QUOTE_SLOW_RATE", "0.10")' in src and 'os.getenv("QUOTE_SLOW_SECONDS", "8")' in src
    assert (FAILURE_RATE, SLOW_RATE, SLOW_SECONDS) == (0.20, 0.10, 8.0)
    assert 'random.Random(int(_seed))' in src and "roll = _rng.random()" in src and '_rng.choice(["500", "502", "503"])' in src
    assert "if roll < FAILURE_RATE:" in src and "if roll < FAILURE_RATE + SLOW_RATE:" in src


def test_the_retry_seed_fails_the_first_quote_with_a_5xx_and_passes_the_second():
    seq = predict(RETRY_SEED, 8)
    assert seq[0].startswith("5xx:") and seq[1] == "ok"
    assert seq[2:] == ["ok"] * 6, "o resto da sessao nao tem mais falha: o que aparecer no log nao veio da API"


def test_the_slow_seed_makes_the_first_quote_slow_and_the_rest_normal():
    seq = predict(SLOW_SEED, 8)
    assert seq[0] == "lenta" and seq[1:] == ["ok"] * 7


def test_the_prediction_is_deterministic_and_depends_on_the_seed():
    assert predict(91, 20) == predict(91, 20) and predict(91, 20) != predict(92, 20)


@pytest.mark.parametrize("status,seconds,expected", [(200, 0.01, "ok"), (422, 0.01, "ok"), (503, 0.02, "5xx:503"), (500, 0.0, "5xx:500"), (200, 8.03, "lenta"), (200, 5.9, "ok")])
def test_classification_of_an_observed_call(status, seconds, expected):
    assert classify(status, seconds) == expected
