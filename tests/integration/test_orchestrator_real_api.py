"""O orquestrador contra a API REAL de teste (porta 8100): o preco que o lead le e o que a API devolve, por plano; a recusa de verdade; os quatro cenarios.
`make test-integration`."""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import date

import pytest

from autoseguro.cli import build_orchestrator
from autoseguro.store import SequentialIds, brl
from tools import scenarios

pytestmark = pytest.mark.integration
URL = os.getenv("QUOTE_API_URL", "http://localhost:8100")


def api_quote(payload: dict) -> dict:
    req = urllib.request.Request(URL + "/quote", data=json.dumps(payload).encode(), headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def conversation(lines, **kw):
    orc, store, _ = build_orchestrator(llm_mode="mock", api_url=URL, db_path=":memory:", ids=SequentialIds(), **kw)
    trace = orc.start()
    results = [orc.handle(trace, line) for line in lines]
    return orc, store, trace, results


@pytest.mark.parametrize("need,plano", [("só roubo e colisão", "essencial"), ("quero cobrir terceiros e vidros também", "completo"),
                                        ("quero carro reserva e assistência 24h, a completa", "premium")])
def test_the_price_the_lead_reads_is_the_one_the_api_returns_for_each_plan(need, plano):
    ano = date.today().year - 3
    orc, store, trace, results = conversation(["oi", f"é um carro {ano}, tenho 34 anos e moro no cep 30130-010", need, "pode começar dia 01/12/2099"])
    text = results[-1].terminal[0].text
    expected = api_quote({"plano_id": plano, "idade": 34, "veiculo_ano": ano, "cep": "30130010", "data_inicio": "2099-12-01"})
    assert results[-1].status == "quoted" and f"plano {expected['plano_nome']}" in text
    assert f"Mensalidade: {brl(expected['premio_mensal'])}" in text and f"Franquia: {brl(expected['franquia'])}" in text
    q = store.quotes(trace)[0]
    assert q["plano_id"] == plano and q["premio_mensal"] == expected["premio_mensal"] and json.loads(q["response"]) == expected
    assert store.money_not_in_quotes(trace) == []


@pytest.mark.parametrize("line,motivo", [("é um fusca 1998, tenho 45 anos e moro no cep 01310-100", "Veiculo com mais de 20 anos"),
                                         ("é um onix 2019, tenho 80 anos e moro no cep 01310-100", "Idade acima do limite")])
def test_a_real_refusal_is_recorded_as_a_refusal_and_closes_the_conversation(line, motivo):
    orc, store, trace, results = conversation(["oi", line, "só roubo e colisão", "começando dia 01/12/2099"])
    assert results[-1].terminal[0].kind == "refusal" and motivo in results[-1].terminal[0].text and results[-1].status == "refused"
    c = store.conversation(trace)
    assert c["status"] == "refused" and c["handoff_reason"] is None and store.quotes(trace)[0]["status"] == "refused"


def test_the_four_scenarios_end_the_way_the_plan_says(tmp_path):
    assert scenarios.main(["--out", str(tmp_path)]) == 0
    from autoseguro.store import Store
    store = Store(tmp_path / "scenarios.db")
    rows = {r["trace_id"]: r for r in (dict(x) for x in store._conn.execute("SELECT * FROM conversations ORDER BY trace_id"))}
    assert [(r["status"], r["handoff_reason"], r["failed_component"]) for r in rows.values()] == [
        ("quoted", None, None), ("refused", None, None), ("handoff", "QUOTE_UNAVAILABLE", "quote_api"), ("handoff", "HUMAN_REQUESTED", None)]
    for trace in rows:
        assert store.money_not_in_quotes(trace) == []
        msgs = store.messages(trace)
        assert all(m["id"] and m["status"] for m in msgs) and "[CPF]" not in "".join(m["text"] for m in msgs if m["role"] == "agent")
    assert "529.982" not in store.all_text()
