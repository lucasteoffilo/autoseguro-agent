"""O contrato da pre-checagem: ela e comparada com o SERVICO (a logica vendorizada, sem rede, ou a API real) nas BORDAS de cada faixa e numa amostra aleatoria.

As bordas saem do `/planos` (`Rules.boundaries`): nada de numero escrito a mao aqui. A amostra usa uma SEMENTE REGISTRADA (SEED), impressa em toda falha, para reproduzir.
As duas direcoes reprovam: "a pre-checagem recusa e a API aceita" (o lead seria recusado sem motivo: o caso grave) e "a pre-checagem aceita e a API recusa" (perde-se so a antecipacao).
"""
from __future__ import annotations

import random
from collections.abc import Callable
from datetime import date

from autoseguro.precheck import Rules, precheck
from autoseguro.refusals import RefusalKind, classify_motive
from evals.service import VendoredService

SEED = 20261021
RANDOM_SAMPLES = 400

# (aceita?, razao da recusa). Quem implementa: `vendored_service` (offline) e `http_service` (a API real, em tests/integration).
Service = Callable[[int, int], tuple[bool, RefusalKind | None]]


def vendored_service(today: date) -> Service:
    """A logica REAL do servico (vendor/quote-service/app/quote_logic.py), executada em processo, com o relogio fixado em `today`."""
    svc = VendoredService(today)

    def call(idade: int, ano: int) -> tuple[bool, RefusalKind | None]:
        status, body = svc.respond({"plano_id": "essencial", "idade": idade, "veiculo_ano": ano})
        if status == 200:
            return True, None
        assert status == 422, f"resposta inesperada ({status}) para idade={idade} ano={ano}: {body}"
        return False, classify_motive(body["motivo"])
    return call


def cases(rules: Rules, today: date) -> list[tuple[int, int, str]]:
    """(idade, ano, origem). Bordas: cada borda de idade com cada borda de idade do carro (o carro vira ano-modelo); depois a amostra aleatoria."""
    edges = rules.boundaries()
    ages = [n for n in edges["idade"] if 0 <= n <= 200]
    years = sorted({today.year - n for n in edges["anos_veiculo"] if 1950 <= today.year - n <= 2100})
    out = [(a, y, "borda") for a in ages for y in years]
    rng = random.Random(SEED)
    out += [(rng.randint(0, 120), rng.randint(1990, today.year + 2), "amostra") for _ in range(RANDOM_SAMPLES)]
    return out


def compare(rules: Rules, service: Service, today: date) -> list[str]:
    """As divergencias, uma por linha. Vazio = a pre-checagem concorda com o servico em todos os casos."""
    bad = []
    for idade, ano, origin in cases(rules, today):
        want_ok, want_kind = service(idade, ano)
        got = precheck(rules, idade=idade, veiculo_ano=ano, today=today)
        if got.accepts != want_ok:
            grave = "PRE-CHECAGEM RECUSA E O SERVICO ACEITA" if not got.accepts else "pre-checagem aceita e o servico recusa"
            bad.append(f"{grave}: idade={idade} ano={ano} ({origin}, semente {SEED})")
        elif got.kind != want_kind:
            bad.append(f"mesma decisao, razao diferente: idade={idade} ano={ano} previsto={got.kind} servico={want_kind} ({origin}, semente {SEED})")
    return bad
