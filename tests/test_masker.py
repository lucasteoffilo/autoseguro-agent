"""Mascarador: troca o que identifica e deixa intacto o que a cotacao precisa (CEP, ano, idade, data). O gate de envio nao pode achar nada depois.

Os valores de PII sao SINTETICOS e montados em tempo de execucao (tests/synthetic_pii.py); masker.json so guarda os modelos dos casos."""
from __future__ import annotations

import random

import pytest

from autoseguro.anchoring import read_text
from autoseguro.masker import Masker, cpf_is_valid, residual_pii
from autoseguro.pii import find_pii
from tests import synthetic_pii

FIX = synthetic_pii.load_fixture()
V = FIX["values"]
CASES = [(c["raw"].format(**V), c["token"], c["kind"]) for c in FIX["cases"]]
VALID_CPF, VALID_CPF_DIGITS = V["cpf"], V["cpf_digits"]
M = Masker()


@pytest.mark.parametrize("raw,token,kind", CASES)
def test_what_identifies_a_person_is_replaced_by_a_marker(raw, token, kind):
    r = M.mask(raw)
    assert token in r.text and kind in r.kinds
    assert residual_pii(r.text) == [], r.text


def test_known_names_are_masked_case_insensitively_and_only_as_whole_words():
    r = Masker(known_names=["Beltrano Souza", "Souza"]).mask("oi, aqui é o beltrano souza, mas o souzado não")
    assert r.text.count("[NOME]") == 1 and "souzado" in r.text and "nome" in r.kinds


def test_a_cpf_with_invalid_check_digits_is_not_called_a_cpf_but_is_still_masked_as_a_phone():
    assert not cpf_is_valid("11111111111") and not cpf_is_valid(V["cpf_bad_digits"]) and cpf_is_valid(VALID_CPF_DIGITS)
    r = M.mask(V["eleven_not_cpf"])
    assert r.text == "[TELEFONE]" and r.kinds == ("telefone",)


# --- o que a cotacao precisa NAO pode ser mascarado ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw", [
    "o cep é 01310-100", "cep 01310100", "01.310-100", "30130-010", "91234-567", "moro no cep 04538-132 mas n tenho certeza",
    "o carro é 2015 mas o modelo é 2016", "2015 2016", "2015/2016", "é um onix 2019, tenho 34 anos e moro no cep 30130-010",
    "tenho 42", "uns 35, quase 36 kkk", "nasci em 1990", "pode ser dia 01/11/2026", "segunda que vem", "2026-11-01", "tenho 34 anos e 2019 02 de carro",
])
def test_slot_data_survives_the_masker_untouched(raw):
    r = M.mask(raw)
    assert r.text == raw and r.kinds == (), r


def test_the_ledger_reads_the_slots_from_the_masked_text_and_the_masker_even_removes_false_candidates():
    """O mascarador roda ANTES da ancoragem: CEP, ano e idade chegam intactos. E ele ajuda: os dois ultimos digitos de um CPF cru ("...-25") virariam
    candidato a idade, e no texto mascarado nao existem mais."""
    cases = [
        ("é um onix 2019, tenho 34 anos e moro no cep 30130-010", ["30130010"], ["2019"], ["34"]),
        (FIX["with_slots"].format(**V), ["01310100"], ["2015"], ["42"]),
        (FIX["with_phone_and_slots"].format(**V), ["04538132"], ["2018"], ["29"]),
    ]
    for raw, ceps, years, ages in cases:
        masked = read_text(M.mask(raw).text, "idade")
        assert [c.value for c in masked.ceps] == ceps and [c.value for c in masked.years] == years and [c.value for c in masked.ages] == ages, raw
    raw_cpf = read_text(f"meu cpf {VALID_CPF}, tenho 42 anos", "idade")
    raw_ages = [c.value for c in raw_cpf.ages]
    assert "42" in raw_ages and len(raw_ages) > 1, "no texto CRU pedacos do CPF viram candidatos a idade: mais um motivo para mascarar antes"


def test_masking_is_idempotent_and_leaves_markers_alone():
    once = M.mask(f"cpf {VALID_CPF} email {V['email']} cel {V['tel_paren']}").text
    assert M.mask(once).text == once and once.count("[") == 3


def test_a_conversation_with_every_kind_of_pii_leaves_nothing_for_the_send_gate():
    raw = FIX["everything"].format(**V)
    r = M.mask(raw)
    assert find_pii(raw), "o texto cru TEM PII (senao o teste nao prova nada)"
    assert residual_pii(r.text) == [] and set(r.kinds) == {"nome", "cpf", "email", "telefone", "placa"}
    for kept in ("2018", "41 anos", "01310-100"):
        assert kept in r.text
    for gone in ("Maria", VALID_CPF, V["email2"].split("@")[0], V["tel_core"], V["placa_mercosul"]):
        assert gone not in r.text


def test_random_text_never_leaves_pii_the_send_gate_can_see():
    """Propriedade com semente: fragmentos de PII em formatos variados, misturados a dados de cotacao."""
    rng = random.Random(7)
    pii = [s.format(**V) for s in FIX["random_pii"]]
    clean = ["2015", "tenho 42", "cep 01310-100", "carro 2019", "uns 35", "dia 01/11/2026", "oi", "quanto custa?"]
    for _ in range(2000):
        parts = rng.sample(pii, rng.randint(0, 4)) + rng.sample(clean, rng.randint(0, 3))
        rng.shuffle(parts)
        raw = " ".join(parts)
        assert residual_pii(M.mask(raw).text) == [], raw


def test_the_masker_does_not_report_what_it_masked_only_the_kind():
    r = M.mask(f"cpf {VALID_CPF}")
    assert r.kinds == ("cpf",) and VALID_CPF not in repr(r)
