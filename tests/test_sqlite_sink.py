"""O SqliteSink passa na MESMA suite de contrato de qualquer destino de handoff (tests/sink_contract.py), mais o que e especifico do SQLite."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from autoseguro.handoff import HandoffReason, SinkUnavailable
from autoseguro.store import RandomIds, SequentialIds, SqliteSink, Store, brl
from tests.doubles import make_package
from tests.sink_contract import SinkContract

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


class FlakySqliteSink(SqliteSink):
    def __init__(self, store: Store, failures: int) -> None:
        super().__init__(store)
        self.failures = failures

    def deliver(self, package):
        if self.failures > 0:
            self.failures -= 1
            raise SinkUnavailable("banco travado (simulado)")
        return super().deliver(package)


class TestSqliteSinkContract(SinkContract):
    def make_sink(self):
        return SqliteSink(Store(":memory:"))

    def delivered_count(self, sink, trace_id):
        with sink._store._lock:
            return sink._store._conn.execute("SELECT COUNT(*) FROM conversations WHERE trace_id = ? AND handoff_package IS NOT NULL", (trace_id,)).fetchone()[0]

    def make_flaky_sink(self, failures):
        return FlakySqliteSink(Store(":memory:"), failures)


def test_a_real_database_error_is_signalled_as_transient_and_leaves_no_partial_delivery(tmp_path):
    store = Store(tmp_path / "x.sqlite")
    sink = SqliteSink(store)
    store._conn.execute("DROP TABLE conversations")  # o banco "some": OperationalError
    with pytest.raises(SinkUnavailable):
        sink.deliver(make_package())


def test_the_package_is_stored_on_the_conversation_and_survives_a_reopen(tmp_path):
    path = tmp_path / "c.sqlite"
    store = Store(path)
    store.open_conversation("trc_0001", mode="mock", provider="mock", model="mock-1", now=T0)
    pkg = make_package("trc_0001", HandoffReason.HUMAN_REQUESTED)
    receipt = SqliteSink(store).deliver(pkg)
    store.close()
    again = Store(path)
    conv = again.conversation("trc_0001")
    assert conv["handoff_reason"] == "HUMAN_REQUESTED" and json.loads(conv["handoff_package"]) == pkg.to_dict()
    assert conv["handoff_external_ref"] == receipt.external_ref == "sqlite:trc_0001" and conv["mode"] == "mock"
    assert SqliteSink(again).deliver(pkg) == receipt


def test_a_package_for_a_conversation_the_database_does_not_know_still_lands():
    store = Store(":memory:")
    SqliteSink(store).deliver(make_package("trc_orphan"))
    assert store.conversation("trc_orphan")["mode"] == "external" and store.conversation("trc_orphan")["handoff_package"]


# --- o esquema e a rastreabilidade ----------------------------------------------------------------------------------------------------------
def test_there_are_exactly_the_four_tables_of_the_plan():
    names = {r[0] for r in Store(":memory:")._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"conversations", "messages", "quotes", "quote_attempts"}


def test_foreign_keys_are_enforced_so_nothing_is_orphaned():
    store = Store(":memory:")
    with pytest.raises(sqlite3.IntegrityError):
        store.add_message("trc_x", "msg_1", role="lead", kind="text", text="oi", ts=T0, status="processed")


def test_messages_are_numbered_in_order_and_the_channel_id_is_deduped():
    store, ids = Store(":memory:"), SequentialIds()
    store.open_conversation("trc_0001", mode="mock", provider="mock", model="m", now=T0)
    store.add_message("trc_0001", ids.new("msg"), role="lead", kind="text", text="oi", ts=T0, status="processed", external_id="wamid.1")
    store.add_message("trc_0001", ids.new("msg"), role="agent", kind="text", text="olá", ts=T0, status="sent")
    assert [(m["seq"], m["role"]) for m in store.messages("trc_0001")] == [(1, "lead"), (2, "agent")]
    assert store.message_by_external("trc_0001", "wamid.1")["id"] == "msg_000001"
    with pytest.raises(sqlite3.IntegrityError):
        store.add_message("trc_0001", ids.new("msg"), role="lead", kind="text", text="oi de novo", ts=T0, status="processed", external_id="wamid.1")


def test_the_status_of_a_conversation_is_constrained():
    store = Store(":memory:")
    store.open_conversation("trc_0001", mode="mock", provider=None, model=None, now=T0)
    with pytest.raises(sqlite3.IntegrityError):
        store.update_conversation("trc_0001", T0, status="inventado")
    with pytest.raises(ValueError):
        store.update_conversation("trc_0001", T0, handoff_package="{}")  # so o sink grava o pacote


def test_reconstruct_gives_the_whole_story_by_trace_id():
    store, ids = Store(":memory:"), SequentialIds()
    t = ids.new("trc")
    store.open_conversation(t, mode="mock", provider="mock", model="m", now=T0)
    store.add_message(t, ids.new("msg"), role="lead", kind="text", text="oi", ts=T0, status="processed")
    q = store.add_quote(t, ids.new("qte"), kind="quote", status="ok", request={"plano_id": "essencial"}, response={"premio_mensal": 100.0}, plano_id="essencial",
                        premio_mensal=100.0, elapsed_s=0.4, now=T0)
    store.add_attempt(t, q, ids.new("att"), n=1, started_s=0.0, latency_s=0.4, http_status=200, error_kind="none", decision="done")
    story = store.reconstruct(t)
    assert [m["text"] for m in story["messages"]] == ["oi"] and story["quotes"][0]["attempts"][0]["http_status"] == 200 and story["handoff"] is None
    with pytest.raises(KeyError):
        store.reconstruct("trc_inexistente")


def test_the_price_invariant_is_a_query_every_reais_value_must_exist_in_the_quote():
    store, ids = Store(":memory:"), SequentialIds()
    t = ids.new("trc")
    store.open_conversation(t, mode="mock", provider="mock", model="m", now=T0)
    q = store.add_quote(t, ids.new("qte"), kind="quote", status="ok", request={}, plano_id="completo", premio_mensal=209.9, elapsed_s=0.1, now=T0,
                        response={"premio_mensal": 209.9, "franquia": 3000, "primeiro_pagamento_pro_rata": {"valor_primeiro_pagamento": 111.95}})
    store.add_message(t, ids.new("msg"), role="agent", kind="quote", status="sent", ts=T0, quote_id=q,
                      text="Mensalidade R$ 209,90, primeiro pagamento R$ 111,95, franquia R$ 3.000,00.")
    assert store.money_not_in_quotes(t) == []
    store.add_message(t, ids.new("msg"), role="agent", kind="text", status="sent", ts=T0, text="Consigo por R$ 150,00!")
    assert store.money_not_in_quotes(t) == ["R$ 150,00"], "um valor que nao esta em nenhuma cotacao e flagrado"


def test_a_refused_quote_does_not_license_any_amount():
    store, ids = Store(":memory:"), SequentialIds()
    t = ids.new("trc")
    store.open_conversation(t, mode="mock", provider="mock", model="m", now=T0)
    store.add_quote(t, ids.new("qte"), kind="quote", status="refused", request={}, response={"motivo": "Idade acima do limite", "premio_mensal": 99.0}, plano_id="x",
                    premio_mensal=None, elapsed_s=0.1, now=T0)
    store.add_message(t, ids.new("msg"), role="agent", kind="text", status="sent", ts=T0, text="Seria R$ 99,00")
    assert store.money_not_in_quotes(t) == ["R$ 99,00"]


@pytest.mark.parametrize("value,text", [(0.5, "R$ 0,50"), (209.9, "R$ 209,90"), (3000, "R$ 3.000,00"), (12345.6, "R$ 12.345,60"), (1234567.89, "R$ 1.234.567,89")])
def test_brl_formatting(value, text):
    assert brl(value) == text


def test_ids_are_unique_and_the_sequential_ones_are_readable():
    ids = SequentialIds()
    assert [ids.new("trc"), ids.new("trc"), ids.new("msg"), ids.new("qte"), ids.new("att")] == ["trc_0001", "trc_0002", "msg_000001", "qte_0001", "att_000001"]
    r = RandomIds()
    assert len({r.new("msg") for _ in range(1000)}) == 1000
