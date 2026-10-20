"""Suite de contrato de `HandoffSink`. Qualquer destino (SQLite, CRM, fila) tem que passar por ela.

Como usar: subclasse `SinkContract` num arquivo `test_*.py` com nome `Test...` e implemente os hooks.
A classe base nao e coletada sozinha (o nome nao comeca com `Test`).
"""
from __future__ import annotations

import pytest

from autoseguro.handoff import DeliveryReceipt, HandoffReason, HandoffSink, SinkUnavailable
from tests.doubles import make_package


class SinkContract:
    # --- hooks que cada implementacao fornece -----------------------------------------------------------
    def make_sink(self) -> HandoffSink:
        raise NotImplementedError

    def delivered_count(self, sink: HandoffSink, trace_id: str) -> int:
        """Quantas vezes o destino armazenou/enfileirou este trace_id (o contrato exige que seja 1)."""
        raise NotImplementedError

    def make_flaky_sink(self, failures: int) -> HandoffSink | None:
        """Sink que falha `failures` vezes com erro TRANSITORIO e depois funciona. None se o destino nao suporta."""
        return None

    # --- contrato ---------------------------------------------------------------------------------------
    def test_implements_protocol(self):
        assert isinstance(self.make_sink(), HandoffSink)

    def test_deliver_returns_receipt_for_the_same_trace(self):
        sink, pkg = self.make_sink(), make_package()
        receipt = sink.deliver(pkg)
        assert isinstance(receipt, DeliveryReceipt)
        assert receipt.trace_id == pkg.trace_id
        assert receipt.status in ("delivered", "queued")
        assert receipt.delivered_at.tzinfo is not None

    def test_deliver_is_idempotent_by_trace_id(self):
        sink, pkg = self.make_sink(), make_package()
        first, second = sink.deliver(pkg), sink.deliver(pkg)
        assert second == first, "reentrega deve devolver o mesmo recibo"
        assert self.delivered_count(sink, pkg.trace_id) == 1, "reentrega nao pode duplicar"

    def test_distinct_traces_are_independent(self):
        sink = self.make_sink()
        a, b = make_package("trc_a"), make_package("trc_b", HandoffReason.HUMAN_REQUESTED)
        sink.deliver(a)
        sink.deliver(b)
        assert self.delivered_count(sink, "trc_a") == 1 and self.delivered_count(sink, "trc_b") == 1

    def test_deliver_does_not_mutate_the_package(self):
        sink, pkg = self.make_sink(), make_package()
        before = pkg.to_dict()
        sink.deliver(pkg)
        assert pkg.to_dict() == before

    def test_transient_failure_is_signalled_and_retry_succeeds_without_duplicates(self):
        sink = self.make_flaky_sink(failures=2)
        if sink is None:
            pytest.skip("destino nao simula falha transitoria")
        pkg = make_package()
        for _ in range(2):
            with pytest.raises(SinkUnavailable):
                sink.deliver(pkg)
        assert self.delivered_count(sink, pkg.trace_id) == 0, "falha transitoria nao pode deixar entrega parcial"
        receipt = sink.deliver(pkg)
        assert receipt.trace_id == pkg.trace_id
        assert self.delivered_count(sink, pkg.trace_id) == 1
