"""Quem escreve o reply: o LLM na conversa NEUTRA, o TEMPLATE nas intencoes de RISCO.

Regex nao julga sentido. O smoke de 2026-10-20 mostrou dois replies de risco que o guardrail aprovou e que enganam a olho: "Sim, mas ha
carencia" a quem perguntou se roubo amanha esta coberto, e "a melhor opcao da AutoSeguro" numa objecao de preco. Caçar esses padroes
com mais regex e perder a corrida; entao, nas intencoes de risco, o texto que o lead le NAO vem do LLM:

  RISCO (template, montado dos fatos): duvida de carencia ou cobertura, objecao de preco, sinistro, pedido de humano.
  NEUTRA (LLM, com o guardrail R1-R7 estrito): saudacao, proxima pergunta, confirmacao.

Do LLM, nas turnos de risco, vale so a INTENCAO. Por isso reconhecer a intencao de risco passou a ser criterio do smoke (100%): se o
modelo classifica uma duvida de carencia como `provide_info`, o reply livre dele chega ao lead, ainda sob o guardrail.

Cada reply de risco tem um CORPO (so fatos e frases fixas, e passa no `check_reply` por construcao, testado) e, se houver, uma PERGUNTA do
produto (`questions.py`) para o orquestrador seguir a conversa. A objecao de preco segue o fluxo do PLAN: oferece UMA alternativa real;
se o lead hesita de novo, handoff PRICE_OBJECTION. Nunca promete desconto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .facts import COVERAGE_IDS, FactBase
from .handoff import HandoffReason
from .llm.guarded import GuardedResult

# `question_not_in_facts` entra porque e uma duvida de cobertura que os fatos nao respondem: a resposta honesta e fixa.
RISK_INTENTS = frozenset({"ask_coverage_question", "question_not_in_facts", "price_objection", "claim", "wants_human"})

NOT_IN_FACTS = "Não tenho essa informação por aqui, e prefiro não chutar."
NOT_UNDERSTOOD = "Não consegui entender direito. Pode escrever de outro jeito?"
PRICE_OFFER = "Entendo que o valor pesou. Posso te mostrar outro plano para você comparar?"
CLAIM = "Sinto muito pelo que aconteceu. Acionar o seguro (sinistro) não é comigo: eu só faço cotação."


def handoff_text(next_step: str = "") -> str:
    """O que o lead le quando a conversa passa a um humano (D2): honesto, sem prazo, canal nem desconto. `next_step` e configuracao de negocio."""
    base = "Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado."
    return f"{base} {next_step.strip()}" if next_step.strip() else base


@dataclass(frozen=True)
class Reply:
    text: str                                    # o que o lead le (corpo + pergunta)
    source: str                                  # "llm" | "template_risk" | "template_fallback"
    body: str = ""                               # so o corpo montado dos fatos / frases fixas (o que passa no guardrail por construcao)
    question: str | None = None                  # a pergunta do produto que segue o corpo
    facts_used: tuple[str, ...] = ()
    action: str | None = None                    # None | "offer_alternative" | "handoff"
    handoff_reason: HandoffReason | None = None
    violations: tuple[str, ...] = ()             # por que o reply do LLM foi trocado pelo template (so no fallback)


_PLAN_WORDS = re.compile(r"\bplanos?\b")


def facts_for_question(text: str, base: FactBase) -> tuple[str, ...]:
    """Os fatos que respondem a pergunta do lead, escolhidos pelo TEXTO DELE com o mesmo lexico do guardrail, nao pela citacao do modelo
    (que uma injecao poderia manipular). No maximo dois. Vazio = a base nao responde."""
    terms = base.find_terms(text)
    picked: list[str] = []

    def add(fid: str) -> None:
        if fid in base.facts and fid not in picked:
            picked.append(fid)

    if terms & {"carencia", "roubo", "furto"}:
        add("carencia")
    if "franquia" in terms:
        add("franquia")
    if "pro_rata" in terms:
        add("pro_rata")
    named = [t for t in terms if t.startswith("plan_")]
    for t in sorted(named):
        add("plano:" + t[len("plan_"):])
    wanted = (terms & COVERAGE_IDS) - {"roubo", "furto"}
    if wanted and not named:  # "cobre vidros?": os dois planos mais baratos que cobrem
        covering = sorted((t for t, cov in base.plan_coverages.items() if wanted <= cov), key=lambda t: len(base.plan_coverages[t]))
        for t in covering[:2]:
            add("plano:" + t[len("plan_"):])
    if not picked and _PLAN_WORDS.search(text.lower()):
        add("planos")
    return tuple(picked[:2])


def _coverage(lead_text: str, cited: tuple[str, ...], base: FactBase, question: str | None) -> Reply:
    ids = facts_for_question(lead_text, base) or tuple(f for f in cited if f in base.facts)[:2]  # sem match no texto, vale o que o modelo citou
    if not ids:
        return Reply(_join(NOT_IN_FACTS, question), "template_risk", NOT_IN_FACTS, question)
    body = " ".join(base.facts[f].text for f in ids)
    return Reply(_join(body, question), "template_risk", body, question, facts_used=ids)


def _join(body: str, question: str | None) -> str:
    return f"{body} {question}" if question else body


def select_reply(gres: GuardedResult, base: FactBase, *, lead_text: str, next_question: str | None = None, objection_count: int = 0,
                 has_alternative: bool = True, handoff_next_step: str = "") -> Reply:
    """O reply que vai ao lead. `next_question`: a pergunta do produto para o passo seguinte (o orquestrador a escolhe pelo estado).
    `objection_count`: quantas objecoes de preco ANTES desta. `has_alternative`: ha um plano mais barato para oferecer?"""
    fallback_q = next_question or NOT_UNDERSTOOD
    out = gres.output
    if out is None:  # falha do LLM, saida invalida, bloqueio do provedor: a conversa nao fica sem resposta
        return Reply(fallback_q, "template_fallback", fallback_q, violations=("sem_saida",))
    if out.intent in RISK_INTENTS:
        return _risk(out.intent, lead_text, out.facts_used, base, next_question, objection_count, has_alternative, handoff_next_step)
    if gres.reply_ok:
        return Reply(out.reply, "llm", out.reply, facts_used=out.facts_used)
    return Reply(fallback_q, "template_fallback", fallback_q, violations=tuple(sorted({v.rule for v in gres.violations})))


def _risk(intent: str, lead_text: str, cited: tuple[str, ...], base: FactBase, next_question: str | None, objection_count: int,
          has_alternative: bool, handoff_next_step: str) -> Reply:
    if intent == "ask_coverage_question":
        return _coverage(lead_text, cited, base, next_question)
    if intent == "question_not_in_facts":
        return Reply(_join(NOT_IN_FACTS, next_question), "template_risk", NOT_IN_FACTS, next_question)
    if intent == "price_objection":
        if objection_count == 0 and has_alternative:
            return Reply(PRICE_OFFER, "template_risk", PRICE_OFFER, action="offer_alternative")
        body = f"Entendo. {handoff_text(handoff_next_step)}"
        return Reply(body, "template_risk", body, action="handoff", handoff_reason=HandoffReason.PRICE_OBJECTION)
    if intent == "claim":
        body = f"{CLAIM} {handoff_text(handoff_next_step)}"
        return Reply(body, "template_risk", body, action="handoff", handoff_reason=HandoffReason.CLAIM_SINISTRO)
    body = f"Claro. {handoff_text(handoff_next_step)}"  # wants_human
    return Reply(body, "template_risk", body, action="handoff", handoff_reason=HandoffReason.HUMAN_REQUESTED)
