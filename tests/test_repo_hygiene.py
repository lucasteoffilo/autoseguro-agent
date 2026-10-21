"""Higiene do repo: PII, segredos e linhas cruas do dataset.

As mensagens de falha mostram arquivo, linha e TIPO do achado, nunca o trecho: o teste nao pode vazar o que cobre.
"""
from __future__ import annotations

import re
from pathlib import Path

from autoseguro.masker import cpf_is_valid
from tests import synthetic_pii
from tests.pii_patterns import EMAIL_OK_DOMAINS, PATTERNS

ROOT = Path(__file__).resolve().parent.parent

def _findings(files: list[tuple[str, str]]) -> list[str]:
    out = []
    for rel, text in files:
        for n, line in enumerate(text.splitlines(), 1):
            for kind, rx in PATTERNS.items():
                for m in rx.finditer(line):
                    if kind == "email" and m.group(0).lower().endswith(EMAIL_OK_DOMAINS):
                        continue
                    out.append(f"{rel}:{n} [{kind}]")
    return out


def test_no_pii_or_secrets_in_repo(repo_text_files):
    found = _findings(repo_text_files)
    assert not found, "PII/segredo em arquivos do repo (trecho omitido de proposito):\n" + "\n".join(found[:30])


def test_pii_scanner_catches_what_it_should():
    """Guarda do guarda: se o scanner parar de enxergar, a higiene acima vira teatro."""
    # Amostras montadas em tempo de execucao: o literal completo nao pode existir na fonte deste arquivo.
    samples = ["111.222" + ".333-44", "a" + "@" + "b.com", "+55 11 9" + "1234-5678", "ABC1" + "D23",
               "/Users" + "/fulano/x", "sk-ant" + "-abcdefgh12", "sk-or" + "-v1-abcdefgh12"]
    fake = [("x.txt", ", ".join(samples))]
    kinds = {f.split("[")[1].rstrip("]") for f in _findings(fake)}
    assert kinds == set(PATTERNS)


_ELEVEN = re.compile(r"(?<![\d.-])\d{11}(?![\d.-])")


def _cpf_findings(files: list[tuple[str, str]]) -> list[str]:
    """O que um scanner externo apontaria como CPF: 11 digitos seguidos com os verificadores corretos (o formato com pontos ja e coberto acima)."""
    return [f"{rel}:{n} [cpf_valido]" for rel, text in files for n, line in enumerate(text.splitlines(), 1)
            for m in _ELEVEN.finditer(line) if cpf_is_valid(m.group(0))]


def test_no_valid_cpf_anywhere_in_repo_not_even_in_fixtures(repo_text_files):
    """Sem allowlist: as amostras sinteticas nascem em tempo de execucao (`tests/synthetic_pii.py`), nunca como literal em arquivo."""
    found = _cpf_findings(repo_text_files)
    assert not found, "CPF com verificadores validos em arquivos do repo (trecho omitido de proposito):\n" + "\n".join(found[:30])


def test_the_cpf_scanner_catches_a_valid_cpf_and_ignores_a_wrong_one():
    """Guarda do guarda, com o CPF montado na hora: o literal nao existe na fonte."""
    valid = synthetic_pii.cpf("hygiene")
    assert _cpf_findings([("x.txt", f"cpf {valid} e {synthetic_pii.with_wrong_check_digit(valid)}")]) == ["x.txt:1 [cpf_valido]"]


def test_the_synthetic_values_are_deterministic_and_the_cpfs_really_are_cpfs():
    a, b = synthetic_pii.values(), synthetic_pii.values()
    assert a == b
    assert cpf_is_valid(a["cpf_digits"]) and cpf_is_valid(a["cpf"].replace(".", "").replace("-", ""))
    assert not cpf_is_valid(a["cpf_bad_digits"]) and not cpf_is_valid(a["eleven_not_cpf"])


def test_no_raw_dataset_lines_in_repo(dataset_bodies, repo_text_files):
    haystacks = [(rel, text.lower()) for rel, text in repo_text_files]
    leaks = sorted({rel for rel, text in haystacks for body in dataset_bodies if body in text})
    assert not leaks, f"trechos de mensagens do dataset encontrados em: {leaks}"
