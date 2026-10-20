"""Pacote de handoff, vocabulario de motivos e contrato de destino (aplicado ao dublê em memoria)."""
from __future__ import annotations

import json
import re
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path

import pytest

from autoseguro.handoff import QUALIFICATION_SLOTS, HandoffReason, HandoffSink, SinkRejected
from tests.doubles import InMemorySink, make_package
from tests.pii_patterns import find_pii
from tests.sink_contract import SinkContract

ROOT = Path(__file__).resolve().parent.parent


class TestInMemorySinkContract(SinkContract):
    """O dublê prova que a suite e satisfazivel. O SqliteSink da Etapa 2b herda desta mesma classe base."""

    def make_sink(self):
        return InMemorySink()

    def delivered_count(self, sink, trace_id):
        return int(trace_id in sink.receipts)

    def make_flaky_sink(self, failures):
        sink = InMemorySink()
        sink.fail_times = failures
        return sink


class _DuplicatingSink(InMemorySink):
    """Defeituoso de proposito: conta uma entrega a cada chamada (nao e idempotente)."""

    def __init__(self):
        super().__init__()
        self.calls: dict[str, int] = {}

    def deliver(self, package):
        self.calls[package.trace_id] = self.calls.get(package.trace_id, 0) + 1
        return super().deliver(package)


class _WrongExceptionSink(InMemorySink):
    """Defeituoso de proposito: falha transitoria vaza RuntimeError em vez de SinkUnavailable."""

    def deliver(self, package):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("deveria ser SinkUnavailable")
        return super().deliver(package)


class _BrokenIdempotence(SinkContract):
    def make_sink(self):
        return _DuplicatingSink()

    def delivered_count(self, sink, trace_id):
        return sink.calls.get(trace_id, 0)


class _BrokenException(SinkContract):
    def make_sink(self):
        return _WrongExceptionSink()

    def delivered_count(self, sink, trace_id):
        return int(trace_id in sink.receipts)

    def make_flaky_sink(self, failures):
        sink = _WrongExceptionSink()
        sink.fail_times = failures
        return sink


def test_contract_suite_catches_a_non_idempotent_sink():
    with pytest.raises(AssertionError):
        _BrokenIdempotence().test_deliver_is_idempotent_by_trace_id()


def test_contract_suite_catches_a_sink_that_leaks_the_wrong_exception():
    with pytest.raises(RuntimeError):
        _BrokenException().test_transient_failure_is_signalled_and_retry_succeeds_without_duplicates()


# --- vocabulario ----------------------------------------------------------------------------------------
def test_reason_vocabulary_matches_the_plan_table():
    """docs/PLAN.md secao 4 e o enum nao podem divergir: quem consome o pacote le o PLAN."""
    plan = (ROOT / "docs" / "PLAN.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"^\| `([A-Z][A-Z_]+)` \|", plan, flags=re.MULTILINE))
    assert documented == {r.value for r in HandoffReason}


def test_reason_values_equal_their_names():
    assert all(r.value == r.name for r in HandoffReason) and len(HandoffReason) == 12


# --- pacote ---------------------------------------------------------------------------------------------
def test_package_serialises_to_json_and_round_trips_the_reason():
    d = make_package().to_dict()
    back = json.loads(json.dumps(d))
    assert HandoffReason(back["reason"]) is HandoffReason.QUOTE_UNAVAILABLE
    assert back["schema_version"] == 1 and back["last_quote"]["quote_id"] == "qte_0001"
    assert datetime.fromisoformat(back["created_at"]).tzinfo is not None


def test_package_is_immutable():
    pkg = make_package()
    with pytest.raises(FrozenInstanceError):
        pkg.trace_id = "outro"  # type: ignore[misc]
    with pytest.raises(TypeError):
        pkg.qualification["idade"] = 99  # type: ignore[index]


def test_package_cannot_exist_without_what_was_told_to_the_lead():
    with pytest.raises(ValueError, match="told_to_lead"):
        make_package(told_to_lead="   ")


def test_package_requires_timezone():
    with pytest.raises(ValueError, match="fuso"):
        make_package(created_at=datetime(2026, 10, 20, 15, 0))


@pytest.mark.parametrize("campo", ["cpf", "nome", "email", "telefone", "placa"])
def test_package_rejects_direct_identifiers_in_qualification(campo):
    with pytest.raises(ValueError, match="nao permitidos"):
        make_package(qualification={campo: "x"})


def test_qualification_slots_are_only_quote_inputs():
    assert set(QUALIFICATION_SLOTS) == {"idade", "veiculo_ano", "cep", "plano_id", "data_inicio"}


def test_serialised_package_is_free_of_pii_patterns():
    assert find_pii(json.dumps(make_package().to_dict(), ensure_ascii=False)) == []


def test_pii_detector_would_flag_a_leaky_package():
    """Controle negativo: se uma mensagem crua passar, o detector enxerga (amostra montada em tempo de execucao)."""
    leaky = make_package(told_to_lead="fale com " + "joao" + "@" + "gmail.com")
    assert find_pii(json.dumps(leaky.to_dict())) == ["email"]


def test_sink_rejected_is_distinct_from_unavailable():
    from autoseguro.handoff import SinkUnavailable
    assert not issubclass(SinkRejected, SinkUnavailable) and not issubclass(SinkUnavailable, SinkRejected)


def test_in_memory_sink_is_a_handoff_sink():
    assert isinstance(InMemorySink(), HandoffSink)
