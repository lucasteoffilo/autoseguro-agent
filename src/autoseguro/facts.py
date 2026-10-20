"""Base de fatos injetada a partir do /planos: o UNICO material que o `reply` do LLM pode afirmar.

Cada fato tem um id, um texto e os TERMOS (cobertura, plano, carencia, franquia...) sobre os quais ele autoriza o LLM a falar.
O LLM declara em `facts_used` em quais fatos se apoiou; o guardrail confere que todo termo e todo numero do texto vem de fatos citados
(ou foi escrito pelo lead). A base e derivada do /planos, entao um plano novo ou uma carencia diferente entra sem mudar codigo.
Valores em dinheiro (franquia, mensalidade) NUNCA entram: vivem so nos templates de cotacao.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

COVERAGE_LABEL = {
    "colisao": "colisão", "roubo": "roubo", "furto": "furto", "terceiros": "danos a terceiros", "vidros": "vidros",
    "carro_reserva": "carro reserva", "assistencia_24h": "assistência 24h",
}
COVERAGE_IDS = frozenset(COVERAGE_LABEL)

# Termos que "carregam afirmacao". Aplicados ao texto SEM acentos e em minusculas.
_PLAIN_TERMS = {
    "colisao": r"\bcolis", "roubo": r"\broub", "furto": r"\bfurt", "terceiros": r"\bterceir", "vidros": r"\bvidro",
    "carro_reserva": r"carro[- ]reserva", "assistencia_24h": r"\bassistencia",
    "carencia": r"\bcarencia", "franquia": r"\bfranquia", "pro_rata": r"proporcional|pro[- ]?rata|primeiro pagamento",
}
_PLAIN = {k: re.compile(v) for k, v in _PLAIN_TERMS.items()}
_NUMBER_WORDS = {1: "um", 2: "dois", 3: "três", 4: "quatro", 5: "cinco"}
_NUMBER_WORDS_F = {1: "uma", 2: "duas", 3: "três", 4: "quatro", 5: "cinco"}  # "duas opções", nao "dois opções"


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1]


def _necessidades_fact(plans: list) -> Fact:
    """As opcoes de cobertura que o agente OFERECE ao lead ("so roubo e colisao, ou tambem terceiros e vidros, ou..."), derivadas dos planos.

    Perguntar a necessidade ja e nomear coberturas: o guardrail exige um fato citado para cada termo, e sem este fato a unica coisa citavel
    seria `plano:<id>`, que AFIRMA algo sobre um plano. Este fato autoriza nomear as coberturas e nada mais: nao tem nome de plano.
    Cada opcao e o que o plano seguinte acrescenta ao anterior (planos ordenados pelo numero de coberturas)."""
    tiers = sorted(plans, key=lambda p: len(p["coberturas"]))
    prev: set[str] = set()
    phrases: list[str] = []
    terms: set[str] = set()
    for i, p in enumerate(tiers):
        cov = list(p["coberturas"])
        new = [c for c in cov if c not in prev]
        if i == 0:
            phrases.append("só " + _join([COVERAGE_LABEL.get(c, c) for c in cov]))
        elif prev <= set(cov) and new:
            phrases.append("também " + _join([COVERAGE_LABEL.get(c, c) for c in new]))
        else:
            phrases.append(_join([COVERAGE_LABEL.get(c, c) for c in cov]))
        prev |= set(cov)
        terms |= set(cov)
    n = len(phrases)
    body = phrases[0] if n == 1 else "; ".join(phrases[:-1]) + "; ou " + phrases[-1]
    return Fact("necessidades", f"A necessidade de cobertura tem {_NUMBER_WORDS_F.get(n, str(n))} {'opção' if n == 1 else 'opções'}: {body}.", frozenset(terms))


@dataclass(frozen=True)
class Fact:
    id: str
    text: str
    terms: frozenset[str]

    @property
    def numbers(self) -> frozenset[str]:
        return frozenset(re.findall(r"[0-9]+", self.text))


@dataclass(frozen=True)
class FactBase:
    facts: Mapping[str, Fact]
    plan_coverages: Mapping[str, frozenset[str]]   # "plan_<id>" -> coberturas do plano
    plan_patterns: Mapping[str, re.Pattern[str]]   # "plan_<id>" -> nome do plano (case-sensitive: "Completo" != "completo")

    @classmethod
    def from_planos(cls, planos: Mapping) -> FactBase:
        facts: dict[str, Fact] = {}
        coverages: dict[str, frozenset[str]] = {}
        patterns: dict[str, re.Pattern[str]] = {}
        plans = planos["planos"]
        for p in plans:
            term = f"plan_{p['id']}"
            cov = frozenset(p["coberturas"])
            coverages[term] = cov
            patterns[term] = re.compile(rf"\b{re.escape(p['nome'])}\b")
            labels = [COVERAGE_LABEL.get(c, c) for c in p["coberturas"]]
            facts[f"plano:{p['id']}"] = Fact(f"plano:{p['id']}", f"O plano {p['nome']} cobre {_join(labels)}.", frozenset({term}) | cov)
        n = len(plans)
        facts["planos"] = Fact("planos", f"A AutoSeguro tem {_NUMBER_WORDS.get(n, str(n))} planos: {_join([p['nome'] for p in plans])}.",
                               frozenset(coverages))
        facts["necessidades"] = _necessidades_fact(plans)
        car = planos["regras"]["carencia"]
        car_cov = list(car["coberturas_com_carencia"])
        labels = _join([COVERAGE_LABEL.get(c, c) for c in car_cov])
        facts["carencia"] = Fact(
            "carencia", f"{labels[0].upper()}{labels[1:]} só passam a valer {car['dias']} dias depois do início da vigência (carência).",
            frozenset({"carencia"}) | frozenset(car_cov))
        if "entrada_meio_mes" in planos["regras"]:
            facts["pro_rata"] = Fact("pro_rata", "Quando a vigência começa no meio do mês, o primeiro pagamento é proporcional aos dias "
                                                 "restantes; os meses seguintes são integrais.", frozenset({"pro_rata"}))
        facts["franquia"] = Fact("franquia", "Cada plano tem uma franquia, a parte do prejuízo que fica com o segurado. "
                                             "O valor aparece na cotação.", frozenset({"franquia"}))
        return cls(facts, coverages, patterns)

    def ids(self) -> tuple[str, ...]:
        return tuple(self.facts)

    def render_for_prompt(self) -> str:
        return "\n".join(f"- [{f.id}] {f.text}" for f in self.facts.values())

    def find_terms(self, text: str) -> set[str]:
        """Termos que carregam afirmacao presentes em `text`."""
        plain = strip_accents(text).lower()
        found = {t for t, rx in _PLAIN.items() if rx.search(plain)}
        found |= {t for t, rx in self.plan_patterns.items() if rx.search(text)}
        return found
