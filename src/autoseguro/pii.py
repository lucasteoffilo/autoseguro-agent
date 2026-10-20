"""Detector de PII/segredo compartilhado: gate de envio ao LLM, higiene do repo e (na 2b) base do mascarador.

Um PISO, nao uma garantia: ele so enxerga os formatos abaixo. CPF sem pontuacao, telefone com parenteses e placa antiga
ficam para o mascarador da Etapa 2b, que tem teste proprio.
"""
from __future__ import annotations

import re

PATTERNS = {
    "cpf": re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    "telefone_br": re.compile(r"\+55 ?\d{2} ?9\d{4}-?\d{4}"),
    "placa_mercosul": re.compile(r"\b[A-Z]{3}\d[A-Z]\d{2}\b"),
    "caminho_de_home": re.compile(r"/Users/[A-Za-z0-9._-]+/"),
    "chave_anthropic": re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    "chave_openrouter": re.compile(r"sk-or-[A-Za-z0-9_-]{8,}"),
}
EMAIL_OK_DOMAINS = ("example.com", "example.org")


def find_pii(text: str) -> list[str]:
    """Tipos de PII/segredo encontrados em `text` (sem o trecho: quem chama nao deve reimprimir o achado)."""
    kinds = []
    for kind, rx in PATTERNS.items():
        for m in rx.finditer(text):
            if kind == "email" and m.group(0).lower().endswith(EMAIL_OK_DOMAINS):
                continue
            kinds.append(kind)
            break
    return kinds
