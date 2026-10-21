"""Normalizacao dos slots antes de chamar a /quote. Higiene de ENTRADA, nao regra de negocio.

A API nao valida nada disto e responde 200 com preco errado (ver docs/FINDINGS.md 1.5): CEP ausente ou sem o zero a esquerda
nao aplica o agravo regional; `plano_id` vazio vira Essencial; `data_inicio` no passado e aceita. Por isso o agente normaliza e
valida ANTES de chamar. Na duvida, recusa o valor (o agente pergunta de novo) em vez de adivinhar.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any


class SlotValueError(ValueError):
    """Valor de slot rejeitado. `code` e estavel e vai para logs e testes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SlotIssue:
    slot: str
    code: str


@dataclass(frozen=True)
class QuoteRequest:
    plano_id: str
    idade: int
    veiculo_ano: int
    cep: str | None = None            # 8 digitos; obrigatorio no fluxo de cotacao, opcional so na confirmacao da pre-checagem
    data_inicio: date | None = None   # hoje ou futura

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"plano_id": self.plano_id, "idade": self.idade, "veiculo_ano": self.veiculo_ano}
        if self.cep is not None:
            payload["cep"] = self.cep
        if self.data_inicio is not None:
            payload["data_inicio"] = self.data_inicio.isoformat()
        return payload


_DIGITS = re.compile(r"[0-9]+")
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _as_int(value: object, code: str) -> int:
    if isinstance(value, bool):
        raise SlotValueError(code)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and _DIGITS.fullmatch(value.strip()):
        return int(value.strip())
    raise SlotValueError(code)


def normalize_cep(value: object) -> str:
    """CEP como texto de 8 digitos. 7 digitos (zero a esquerda perdido) NAO e completado: pergunta de novo."""
    if value is None or isinstance(value, bool):
        raise SlotValueError("cep_ausente")
    if isinstance(value, int):
        raise SlotValueError("cep_nao_texto")  # um inteiro ja perdeu o zero a esquerda
    if not isinstance(value, str):
        raise SlotValueError("cep_invalido")
    digits = re.sub(r"[.\-\s]", "", value)
    if not _DIGITS.fullmatch(digits):
        raise SlotValueError("cep_invalido")
    if len(digits) == 8:
        return digits
    raise SlotValueError("cep_incompleto" if len(digits) == 7 else "cep_invalido")


def normalize_plano(value: object, known_plans: Iterable[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SlotValueError("plano_ausente")
    plano = value.strip().lower()
    if plano not in set(known_plans):
        raise SlotValueError("plano_desconhecido")
    return plano


def normalize_ano(value: object, today: date) -> int:
    ano = _as_int(value, "ano_invalido")
    if ano < 1950 or ano > 2100:
        raise SlotValueError("ano_invalido")
    if ano > today.year:
        raise SlotValueError("ano_modelo_futuro")  # a API recusa como "fora das faixas"; quem decide e o humano
    return ano


def normalize_idade(value: object) -> int:
    idade = _as_int(value, "idade_invalida")
    if not 0 <= idade <= 200:
        raise SlotValueError("idade_invalida")
    return idade  # elegibilidade (18 a 75) e da API, nao daqui


def normalize_data_inicio(value: object, today: date) -> date:
    if isinstance(value, date):
        d = value
    elif isinstance(value, str) and _ISO_DATE.fullmatch(value.strip()):
        try:
            d = date.fromisoformat(value.strip())
        except ValueError:
            raise SlotValueError("data_invalida") from None
    else:
        raise SlotValueError("data_invalida")
    if d < today:
        raise SlotValueError("data_no_passado")
    return d


def build_quote_request(raw: Mapping[str, object], *, today: date, known_plans: Iterable[str]) -> QuoteRequest | tuple[SlotIssue, ...]:
    """Pedido de cotacao completo ou, se faltar ou for invalido algum slot, TODAS as pendencias de uma vez."""
    known = tuple(known_plans)
    normalizers = (
        ("plano_id", lambda v: normalize_plano(v, known)),
        ("idade", normalize_idade),
        ("veiculo_ano", lambda v: normalize_ano(v, today)),
        ("cep", normalize_cep),
        ("data_inicio", lambda v: normalize_data_inicio(v, today)),
    )
    values: dict[str, Any] = {}
    issues: list[SlotIssue] = []
    for slot, fn in normalizers:
        if raw.get(slot) in (None, ""):
            issues.append(SlotIssue(slot, "ausente"))
            continue
        try:
            values[slot] = fn(raw[slot])
        except SlotValueError as exc:
            issues.append(SlotIssue(slot, exc.code))
    return tuple(issues) if issues else QuoteRequest(**values)


def build_eligibility_request(raw: Mapping[str, object], *, today: date, plano_id: str, known_plans: Iterable[str]) -> QuoteRequest | tuple[SlotIssue, ...]:
    """O pedido da confirmacao da pre-checagem: so idade e ano, com a MESMA higiene de entrada do pedido completo. Sem CEP nem data (a recusa nao depende deles)."""
    known = tuple(known_plans)
    values: dict[str, Any] = {}
    issues: list[SlotIssue] = []
    for slot, fn in (("plano_id", lambda v: normalize_plano(v, known)), ("idade", normalize_idade), ("veiculo_ano", lambda v: normalize_ano(v, today))):
        value = plano_id if slot == "plano_id" else raw.get(slot)
        if value in (None, ""):
            issues.append(SlotIssue(slot, "ausente"))
            continue
        try:
            values[slot] = fn(value)
        except SlotValueError as exc:
            issues.append(SlotIssue(slot, exc.code))
    return tuple(issues) if issues else QuoteRequest(**values)
