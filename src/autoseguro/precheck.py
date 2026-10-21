"""Pre-checagem de elegibilidade: antecipa a RECUSA assim que idade e ano do carro estao verificados, em vez de perguntar CEP, cobertura e data a quem a API vai recusar.

Existe so por experiencia (PLAN, principio 3: a API e a palavra final). As faixas vem do `/planos` (`Rules.from_planos`), nunca do codigo, e a leitura espelha o
servico: a idade primeiro, o carro depois, a primeira faixa que casa decide, e "nenhuma faixa casou" tambem e recusa. O orquestrador NUNCA diz "recusado" por causa
desta funcao: uma previsao de recusa dispara uma chamada de confirmacao a `/quote` (so idade e ano, o plano mais barato, sem CEP nem data), e quem fala e a API.
Se a API aceitar, a divergencia e registrada e o preco parcial nunca e exibido; se a API estiver fora, o caso vai a um humano com este veredito no pacote.

A pre-checagem duplica semantica do servico. Por isso `tests/test_precheck_contract.py` a compara com a API nas bordas de cada faixa (derivadas do `/planos`) e numa
amostra aleatoria com semente registrada: "a pre-checagem recusa e a API aceita" reprova o teste. Se um dia deixar de compensar, ela sai sem afetar o resto.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from .refusals import RefusalKind, classify_motive

Label = Literal["ok", "recusa_provavel"]


@dataclass(frozen=True)
class Band:
    lo: int
    hi: int
    refuse: bool
    motivo: str

    def contains(self, n: int) -> bool:
        return self.lo <= n <= self.hi


@dataclass(frozen=True)
class Rules:
    """As faixas de aceitacao do `/planos`: idade do motorista e idade do veiculo (ano corrente menos o ano-modelo)."""

    age: tuple[Band, ...]
    vehicle: tuple[Band, ...]

    @classmethod
    def from_planos(cls, planos: Mapping[str, Any]) -> Rules:
        regras = planos["regras"]
        return cls(
            tuple(Band(f["idade_min"], f["idade_max"], bool(f.get("recusar")), f.get("motivo", "")) for f in regras["faixa_etaria"]),
            tuple(Band(f["anos_min"], f["anos_max"], bool(f.get("recusar")), f.get("motivo", "")) for f in regras["idade_veiculo"]))

    def boundaries(self) -> dict[str, list[int]]:
        """Os valores de borda de cada faixa e os vizinhos de fora (lo-1, lo, hi, hi+1), para o teste de contrato. Derivados da regra, nao escritos a mao."""
        def edges(bands: tuple[Band, ...], hi_cap: int) -> list[int]:
            out = {n for b in bands for n in (b.lo - 1, b.lo, b.hi, b.hi + 1)}
            return sorted(n for n in out if n <= hi_cap)
        return {"idade": edges(self.age, 200), "anos_veiculo": edges(self.vehicle, 200)}


@dataclass(frozen=True)
class Verdict:
    accepts: bool
    kind: RefusalKind | None = None      # a razao PREVISTA; quem decide o que o lead le e o motivo da API
    decided_by: Literal["idade", "veiculo_ano"] | None = None

    @property
    def label(self) -> Label:
        return "ok" if self.accepts else "recusa_provavel"


def _lookup(bands: tuple[Band, ...], n: int, nowhere: RefusalKind) -> RefusalKind | None:
    """None = aceita. Espelha o servico: a primeira faixa que contem `n` decide; nenhuma faixa casou = recusa."""
    for b in bands:
        if b.contains(n):
            return classify_motive(b.motivo) if b.refuse else None
    return nowhere


def precheck(rules: Rules, *, idade: int, veiculo_ano: int, today: date) -> Verdict:
    """A idade primeiro (o servico recusa na ordem idade, veiculo). `today` e o relogio DO SERVICO (perto de 31/12 o Brasil e o servidor em UTC discordam por horas)."""
    kind = _lookup(rules.age, idade, RefusalKind.AGE_OUT_OF_RANGE)
    if kind is not None:
        return Verdict(False, kind, "idade")
    kind = _lookup(rules.vehicle, today.year - veiculo_ano, RefusalKind.VEHICLE_YEAR_OUT_OF_RANGE)
    if kind is not None:
        return Verdict(False, kind, "veiculo_ano")
    return Verdict(True)
