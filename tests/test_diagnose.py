"""A causa provavel que o smoke e o ping mostram: cada falha conhecida tem uma dica, e nenhuma dica toca na chave."""
from __future__ import annotations

import pytest

from autoseguro.llm.config import LLMConfig
from autoseguro.llm.base import LLMResult
from autoseguro.llm.diagnose import describe_request, explain_failure, provider_name_from
from autoseguro.llm.throttle import QuotaLog
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


def test_a_404_mentions_the_parameters_only_when_they_were_sent():
    assert "require_parameters" in explain_failure(OR, "http_404", 404)
    assert "require_parameters" not in explain_failure(OR_PLAIN, "http_404", 404) and "LLM_MODEL" in explain_failure(OR_PLAIN, "http_404", 404)


def test_an_unknown_failure_still_gets_an_honest_answer():
    assert "nao classificada" in explain_failure(OR, "algo_novo", None)


@pytest.mark.parametrize("status", [None, 400, 401, 402, 403, 404, 408, 422, 429, 500, 503])
def test_no_hint_ever_contains_the_key_or_its_format(status):
    text = explain_failure(OR, f"http_{status}" if status else "timeout", status) + describe_request(OR)
    assert CANARY_KEY not in text and "sk-or" not in text


# --- o 404: duas hipoteses, e o provedor pelo nome quando o metadata o trouxe ---------------------------------------------------------------
# A mensagem antiga apontava so o formato do pedido, e foi isso que induziu o palpite errado (o provedor de origem estava fora do ar).
DETAIL = "Provider returned error | provedor=Nvidia | retorno=model endpoint is not available"


def test_a_404_with_special_parameters_lists_both_hypotheses_in_order():
    text = explain_failure(OR, "http_404", 404)
    assert "Duas hipoteses" in text
    assert "(1)" in text and "fora do ar" in text and "o modelo nao existe" in text
    assert "(2)" in text and "nenhum provedor aceita TODOS os parametros do pedido (json_schema + require_parameters, reasoning=none)" in text
    assert text.index("(1)") < text.index("(2)"), "a hipotese do modelo/provedor fora do ar vem primeiro: e a que o 404 generico mais esconde"


def test_a_404_tells_how_to_separate_the_two_hypotheses():
    text = explain_failure(OR, "http_404", 404)
    assert "LLM_STRUCTURED_OUTPUT=none" in text and "LLM_REASONING_EFFORT=off" in text
    assert "se o 404 continuar, e a (1)" in text and "se passar, e a (2)" in text


def test_a_404_names_the_provider_that_returned_the_error_when_the_metadata_had_it():
    text = explain_failure(OR, "http_404", 404, DETAIL)
    assert "o provedor Nvidia (o que devolveu o erro) esta fora do ar" in text
    assert "(2)" in text, "nomear o provedor nao tira a outra hipotese"


@pytest.mark.parametrize("detail", [None, "", "Provider returned error", "algo | retorno=x", "Provider returned error | provedor= | retorno=x"])
def test_a_404_without_a_provider_name_stays_generic(detail):
    text = explain_failure(OR, "http_404", 404, detail)
    assert "o provedor dele esta fora do ar" in text and "o que devolveu o erro" not in text


def test_a_404_on_a_simple_request_only_has_the_availability_hypothesis():
    text = explain_failure(OR_PLAIN, "http_404", 404, DETAIL)
    assert "O pedido ja e simples, entao os parametros nao sao a causa" in text
    assert "o provedor Nvidia (o que devolveu o erro) esta fora do ar, ou o modelo nao existe" in text
    assert "(2)" not in text and "nenhum provedor aceita" not in text and "require_parameters" not in text
    assert "LLM_MODEL" in text and "LLM_BASE_URL" in text


def test_reasoning_alone_is_also_a_parameter_a_provider_may_refuse():
    """O texto antigo so considerava o json_schema. Com `reasoning` enviado (e require_parameters), a hipotese (2) tambem vale."""
    cfg = LLMConfig.from_env({"LLM_API_KEY": CANARY_KEY, "LLM_STRUCTURED_OUTPUT": "none"})  # raciocinio: default none no OpenRouter
    text = explain_failure(cfg, "http_404", 404)
    assert "(2)" in text and "reasoning=none" in text and "json_schema" not in text.split("(2)")[1].split("Para separar")[0]


def test_the_anthropic_provider_has_no_openrouter_parameters_so_a_404_is_only_availability():
    cfg = LLMConfig.from_env({"LLM_PROVIDER": "anthropic", "ANTHROPIC_API_KEY": "placeholder-not-a-key"})
    assert "(2)" not in explain_failure(cfg, "http_404", 404)


@pytest.mark.parametrize("detail,expected", [
    ("m | provedor=Nvidia | retorno=x", "Nvidia"),
    ("m | provedor=Google AI Studio | retorno=x", "Google AI Studio"),
    ("m | provedor=Phala", "Phala"),
    ("provedor=AtlasCloud | retorno=x", "AtlasCloud"),
    ("m | provedor=  Phala  | retorno=x", "Phala"),
    ("m | retorno=provedor=falso", None),
    ("sem metadata", None),
    (None, None),
])
def test_provider_name_from_the_detail(detail, expected):
    assert provider_name_from(detail) == expected


def test_the_404_text_never_echoes_a_key_even_if_the_detail_somehow_carried_one():
    """O adaptador ja mascara o detalhe; aqui a defesa em profundidade: o nome do provedor passa de novo por redact."""
    text = explain_failure(OR, "http_404", 404, f"m | provedor=Prov-{CANARY_KEY} | retorno=x")
    assert CANARY_KEY not in text and "CANARY" not in text and "sk-or" not in text and "[REDACTED]" in text


def test_the_smoke_abort_message_carries_the_detail_to_the_diagnosis(tmp_path, capsys):
    from tools import smoke_llm
    res = LLMResult(None, "http_404", 0.1, None, None, http_status=404, detail=DETAIL)
    smoke_llm._report_abort("erro de protocolo", res, OR, CANARY_KEY, 0, 31, None, QuotaLog(tmp_path / "q.jsonl", 50), True, fast=True)
    err = capsys.readouterr().err
    assert "detalhe do provedor: " + DETAIL in err
    assert "o provedor Nvidia (o que devolveu o erro) esta fora do ar" in err and "(2) nenhum provedor aceita" in err
    assert CANARY_KEY not in err
