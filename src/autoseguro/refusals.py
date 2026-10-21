"""As recusas da /quote como um CONJUNTO FECHADO: o lead nunca le o texto cru que a API devolveu.

O servico responde 422 com `{"motivo": "<frase em portugues sem acento>"}`. Aquela frase e dele, nao nossa: vem sem acento, pode mudar de redacao sem aviso e, se o
`plans.json` ganhar uma regra, ganha um motivo que este codigo nunca viu. Entao o motivo vira um CODIGO (`RefusalKind`) e cada codigo tem um template acentuado
(`templates.refusal_text`). O que nao for reconhecido cai em `OTHER`, o generico: o lead le uma frase honesta e fixa, e o motivo cru fica so no banco (`quotes.response`).

Os limites que o texto cita (18, 75 anos, 20 anos de carro) saem do `/planos` (`Limits.from_planos`), nunca do codigo: se a regra mudar, o texto muda junto.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .facts import strip_accents


class RefusalKind(StrEnum):
    AGE_ABOVE_LIMIT = "age_above_limit"                      # "Idade acima do limite de aceitacao (75 anos)."
    AGE_OUT_OF_RANGE = "age_out_of_range"                    # "Idade fora das faixas aceitas." (menos de 18)
    VEHICLE_TOO_OLD = "vehicle_too_old"                      # "Veiculo com mais de 20 anos nao e aceito."
    VEHICLE_YEAR_OUT_OF_RANGE = "vehicle_year_out_of_range"  # "Idade do veiculo fora das faixas aceitas." (ano-modelo futuro)
    UNKNOWN_PLAN = "unknown_plan"                            # "Plano 'x' inexistente...": erro NOSSO. Nunca e dito ao lead como recusa
    OTHER = "other"                                          # qualquer motivo que este codigo nao conhece


# A ordem importa: "idade do veiculo fora" tambem contem "idade ... fora".
_PATTERNS = (
    (RefusalKind.VEHICLE_YEAR_OUT_OF_RANGE, re.compile(r"idade do veiculo fora")),
    (RefusalKind.VEHICLE_TOO_OLD, re.compile(r"veiculo com mais de")),
    (RefusalKind.AGE_ABOVE_LIMIT, re.compile(r"idade acima do limite")),
    (RefusalKind.AGE_OUT_OF_RANGE, re.compile(r"idade fora d")),
    (RefusalKind.UNKNOWN_PLAN, re.compile(r"plano .* inexistente")),
)


def classify_motive(motivo: str) -> RefusalKind:
    plain = strip_accents(motivo or "").lower()
    return next((kind for kind, rx in _PATTERNS if rx.search(plain)), RefusalKind.OTHER)


@dataclass(frozen=True)
class Limits:
    """O que a regra aceita, lido do /planos. `None` = a regra nao informa (o texto omite o numero em vez de inventar)."""

    min_age: int | None = None
    max_age: int | None = None
    max_vehicle_age: int | None = None

    @classmethod
    def from_planos(cls, planos: Mapping[str, Any]) -> Limits:
        regras = planos.get("regras", {})
        ages = [f for f in regras.get("faixa_etaria", ()) if not f.get("recusar")]
        cars = [f for f in regras.get("idade_veiculo", ()) if not f.get("recusar")]
        return cls(min(f["idade_min"] for f in ages) if ages else None, max(f["idade_max"] for f in ages) if ages else None,
                   max(f["anos_max"] for f in cars) if cars else None)
