"""Padroes de PII/segredo compartilhados pelos testes (higiene do repo e contrato do pacote de handoff).

Um piso, nao uma garantia: formatos que o dataset nao tem (CPF sem pontuacao, telefone com parenteses) so entram
quando o mascarador da Etapa 2b existir e tiver seu proprio teste.
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
