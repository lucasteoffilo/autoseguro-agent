"""Higiene do repo: PII, segredos e linhas cruas do dataset.

As mensagens de falha mostram arquivo, linha e TIPO do achado, nunca o trecho: o teste nao pode vazar o que cobre.
"""
from __future__ import annotations

from pathlib import Path

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
               "/Users" + "/fulano/x", "sk-ant" + "-abcdefgh12"]
    fake = [("x.txt", ", ".join(samples))]
    kinds = {f.split("[")[1].rstrip("]") for f in _findings(fake)}
    assert kinds == set(PATTERNS)


def test_no_raw_dataset_lines_in_repo(dataset_bodies, repo_text_files):
    haystacks = [(rel, text.lower()) for rel, text in repo_text_files]
    leaks = sorted({rel for rel, text in haystacks for body in dataset_bodies if body in text})
    assert not leaks, f"trechos de mensagens do dataset encontrados em: {leaks}"
