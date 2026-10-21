"""O detalhe do erro do provedor vai para o registro (meta e handoff_detail), mascarado, redigido e truncado em 500; e o export nunca recusa a conversa por causa dele."""
from __future__ import annotations

import pytest

from autoseguro.llm.base import LLMResult
from autoseguro.llm.redact import DETAIL_LIMIT
from autoseguro.llm.throttle import ProtocolError, ServiceUnstable
from autoseguro.logexport import export_markdown, scan
from autoseguro.masker import Masked, Masker
from tests import synthetic_pii
from tests.test_orchestrator import BASE, GREET, Harness, RaisingLLM

V = synthetic_pii.values()
DETAIL = "Provider returned error | provedor=Acme | raw={'error': {'message': 'invalid request'}}"


def err(status=400, detail=DETAIL):
    return LLMResult(None, f"http_{status}", 2.3, None, None, http_status=status, detail=detail)


def test_a_protocol_error_records_the_providers_detail_in_the_meta_and_in_the_handoff_detail():
    h = Harness(llm=RaisingLLM(ProtocolError(err())))
    r = h.say(GREET)
    assert r.terminal[0].kind == "handoff"
    assert h.conv["handoff_detail"] == f"protocolo:400 | {DETAIL}" and (h.conv["handoff_reason"], h.conv["failed_component"]) == ("SAFETY_GUARD", "llm")
    meta = h.meta(h.agent[-1])
    assert meta["llm_error"] == "http_400" and meta["llm_error_detail"] == DETAIL and meta["llm_latency_s"] == 2.3 and meta["reply_source"] == "template_failure"
    assert DETAIL not in r.terminal[0].text, "o lead nunca le o detalhe do provedor"


def test_without_a_detail_the_handoff_detail_stays_just_the_code():
    h = Harness(llm=RaisingLLM(ProtocolError(err(detail=None))))
    h.say(GREET)
    assert h.conv["handoff_detail"] == "protocolo:400" and "llm_error_detail" not in h.meta(h.agent[-1])


def test_a_service_unstable_failure_also_carries_the_detail():
    h = Harness(llm=RaisingLLM(ServiceUnstable(err(503, "upstream indisponivel"), 3)))
    h.say(GREET)
    assert h.conv["handoff_detail"] == "servico_instavel | upstream indisponivel" and h.meta(h.agent[-1])["llm_error_detail"] == "upstream indisponivel"


def test_a_secret_in_the_detail_is_redacted_and_nothing_is_stored_raw():
    h = Harness(llm=RaisingLLM(ProtocolError(err(detail=f"chave rejeitada {V['key_or']} pelo provedor"))))
    h.say(GREET)
    stored = h.conv["handoff_detail"] + h.agent[-1]["meta"] + h.store.all_text()
    assert V["key_or"] not in stored and V["key_or"].split("-")[-1] not in stored


def test_pii_in_the_detail_is_masked_and_the_export_is_clean():
    h = Harness(llm=RaisingLLM(ProtocolError(err(detail=f"mensagem invalida de {V['email']} e {V['tel_paren']}"))))
    h.say(GREET)
    assert "[EMAIL]" in h.conv["handoff_detail"] and V["email"] not in h.conv["handoff_detail"] and V["tel_core"] not in h.conv["handoff_detail"]
    md = export_markdown(h.store, h.trace)
    assert scan(md) == [] and "[EMAIL]" in md and "protocolo:400" in md


def test_the_detail_is_truncated_at_the_same_limit_as_everything_else():
    h = Harness(llm=RaisingLLM(ProtocolError(err(detail="x" * 5000))))
    h.say(GREET)
    assert h.meta(h.agent[-1])["llm_error_detail"] == "x" * DETAIL_LIMIT + "…" and len(h.conv["handoff_detail"]) == len("protocolo:400 | ") + DETAIL_LIMIT + 1


def test_if_pii_survives_the_masker_only_the_mark_is_recorded_and_the_export_still_works():
    class LeakyMasker(Masker):
        def mask(self, text):
            return Masked(text, ())

    h = Harness(llm=RaisingLLM(ProtocolError(err(detail=f"telefone {V['tel_plus']} no corpo"))), masker=LeakyMasker())
    h.say(GREET)
    assert h.conv["handoff_detail"] == "protocolo:400 | detalhe omitido: pii" and h.meta(h.agent[-1])["llm_error_detail_omitted"] == "pii"
    assert V["tel_core"] not in h.store.all_text()
    md = export_markdown(h.store, h.trace)                  # nao recusa
    assert scan(md) == [] and "detalhe omitido: pii" in md


@pytest.mark.parametrize("kind", ["content_filter"])
def test_a_provider_filter_on_both_attempts_records_the_detail_in_the_fallback_message(kind):
    class Filtering:
        provider, model, system_prompt = "f", "f-1", "sistema"

        def __init__(self):
            self.calls = []

        def turn(self, user_message):
            self.calls.append(user_message)
            return LLMResult(None, kind, 0.4, None, "content_filter", http_status=200, detail="bloqueado pela politica do provedor")

    h = Harness(llm=Filtering())
    h.say(GREET)
    meta = h.meta(h.agent[-1])
    assert meta["reply_source"] == "template_fallback" and meta["llm_error"] == "content_filter" and meta["llm_error_detail"] == "bloqueado pela politica do provedor"
    h.say("oi de novo")
    assert h.conv["handoff_detail"] == "content_filter | bloqueado pela politica do provedor"


def test_the_export_shows_the_detail_in_the_decisions_table():
    h = Harness(llm=RaisingLLM(ProtocolError(err())))
    h.say(GREET)
    md = export_markdown(h.store, h.trace)
    assert 'llm_error="http_400"; llm_error_detail="Provider returned error' in md
