"""Dublês de teste. Nada daqui vai para o produto."""
from __future__ import annotations

from datetime import UTC, datetime

from autoseguro.handoff import (
    DeliveryReceipt,
    HandoffPackage,
    HandoffReason,
    MaskedMessage,
    QuoteRef,
    SinkUnavailable,
)

T0 = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)


def make_package(trace_id: str = "trc_0001", reason: HandoffReason = HandoffReason.QUOTE_UNAVAILABLE,
                 **over) -> HandoffPackage:
    base = dict(
        trace_id=trace_id, reason=reason, created_at=T0,
        qualification={"idade": 35, "veiculo_ano": 2022, "cep": "01310100", "plano_id": "completo", "data_inicio": None},
        missing=("data_inicio",),
        last_quote=QuoteRef(quote_id="qte_0001", plano_id="completo", status="unavailable"),
        recent_messages=(MaskedMessage("lead", "tenho [IDADE] anos, cep [CEP]", T0),
                         MaskedMessage("agent", "Um instante, estou consultando o sistema.", T0)),
        told_to_lead="Nao consegui gerar sua cotacao agora. Vou encaminhar sua conversa a um consultor.",
        precheck="ok",
    )
    base.update(over)
    return HandoffPackage(**base)


class InMemorySink:
    """Implementacao de referencia do contrato: serve de dublê e prova que a suite de contrato e satisfazivel."""

    def __init__(self) -> None:
        self.receipts: dict[str, DeliveryReceipt] = {}
        self.packages: dict[str, dict] = {}
        self.fail_times = 0

    def deliver(self, package: HandoffPackage) -> DeliveryReceipt:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise SinkUnavailable("falha transitoria simulada")
        if package.trace_id not in self.receipts:
            self.packages[package.trace_id] = package.to_dict()
            self.receipts[package.trace_id] = DeliveryReceipt(
                trace_id=package.trace_id, status="delivered", delivered_at=datetime.now(UTC),
                external_ref=f"mem:{package.trace_id}")
        return self.receipts[package.trace_id]
