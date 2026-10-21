"""CONTRATO da pre-checagem contra a API HTTP REAL de teste (porta 8100): bordas das faixas (derivadas do /planos) mais uma amostra aleatoria com semente registrada.

`make test-integration`. A divergencia nas duas direcoes reprova; a que importa e "a pre-checagem recusa e a API aceita"."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

from autoseguro.precheck import Rules
from autoseguro.refusals import classify_motive
from tests.precheck_contract import SEED, cases, compare

pytestmark = pytest.mark.contract
URL = os.getenv("QUOTE_API_URL", "http://localhost:8100")
ROOT = Path(__file__).resolve().parent.parent.parent


def http_service(idade: int, ano: int):
    body = json.dumps({"plano_id": "essencial", "idade": idade, "veiculo_ano": ano}).encode()
    req = urllib.request.Request(URL + "/quote", data=body, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:   # noqa: S310
            r.read()
            return True, None
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read())
        assert exc.code == 422 and payload.get("error") == "cotacao_recusada", f"resposta inesperada ({exc.code}) para idade={idade} ano={ano}: {payload}"
        return False, classify_motive(payload["motivo"])


def test_the_precheck_agrees_with_the_real_api_at_the_edges_and_on_the_seeded_sample():
    with urllib.request.urlopen(URL + "/planos", timeout=10) as r:   # noqa: S310
        rules = Rules.from_planos(json.load(r))                       # as faixas saem do /planos da API que vai ser comparada
    today = datetime.now(UTC).date()                                   # o relogio do servico e UTC
    bad = compare(rules, http_service, today)
    total = len(cases(rules, today))
    print(f"\n[contrato HTTP] {total} casos (bordas + amostra, semente {SEED}) | divergencias: {len(bad)}")
    assert not bad, f"{len(bad)} divergencia(s) em {total} casos:\n" + "\n".join(bad[:20])
