"""Guardrail do `reply` que o LLM redige. Funcao pura: `check_reply(...) -> violacoes`. Reprovou, o orquestrador usa o template do passo.

O que ele GARANTE (mecanicamente): o texto nao carrega dinheiro, prazo, promessa de desconto nem garantia de cobertura; todo numero esta
num fato citado ou foi escrito pelo lead; todo termo de cobertura/plano/carencia pertence a um fato que o LLM declarou usar; nenhuma
cobertura e atribuida ao plano errado; nenhuma negacao recai sobre um desses termos.
O que NAO garante: que uma frase montada so com termos autorizados seja verdadeira. Esse residuo fica com o prompt e com a leitura
humana do smoke-llm (ver docs/PLAN.md, secao 6). Na duvida, reprova: o custo de um falso positivo e cair num template.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from . import budgets
from .facts import COVERAGE_IDS, FactBase, strip_accents


@dataclass(frozen=True)
class Violation:
    rule: str
    detail: str  # nome do padrao/termo; nunca o trecho do texto


_R1_DINHEIRO = {"simbolo": r"r\$", "reais": r"\breais\b", "us": r"us\$", "mensalidade": r"\bmensalidade", "mensal": r"\bmensa(l|is)\b", "parcela": r"\bparcela",
                "premio": r"\bpremio\b", "valor_decimal": r"[0-9][0-9.]*,[0-9]{2}\b", "por_mes": r"\bpor mes\b"}
_R3_PRAZO = {"amanha": r"\bamanha\b", "em_breve": r"\bem breve\b", "em_instantes": r"\bem instantes?\b", "daqui_a_pouco": r"\bdaqui a pouco\b",
             "imediato": r"\bimediat", "em_ate": r"\bem ate [0-9]+", "dias_uteis": r"\bdias uteis\b", "horas": r"\bhoras?\b",
             "minutos": r"\bminutos?\b", "contato": r"\bentrar em contato\b", "ligar": r"\bliga(r|mos)\b|\bte ligo\b|\bligo para\b",
             "chamar": r"\bte chamar\b|\bchamo voce\b", "mesmo_chat": r"\bneste mesmo chat\b", "retorno": r"\bretorn",
             "ainda_hoje": r"\bainda hoje\b", "logo_mais": r"\blogo mais\b", "proximas": r"\bnas proximas\b"}
_R4_CONDICAO = {"desconto": r"\bdesconto", "promocao": r"\bpromoc", "abatimento": r"\babatimento", "preco_especial": r"preco especial",
                "condicao_especial": r"condicao especial", "melhor_preco": r"melhor preco", "igualamos": r"\bigualamos\b|\bcobrimos\b",
                "cortesia": r"\bcortesia\b", "gratis": r"\bgratis\b|\bgratuit", "sem_custo": r"sem custo", "isencao": r"\bisencao\b|\bisent[oa]\b"}
_R5_GARANTIA = {"cobre_tudo": r"cobre tudo", "sem_carencia": r"\bsem carencia\b", "garantia": r"\bgarant", "cem_por_cento": r"100 ?%",
                "qualquer": r"\bqualquer (dano|situacao|acidente|coisa)\b"}
_NEGACAO = re.compile(r"\b(nao|nunca|jamais|sem|nenhum|nenhuma|nem)\b")
_MARKUP = re.compile(r"[<>{}\[\]`]")
_SENTENCE_SPLIT = re.compile(r"[.!?;\n]+")


def _compile(d: dict[str, str]) -> dict[str, re.Pattern[str]]:
    return {k: re.compile(v) for k, v in d.items()}


_RULES = (("R1_dinheiro", _compile(_R1_DINHEIRO)), ("R3_prazo_ou_contato", _compile(_R3_PRAZO)),
          ("R4_desconto_ou_condicao", _compile(_R4_CONDICAO)), ("R5_garantia_de_cobertura", _compile(_R5_GARANTIA)))


def _digit_runs(text: str) -> set[str]:
    """Sequencias de digitos de `text` e as juncoes ("01310-100" -> 01310, 100 e 01310100)."""
    runs = set(re.findall(r"[0-9]+", text))
    for m in re.finditer(r"[0-9][0-9.\-/ ]*[0-9]", text):
        runs.add(re.sub(r"\D", "", m.group()))
    return runs


def check_reply(reply: str, *, facts_used: Sequence[str], base: FactBase, lead_texts: Sequence[str]) -> tuple[Violation, ...]:
    """`lead_texts`: o que o LEAD escreveu (mensagem atual e janela de historico). So numeros daqui, ou de fatos citados, podem ecoar."""
    v: list[Violation] = []
    plain = strip_accents(reply).lower()

    if not reply.strip():
        v.append(Violation("R6_forma", "vazio"))
    if len(reply.split()) > budgets.REPLY_HARD_MAX_WORDS:
        v.append(Violation("R6_forma", "palavras_demais"))
    if _MARKUP.search(reply):
        v.append(Violation("R6_forma", "marcacao"))

    for rule, patterns in _RULES:
        v.extend(Violation(rule, name) for name, rx in patterns.items() if rx.search(plain))

    unknown = [f for f in facts_used if f not in base.facts]
    v.extend(Violation("R7_fato_inexistente", "id") for _ in unknown)
    cited = [base.facts[f] for f in facts_used if f in base.facts]

    allowed_numbers = set().union(*(f.numbers for f in cited)) if cited else set()
    for t in lead_texts:
        allowed_numbers |= _digit_runs(t)
    v.extend(Violation("R2_numero_nao_permitido", "numero") for n in sorted(set(re.findall(r"[0-9]+", reply)) - allowed_numbers))

    allowed_terms = set().union(*(f.terms for f in cited)) if cited else set()
    v.extend(Violation("R7_termo_sem_fato", term) for term in sorted(base.find_terms(reply) - allowed_terms))

    for sentence in _SENTENCE_SPLIT.split(reply):
        terms = base.find_terms(sentence)
        if terms and _NEGACAO.search(strip_accents(sentence).lower()):
            v.append(Violation("R7_negacao_sobre_fato", "negacao"))
        coverages = terms & COVERAGE_IDS
        for plan in (t for t in terms if t in base.plan_coverages):
            v.extend(Violation("R7_cobertura_no_plano_errado", f"{plan}:{c}") for c in sorted(coverages - base.plan_coverages[plan]))
    return tuple(v)
