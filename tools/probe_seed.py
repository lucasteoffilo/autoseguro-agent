"""Confere uma QUOTE_SEED contra a API de verdade, SEM LLM: N chamadas SEQUENCIAIS ao POST /quote, com status e latencia, ao lado do que a semente PREVE.

    QUOTE_SEED=91 make api-up && python tools/probe_seed.py --seed 91 --port 8000 --n 8

A sequencia de falhas da API e uma funcao da semente e da ORDEM das chamadas a /quote (o /health e o /planos nao a consomem). Por isso a API precisa ter acabado de subir:
com chamadas anteriores a sequencia ja andou, e a previsao nao vale. A previsao reproduz o sorteio do servico (vendor/quote-service/app/main.py): `random.Random(seed)`, um
`random()` por chamada, e um `choice(["500","502","503"])` a mais quando a chamada falha. Sai com 1 se o observado difere do previsto.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
import urllib.error
import urllib.request

FAILURE_RATE, SLOW_RATE, SLOW_SECONDS = 0.20, 0.10, 8.0   # os padroes do servico (docker-compose.yml)


def predict(seed: int, n: int, failure_rate: float = FAILURE_RATE, slow_rate: float = SLOW_RATE) -> list[str]:
    """A classe de cada uma das `n` primeiras chamadas: '5xx:<codigo>', 'lenta' ou 'ok'."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        roll = rng.random()
        if roll < failure_rate:
            out.append("5xx:" + rng.choice(["500", "502", "503"]))
        elif roll < failure_rate + slow_rate:
            out.append("lenta")
        else:
            out.append("ok")
    return out


def classify(status: int | str, seconds: float, slow_seconds: float = SLOW_SECONDS) -> str:
    if isinstance(status, int) and 500 <= status < 600:
        return f"5xx:{status}"
    return "lenta" if seconds >= slow_seconds * 0.75 else "ok"


def one_call(port: int) -> tuple[int | str, float]:
    today = dt.date.today()
    first_next = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    payload = {"plano_id": "completo", "idade": 35, "veiculo_ano": today.year - 4, "cep": "01310100", "data_inicio": first_next.isoformat()}
    req = urllib.request.Request(f"http://localhost:{port}/quote", data=json.dumps(payload).encode(), headers={"content-type": "application/json"}, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:   # noqa: S310
            r.read()
            return r.status, time.monotonic() - t0
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, time.monotonic() - t0
    except OSError as exc:
        return f"EXC:{type(exc).__name__}", time.monotonic() - t0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/probe_seed.py", description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args(argv)
    expected = predict(args.seed, args.n)
    print(f"semente {args.seed}, API em localhost:{args.port}, {args.n} chamadas sequenciais (a API precisa ter acabado de subir)")
    print(f"{'#':>2}  {'previsto':<9} {'observado':<9} {'HTTP':<4} {'segundos':>8}")
    bad = 0
    for i, want in enumerate(expected, 1):
        status, seconds = one_call(args.port)
        got = classify(status, seconds)
        bad += got != want
        print(f"{i:>2}  {want:<9} {got:<9} {status!s:<4} {seconds:>8.2f}  {'' if got == want else '<-- DIFERE'}")
    print("OK: a semente se comporta como o previsto." if not bad else f"{bad} chamada(s) diferem: a API ja tinha recebido chamadas? Reinicie com `make api-down && QUOTE_SEED={args.seed} make api-up`.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
