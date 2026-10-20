"""Normalizacao de slots: higiene de entrada que a API nao faz (ver docs/FINDINGS.md 1.5)."""
from __future__ import annotations

from datetime import date

import pytest

from autoseguro.slots import (
    QuoteRequest,
    SlotIssue,
    SlotValueError,
    build_quote_request,
    normalize_ano,
    normalize_cep,
    normalize_data_inicio,
    normalize_idade,
    normalize_plano,
)

TODAY = date(2026, 10, 20)
PLANS = ("essencial", "completo", "premium")


@pytest.mark.parametrize("raw,expected", [("01310-100", "01310100"), ("01310100", "01310100"), ("01.310-100", "01310100"),
                                          (" 01310 100 ", "01310100"), ("08000-000", "08000000")])
def test_cep_is_a_string_of_eight_digits(raw, expected):
    assert normalize_cep(raw) == expected


@pytest.mark.parametrize("raw,code", [("1310100", "cep_incompleto"),     # zero a esquerda perdido: NAO completa, pergunta de novo
                                      ("8000000", "cep_incompleto"),     # completar para 08000000 seria chute; a API subcotaria em silencio
                                      (1310100, "cep_nao_texto"), (7000000, "cep_nao_texto"),
                                      ("abc", "cep_invalido"), ("", "cep_invalido"), ("123456789", "cep_invalido"),
                                      (None, "cep_ausente"), (True, "cep_ausente"), (["01310100"], "cep_invalido")])
def test_cep_rejects_instead_of_guessing(raw, code):
    with pytest.raises(SlotValueError) as e:
        normalize_cep(raw)
    assert e.value.code == code


@pytest.mark.parametrize("raw", ["completo", " Completo ", "PREMIUM"])
def test_plano_is_stripped_lowercased_and_checked(raw):
    assert normalize_plano(raw, PLANS) == raw.strip().lower()


@pytest.mark.parametrize("raw,code", [("gold", "plano_desconhecido"), ("", "plano_ausente"), (None, "plano_ausente"), (3, "plano_ausente")])
def test_plano_never_defaults_silently(raw, code):
    """A API troca plano vazio por Essencial em silencio; aqui vazio e erro."""
    with pytest.raises(SlotValueError) as e:
        normalize_plano(raw, PLANS)
    assert e.value.code == code


@pytest.mark.parametrize("raw,expected", [(2018, 2018), ("2018", 2018), (" 2026 ", 2026), (1950, 1950)])
def test_ano_ok(raw, expected):
    assert normalize_ano(raw, TODAY) == expected


@pytest.mark.parametrize("raw,code", [(2027, "ano_modelo_futuro"), (2100, "ano_modelo_futuro"), (1949, "ano_invalido"), (2101, "ano_invalido"),
                                      ("dois mil", "ano_invalido"), (20.5, "ano_invalido"), (True, "ano_invalido"), (None, "ano_invalido")])
def test_ano_future_goes_to_a_human_not_to_the_api(raw, code):
    """Ano-modelo futuro e recusado pela API como 'fora das faixas' (mensagem enganosa); aqui vira um codigo proprio."""
    with pytest.raises(SlotValueError) as e:
        normalize_ano(raw, TODAY)
    assert e.value.code == code


@pytest.mark.parametrize("raw,expected", [(35, 35), ("42", 42), (0, 0), (200, 200)])
def test_idade_ok_and_eligibility_is_not_decided_here(raw, expected):
    assert normalize_idade(raw) == expected  # 80 anos passa: quem recusa e a API


@pytest.mark.parametrize("raw", [-1, 201, "quarenta", None, True, 35.5])
def test_idade_rejects_what_the_api_schema_rejects(raw):
    with pytest.raises(SlotValueError):
        normalize_idade(raw)


@pytest.mark.parametrize("raw,expected", [("2026-10-20", TODAY), ("2026-11-15", date(2026, 11, 15)), (date(2026, 12, 1), date(2026, 12, 1))])
def test_data_inicio_today_or_future(raw, expected):
    assert normalize_data_inicio(raw, TODAY) == expected


@pytest.mark.parametrize("raw,code", [("2026-10-19", "data_no_passado"), ("2026-02-30", "data_invalida"), ("15/11/2026", "data_invalida"),
                                      ("20261115", "data_invalida"),  # a API aceita o formato compacto; aqui nao, para nao depender disso
                                      ("amanha", "data_invalida"), (None, "data_invalida")])
def test_data_inicio_rejects_past_and_non_iso(raw, code):
    with pytest.raises(SlotValueError) as e:
        normalize_data_inicio(raw, TODAY)
    assert e.value.code == code


def _raw(**over):
    base = {"plano_id": "Completo ", "idade": "35", "veiculo_ano": "2018", "cep": "01310-100", "data_inicio": "2026-11-15"}
    base.update(over)
    return base


def test_build_quote_request_normalizes_everything():
    req = build_quote_request(_raw(), today=TODAY, known_plans=PLANS)
    assert req == QuoteRequest("completo", 35, 2018, "01310100", date(2026, 11, 15))
    assert req.to_payload() == {"plano_id": "completo", "idade": 35, "veiculo_ano": 2018, "cep": "01310100", "data_inicio": "2026-11-15"}


def test_build_quote_request_returns_every_issue_at_once():
    got = build_quote_request(_raw(cep="8000000", plano_id="", veiculo_ano=2027, data_inicio=None), today=TODAY, known_plans=PLANS)
    assert set(got) == {SlotIssue("cep", "cep_incompleto"), SlotIssue("plano_id", "ausente"), SlotIssue("veiculo_ano", "ano_modelo_futuro"),
                        SlotIssue("data_inicio", "ausente")}


def test_missing_slots_are_issues_not_defaults():
    got = build_quote_request({}, today=TODAY, known_plans=PLANS)
    assert {i.slot for i in got} == {"plano_id", "idade", "veiculo_ano", "cep", "data_inicio"} and {i.code for i in got} == {"ausente"}
