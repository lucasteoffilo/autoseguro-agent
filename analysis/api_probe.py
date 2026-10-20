"""Sondagem do comportamento do POST /quote (regras, queda total, reproducibilidade, estatistica).

So stdlib. Cada modo mira uma instancia com configuracao diferente (ver analysis/README.md):
  rules   --port 8100   instancia sem falha/lentidao (make api-test-up): regras de negocio, deterministico
  outage  --port N      instancia com QUOTE_FAILURE_RATE=1: o que acontece com a API 100% fora
  seq     --port N      instancia com QUOTE_SEED e FAILURE_RATE=0.5: sequencia de falhas reproduzivel
  stats   --port 8000   instancia com a instabilidade padrao: taxas e latencia reais

Datas e anos de veiculo sao relativos a HOJE, para o script continuar valido quando virar o ano.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

TODAY = dt.date.today()
YEAR = TODAY.year


def _first_of_next_month(d: dt.date) -> dt.date:
    return (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)


NEXT_1 = _first_of_next_month(TODAY)
NEXT_15 = NEXT_1.replace(day=15)
NEXT_LAST = _first_of_next_month(NEXT_1) - dt.timedelta(days=1)
PAST = TODAY - dt.timedelta(days=90)
FAR = TODAY + dt.timedelta(days=3 * 365)

BASE = {"plano_id": "completo", "idade": 35, "veiculo_ano": YEAR - 4, "cep": "01310-100",
        "data_inicio": NEXT_15.isoformat()}


def call(port: int, payload: dict | None = None, raw: bytes | None = None, timeout: float = 30):
    data = raw if raw is not None else json.dumps(payload).encode()
    req = urllib.request.Request(f"http://localhost:{port}/quote", data=data,
                                 headers={"content-type": "application/json"}, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, e.read()
    except Exception as e:  # noqa: BLE001 - sondagem: queremos ver qualquer falha
        return "EXC", time.time() - t0, repr(e)
    try:
        body = json.loads(body)
    except ValueError:
        body = body.decode(errors="replace")
    return status, time.time() - t0, body


def compact(status, body) -> str:
    if status == 200 and isinstance(body, dict):
        m = body["multiplicadores"]
        s = (f"premio={body['premio_mensal']} plano={body['plano_id']} "
             f"mult(idade/veic/regiao)={m['faixa_etaria']}/{m['idade_veiculo']}/{m['regiao']}")
        pr = body.get("primeiro_pagamento_pro_rata")
        if pr:
            s += f" prorata={pr['valor_primeiro_pagamento']} ({pr['dias_cobrados']}/{pr['dias_no_mes']}d)"
        return s
    if isinstance(body, dict) and "detail" in body:  # formato do pydantic/FastAPI
        d = body["detail"]
        if isinstance(d, list) and d:
            return f"[pydantic] {d[0].get('loc')} {d[0].get('msg')}"
    return json.dumps(body, ensure_ascii=False)[:150]


def case(port: int, label: str, **over) -> None:
    p = dict(BASE)
    for k, v in over.items():
        if v == "__DEL__":
            p.pop(k, None)
        else:
            p[k] = v
    st, _, body = call(port, p)
    print(f"{label:38s} {str(st):4s} {compact(st, body)}")


def rules(port: int) -> None:
    print(f"# sondagem de regras em {TODAY.isoformat()} (hoje); ano do servidor assumido = {YEAR}")
    print("--- baseline")
    case(port, "payload base")
    print("--- idade (18-24 x1.6 | 25-29 x1.25 | 30-59 x1 | 60-75 x1.4 | 76+ recusa)")
    for i in [0, 17, 18, 24, 25, 29, 30, 59, 60, 75, 76, 200, 201, -1]:
        case(port, f"idade={i}", idade=i)
    case(port, "idade=35.5 (float)", idade=35.5)
    case(port, 'idade="35" (string)', idade="35")
    case(port, "idade ausente", idade="__DEL__")
    print(f"--- veiculo_ano (ano do servidor={YEAR}; idade 0-5 x1 | 6-10 x1.15 | 11-20 x1.45 | 21+ recusa)")
    for delta in [-1, 0, 5, 6, 10, 11, 20, 21]:
        case(port, f"veiculo_ano={YEAR - delta} (idade {delta})", veiculo_ano=YEAR - delta)
    case(port, "veiculo_ano=1949", veiculo_ano=1949)
    print("--- cep (alto risco: 07 08 21 26 59 -> x1.30)")
    for c in ["07000-000", "07000000", "08.000-000", " 08000-000", "8000000", "00000-000", "99999-999", "abc", "", "0"]:
        case(port, f"cep={c!r}", cep=c)
    case(port, "cep=7000000 (int)", cep=7000000)
    case(port, "cep omitido", cep="__DEL__")
    case(port, "cep=null", cep=None)
    print("--- plano_id")
    for pl in ["COMPLETO", "completo ", "gold", ""]:
        case(port, f"plano_id={pl!r}", plano_id=pl)
    case(port, "plano_id omitido", plano_id="__DEL__")
    case(port, "plano_id=null", plano_id=None)
    print("--- data_inicio (pro-rata se dia != 1)")
    datas = {"dia 1 do mes que vem": NEXT_1.isoformat(), "dia 15 do mes que vem": NEXT_15.isoformat(),
             "ultimo dia do mes que vem": NEXT_LAST.isoformat(), "90 dias NO PASSADO": PAST.isoformat(),
             "3 anos no futuro": FAR.isoformat(), "30/fev (inexistente)": f"{YEAR}-02-30",
             "formato dd/mm/aaaa": "15/07/2026", "formato compacto aaaammdd": NEXT_15.strftime("%Y%m%d"),
             "string vazia": "", "texto livre": "ontem"}
    for label, d in datas.items():
        case(port, f"data_inicio: {label}", data_inicio=d)
    case(port, "data_inicio=null", data_inicio=None)
    case(port, "data_inicio omitida", data_inicio="__DEL__")
    print("--- payload / extras")
    case(port, "campo extra desconhecido (ignorado?)", campo_extra="x")
    st, _, b = call(port, raw=b"{nao e json")
    print(f"{'JSON malformado':38s} {st:4} {compact(st, b)}")
    st, _, b = call(port, raw=b"")
    print(f"{'corpo vazio':38s} {st:4} {compact(st, b)}")
    print("--- campos da resposta 200:")
    _, _, b = call(port, dict(BASE))
    print(json.dumps(b, ensure_ascii=False, indent=1))


def outage(port: int) -> None:
    print(f"--- instancia 100% falha (:{port})")
    sts, bodies = Counter(), set()
    for _ in range(30):
        st, _, b = call(port, dict(BASE))
        sts[st] += 1
        bodies.add(json.dumps(b, sort_keys=True))
    print("status em 30 chamadas validas:", dict(sts), "| corpos distintos:", len(bodies))
    print("corpo:", sorted(bodies)[0])
    for label, over in [("idade=80 (seria recusa 422)", {"idade": 80}),
                        (f"veiculo {YEAR - 25} (seria recusa 422)", {"veiculo_ano": YEAR - 25}),
                        ("data_inicio invalida (seria 400)", {"data_inicio": "15/07/2026"})]:
        st, _, b = call(port, dict(BASE, **over))
        print(f"{label:38s} {st} {compact(st, b)}")
    st, _, b = call(port, {k: v for k, v in BASE.items() if k != "idade"})
    print(f"{'idade ausente (validacao pydantic)':38s} {st} {compact(st, b)}")


def seq(port: int, n: int) -> None:
    print("".join("." if call(port, dict(BASE))[0] == 200 else "x" for _ in range(n)))


def stats(port: int, n: int, workers: int) -> None:
    t0 = time.time()
    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(lambda _: call(port, dict(BASE), timeout=40), range(n)))
    print(f"{n} chamadas, {workers} em paralelo, {time.time() - t0:.1f}s no total")
    print("status:", dict(Counter(r[0] for r in res)))
    ok = sorted(r[1] for r in res if r[0] == 200)
    fast, slow = [x for x in ok if x < 2], [x for x in ok if x >= 2]
    f5 = [r[1] for r in res if r[0] in (500, 502, 503)]
    print(f"200 rapidos: {len(fast)} (max {max(fast):.2f}s) | 200 lentos: {len(slow)} (min {min(slow) if slow else 0:.2f}s)")
    print(f"latencia dos 5xx: max {max(f5) if f5 else 0:.2f}s")
    print(f"P(5xx)={len(f5) / n:.3f}  P(lento)={len(slow) / n:.3f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("rules", "outage", "seq", "stats"):
        p = sub.add_parser(name)
        p.add_argument("--port", type=int, required=True)
        if name == "seq":
            p.add_argument("--n", type=int, default=40)
        if name == "stats":
            p.add_argument("--n", type=int, default=400)
            p.add_argument("--workers", type=int, default=30)
    a = ap.parse_args()
    if a.mode == "rules":
        rules(a.port)
    elif a.mode == "outage":
        outage(a.port)
    elif a.mode == "seq":
        seq(a.port, a.n)
    else:
        stats(a.port, a.n, a.workers)


if __name__ == "__main__":
    main()
