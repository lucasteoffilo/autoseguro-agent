"""A causa provavel que o smoke e o ping mostram: cada falha conhecida tem uma dica, e nenhuma dica toca na chave."""
from __future__ import annotations

import pytest

from autoseguro.llm.config import LLMConfig
from autoseguro.llm.diagnose import describe_request, explain_failure
from tests.fake_servers import CANARY_KEY

OR = LLMConfig.from_env({"LLM_API_KEY": CANARY_KEY})
OR_PLAIN = LLMConfig.from_env({"LLM_API_KEY": CANARY_KEY, "LLM_STRUCTURED_OUTPUT": "none", "LLM_REASONING_EFFORT": "off"})


def test_the_request_description_names_what_the_provider_can_refuse():
    assert describe_request(OR) == "json_schema + require_parameters, reasoning=none"
    assert describe_request(OR_PLAIN) == "sem saida estruturada"


@pytest.mark.parametrize("status,needle", [(401, "LLM_API_KEY"), (402, ":free"), (403, "moderacao"), (404, "LLM_STRUCTURED_OUTPUT=none"),
                                           (400, "LLM_STRUCTURED_OUTPUT=none"), (422, "LLM_REASONING_EFFORT=off"), (429, "00:00 UTC"),
                                           (408, "servico"), (500, "servico"), (503, "servico"), (418, "recusou o pedido")])
def test_each_http_status_has_a_specific_hint(status, needle):
    assert needle in explain_failure(OR, f"http_{status}", status)


@pytest.mark.parametrize("error,needle", [("timeout", "prazo"), ("connection", "LLM_BASE_URL"), ("max_tokens", "LLM_REASONING_EFFORT"),
                                          ("invalid_output:JSONDecodeError", "schema local"), ("no_text", "sem texto"), ("no_choices", "sem texto"),
                                          ("content_filter", "filtrou"), ("provider_error:502", "dentro de uma resposta 200")])
def test_each_non_http_error_has_a_specific_hint(error, needle):
    assert needle in explain_failure(OR, error, None)


def test_a_404_only_blames_the_structured_request_when_it_was_sent():
    assert "require_parameters" in explain_failure(OR, "http_404", 404)
    assert "require_parameters" not in explain_failure(OR_PLAIN, "http_404", 404) and "LLM_MODEL" in explain_failure(OR_PLAIN, "http_404", 404)


def test_an_unknown_failure_still_gets_an_honest_answer():
    assert "nao classificada" in explain_failure(OR, "algo_novo", None)


@pytest.mark.parametrize("status", [None, 400, 401, 402, 403, 404, 408, 422, 429, 500, 503])
def test_no_hint_ever_contains_the_key_or_its_format(status):
    text = explain_failure(OR, f"http_{status}" if status else "timeout", status) + describe_request(OR)
    assert CANARY_KEY not in text and "sk-or" not in text
