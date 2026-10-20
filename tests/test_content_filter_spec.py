"""A especificacao do `content_filter` (docs/PLAN.md 5.6) amarrada ao codigo em que ela se apoia: se algo mudar, a especificacao nao deriva em silencio."""
from __future__ import annotations

from pathlib import Path

from autoseguro import budgets
from autoseguro.handoff import FailedComponent, HandoffReason
from autoseguro.llm.base import LLMResult
from autoseguro.llm.guarded import GuardedResult
from autoseguro.llm.throttle import is_backoff_status, is_protocol_error, is_service_failure
from tests.doubles import make_package

PLAN = (Path(__file__).resolve().parent.parent / "docs" / "PLAN.md").read_text(encoding="utf-8")
SECTION = PLAN[PLAN.index("### 5.6 Bloqueio do provedor"):PLAN.index("## 6. Guardrail do `reply`")]


def test_the_plan_states_the_three_rules_and_the_acceptance_tests():
    for needle in ("1 retry", "não extrai nada", "pergunta pendente por template", "nunca silêncio", "2º turno seguido filtrado",
                   "`SAFETY_GUARD` com `failed_component=llm`", "Um turno bem-sucedido zera o contador", "Testes de aceitação da 2b"):
        assert needle in SECTION, needle
    assert SECTION.count("(i)") == 1 and "(vi)" in SECTION


def test_the_plan_states_the_criterion_wording_that_was_approved():
    for needle in ("Saída válida em 100% das chamadas que o provedor entregou", "0 em mensagens benignas", "em adversariais é aceito",
                   "Falhas de serviço (timeout, 5xx, 429) ficam fora do denominador"):
        assert needle in SECTION, needle


def test_the_retry_the_spec_relies_on_exists_in_the_budgets():
    assert budgets.LLM_MAX_ATTEMPTS == 2 and budgets.LLM_CALL_TIMEOUT_S == 6.0 and budgets.TURN_CEILING_S == 20.0


def test_a_content_filter_is_neither_a_service_failure_nor_a_protocol_error_nor_a_backoff_case():
    res = LLMResult(None, "content_filter", 1.8, None, "content_filter", http_status=200)
    assert not is_service_failure(res) and not is_protocol_error(res) and not is_backoff_status(res)


def test_without_output_the_reply_is_the_template_never_the_model_text():
    g = GuardedResult(LLMResult(None, "content_filter", 1.8, None, "content_filter", http_status=200), ())
    assert g.output is None and not g.reply_ok and g.reply_source == "template_fallback"


def test_the_handoff_package_can_express_the_second_consecutive_block():
    pkg = make_package(reason=HandoffReason.SAFETY_GUARD)
    assert pkg.reason is HandoffReason.SAFETY_GUARD and pkg.failed_component is FailedComponent.LLM
