"""Mascarador de PII: roda ANTES de qualquer texto do lead ir ao LLM ou ao banco. O texto cru nao sai da funcao que o recebe.

Troca o que identifica uma pessoa por um marcador ([CPF], [EMAIL], [TELEFONE], [PLACA], [NOME], [NASCIMENTO], [CAMINHO], [SEGREDO]) e DEIXA
INTACTO o que a cotacao precisa: CEP, ano do carro, idade e data de inicio. Cobre mais formatos que o detector de `pii.py` (CPF sem pontuacao, telefone
com parenteses, placa antiga), que continua sendo o gate de envio: o mascarador reduz, o gate confere, e o que o gate ainda achar e SAFETY_GUARD.

LIMITE ASSUMIDO (PLAN, secao 14): e um PISO, nao uma garantia. Regex e uma lista de nomes conhecidos nao pegam todo nome proprio nem todo endereco.
O que nao e reconhecido passa; por isso o texto cru nunca e persistido e o gate roda por cima de tudo.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .pii import find_pii

_CPF_PUNCT = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_ELEVEN_DIGITS = re.compile(r"(?<!\d)\d{11}(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# Telefone: +55 opcional, DDD OBRIGATORIO (com ou sem parenteses), 9 opcional, 4 + 4 digitos. Sem DDD "2015 2016" (dois anos digitados juntos) viraria telefone,
# e um CEP (5-3 digitos) nunca casa: falta o segundo bloco de 4. O celular sem DDD ("91234-5678") tem o padrao proprio abaixo.
_PHONE = re.compile(r"(?<![\d-])(?:\+?55[\s.-]?)?(?:\(\s*\d{2}\s*\)|\d{2})[\s.-]?9?\d{4}[\s.-]?\d{4}(?![\d-])")
_LOCAL_PHONE = re.compile(r"(?<![\d-])9\d{4}-\d{4}(?![\d-])")
_PLACA = re.compile(r"\b[A-Za-z]{3}-?\d[A-Za-z0-9]\d{2}\b")
_HOME = re.compile(r"/Users/[A-Za-z0-9._-]+/\S*")
_SECRET = re.compile(r"sk-(?:ant|or)-[A-Za-z0-9_-]{6,}|(?i:bearer)\s+[A-Za-z0-9_\-.=]{8,}")
_NAME = re.compile(r"(?i:\b(?:meu nome (?:é|e)|me chamo|sou (?:o|a)|aqui (?:é|e) (?:o|a))\s+)"
                   r"([A-ZÀ-Ý][\wÀ-ÿ]+(?:\s+(?:d[aeo]s?\s+)?[A-ZÀ-Ý][\wÀ-ÿ]+){0,3})")
_BIRTHDATE = re.compile(r"(?i:\bnasc\w*\W{0,3}(?:em\W{0,3}|no dia\W{0,3}|dia\W{0,3})?)(\d{1,2}/\d{1,2}/\d{2,4})")


def cpf_is_valid(digits: str) -> bool:
    """Digitos verificadores do CPF. Separa um CPF de 11 digitos de um telefone de 11 digitos sem pontuacao."""
    if len(digits) != 11 or len(set(digits)) == 1:
        return False
    for n in (9, 10):
        s = sum(int(d) * w for d, w in zip(digits[:n], range(n + 1, 1, -1), strict=True))
        if int(digits[n]) != (s * 10 % 11) % 10:
            return False
    return True


@dataclass(frozen=True)
class Masked:
    text: str
    kinds: tuple[str, ...]   # QUE tipos foram mascarados (nunca o trecho)


class Masker:
    def __init__(self, known_names: Iterable[str] = ()) -> None:
        self._names = tuple(sorted({n.strip() for n in known_names if n and len(n.strip()) >= 3}, key=len, reverse=True))

    def mask(self, text: str) -> Masked:
        kinds: list[str] = []

        def sub(rx: re.Pattern[str], token: str, s: str, kind: str, group: int | None = None) -> str:
            def repl(m: re.Match[str]) -> str:
                kinds.append(kind)
                if group is None:
                    return token
                return m.group(0)[:m.start(group) - m.start(0)] + token + m.group(0)[m.end(group) - m.start(0):]
            return rx.sub(repl, s)

        out = text
        out = sub(_SECRET, "[SEGREDO]", out, "segredo")
        out = sub(_HOME, "[CAMINHO]", out, "caminho")
        out = sub(_EMAIL, "[EMAIL]", out, "email")
        out = sub(_CPF_PUNCT, "[CPF]", out, "cpf")
        out = _ELEVEN_DIGITS.sub(lambda m: self._eleven(m.group(0), kinds), out)
        out = sub(_BIRTHDATE, "[NASCIMENTO]", out, "nascimento", group=1)
        out = sub(_PHONE, "[TELEFONE]", out, "telefone")
        out = sub(_LOCAL_PHONE, "[TELEFONE]", out, "telefone")
        out = sub(_PLACA, "[PLACA]", out, "placa")
        out = sub(_NAME, "[NOME]", out, "nome", group=1)
        for name in self._names:
            out, n = re.subn(rf"(?i)(?<!\w){re.escape(name)}(?!\w)", "[NOME]", out)
            kinds += ["nome"] * n
        return Masked(out, tuple(dict.fromkeys(kinds)))

    @staticmethod
    def _eleven(digits: str, kinds: list[str]) -> str:
        if cpf_is_valid(digits):
            kinds.append("cpf")
            return "[CPF]"
        kinds.append("telefone")  # 11 digitos que nao sao CPF: celular com DDD e sem pontuacao
        return "[TELEFONE]"


def residual_pii(text: str) -> list[str]:
    """O que o detector de `pii.py` (o gate de envio) ainda enxerga DEPOIS de mascarar. Tem que ser vazio; se nao for, e SAFETY_GUARD (componente masker)."""
    return find_pii(text)
