"""Quem escreve o reply: o LLM na conversa NEUTRA, o TEMPLATE nas intencoes de RISCO.

Regex nao julga sentido. O smoke de 2026-10-20 mostrou dois replies de risco que o guardrail aprovou e que enganam a olho: "Sim, mas ha
carencia" a quem perguntou se roubo amanha esta coberto, e "a melhor opcao da AutoSeguro" numa objecao de preco. Caçar esses padroes
com mais regex e perder a corrida; entao, nas intencoes de risco, o texto que o lead le NAO vem do LLM:

  RISCO (template, montado dos fatos): duvida de carencia ou cobertura, objecao de preco, sinistro, pedido de humano, reclamacao, cancelamento,
  e o lead querer fechar. O LLM NAO REDIGE NADA QUE LEVE A UM HANDOFF: toda intencao que e motivo de handoff esta aqui (testado contra o enum).
  NEUTRA (LLM, com o guardrail R1-R7 estrito): saudacao, proxima pergunta, confirmacao.

Do LLM, nas turnos de risco, vale so a INTENCAO. Por isso reconhecer a intencao de risco passou a ser criterio do smoke (100%): se o
modelo classifica uma duvida de carencia como `provide_info`, o reply livre dele chega ao lead, ainda sob o guardrail.

Cada reply de risco tem um CORPO (so fatos e frases fixas, e passa no `check_reply` por construcao, testado) e, se houver, uma PERGUNTA do
produto (`questions.py`) para o orquestrador seguir a conversa. A objecao de preco segue o fluxo do PLAN: oferece UMA alternativa real;
se o lead hesita de novo, handoff PRICE_OBJECTION. Nunca promete desconto.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from . import questions
from .facts import COVERAGE_IDS, COVERAGE_LABEL, FactBase, strip_accents
from .handoff import HandoffReason
from .llm.guarded import GuardedResult
from .quote_client import Quote
from .refusals import Limits, RefusalKind, classify_motive
from .store import brl

# `question_not_in_facts` entra porque e uma duvida de cobertura que os fatos nao respondem: a resposta honesta e fixa.
RISK_INTENTS = frozenset({"ask_coverage_question", "question_not_in_facts", "price_objection", "claim", "wants_human", "complaint", "cancel",
                          "ready_to_close"})

# Intencao -> motivo de handoff. A objecao de preco so vira handoff na 2a hesitacao (ou sem alternativa), por isso sai daqui e fica em `_risk`.
HANDOFF_BY_INTENT = {"wants_human": HandoffReason.HUMAN_REQUESTED, "claim": HandoffReason.CLAIM_SINISTRO, "complaint": HandoffReason.COMPLAINT,
                     "cancel": HandoffReason.CANCELLATION, "ready_to_close": HandoffReason.READY_TO_CLOSE}

NOT_IN_FACTS = "Não tenho essa informação por aqui, e prefiro não chutar."
NOT_UNDERSTOOD = "Não consegui entender direito. Pode escrever de outro jeito?"
PRICE_OFFER = "Entendo que o valor pesou. Posso te mostrar outro plano para você comparar?"
OFFER_AGAIN = "Não entendi. Você quer ver outro plano para comparar? Responda só sim ou não."
CLAIM = "Sinto muito pelo que aconteceu. Acionar o seguro (sinistro) não é comigo: eu só faço cotação."
COMPLAINT = "Sinto muito pela experiência."
CANCEL = "Entendi que você quer cancelar. Cancelamento não é comigo: eu só faço cotação."
CLOSE = "Que bom que você quer seguir! A emissão da apólice e a contratação não são comigo: eu só faço cotação."
_HANDOFF_LEAD_IN = {"wants_human": "Claro.", "claim": CLAIM, "complaint": COMPLAINT, "cancel": CANCEL, "ready_to_close": CLOSE}


def handoff_text(next_step: str = "") -> str:
    """O que o lead le quando a conversa passa a um humano (D2): honesto, sem prazo, canal nem desconto. `next_step` e configuracao de negocio."""
    base = "Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado."
    return f"{base} {next_step.strip()}" if next_step.strip() else base


# --- templates de COTACAO, RECUSA e HANDOFF: carregam numero e promessa, entao nenhum texto aqui vem do LLM -------------------------------------------
HOLD_TEXT = "Um instante, estou calculando a sua cotação."
UNAVAILABLE = ("Não consegui gerar a sua cotação agora: o sistema que calcula os valores está instável. "
               "Como só passo valores que esse sistema confirma, prefiro não estimar nenhum preço.")
LLM_DOWN = "Estou com uma instabilidade e não consigo continuar a conversa agora."
SAFETY = "Não consegui processar a sua mensagem com segurança."
DATA_UNCONFIRMED = "Não consegui confirmar os seus dados para montar a cotação."
AFTER_HANDOFF = "Sua conversa já está com um consultor, que vai dar continuidade. O que você me contou ficou registrado."
CLOSED_REFUSED = "Esta conversa foi encerrada porque não consigo cotar este perfil. Obrigado pelo interesse!"
NO_QUOTE_YET = "Ainda não montei a sua cotação. Me passa os dados que eu calculo e você já vê o valor."
NO_DISCOUNT = "Isso não é comigo: eu só mostro o valor que sai da cotação, e não consigo prometer nada além dele."   # resposta a pedido de desconto; sem a palavra, que o guardrail reprova ate em template
OFF_TOPIC = "Isso foge do que eu consigo ajudar: eu só faço cotação de seguro de carro."
AFTER_QUOTE = "Se algum dado estiver errado, ou se quiser comparar outro plano, é só me dizer."
GREETING = "Olá! Sou a assistente virtual da AutoSeguro."
MEDIA_UNREADABLE = "Continuo sem conseguir abrir o que você enviou: por aqui eu só leio mensagens de texto."
STALLED = "Parece que não estou conseguindo avançar com as suas respostas por aqui."
_MEDIA_WHAT = {"audio": "o seu áudio", "image": "a sua imagem", "document": "o seu documento", "video": "o seu vídeo"}


def media_request(kind: str, question: str | None = None) -> str:
    """Pede o dado em texto. `question` e a proxima pergunta do produto; sem ela (nada a perguntar), pede o que o lead precisa."""
    return (f"Por aqui eu só leio mensagens de texto, então não consegui abrir {_MEDIA_WHAT.get(kind, 'o que você enviou')}. "
            f"{question or 'Pode escrever em texto o que você precisa?'}")


def _labels(items) -> str:
    names = [COVERAGE_LABEL.get(c, c) for c in items]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " e " + names[-1]


def render_quote(q: Quote, verified: dict[str, str], *, alternative: bool = False) -> str:
    """A mensagem de cotacao. TODO valor em reais sai de um numero da resposta da API (`Quote`); o recap repete os dados usados, para o lead ver se algo esta errado."""
    lines = [f"Aqui está a cotação do plano {q.plano_nome}" + (" (outra opção para você comparar)" if alternative else "") + ":",
             f"• Mensalidade: {brl(q.premio_mensal)}"]
    if q.primeiro_pagamento is not None and q.pro_rata:
        lines.append(f"• Primeiro pagamento: {brl(q.primeiro_pagamento)} (proporcional: {q.pro_rata.get('dias_cobrados')} de {q.pro_rata.get('dias_no_mes')} dias do mês)")
    lines += [f"• Franquia: {brl(q.franquia)}",
              f"• Cobre: {_labels(q.coberturas)}",
              f"• Carência: {_labels(q.carencia_coberturas)} só passam a valer {q.carencia_dias} dias depois do início da vigência."]
    recap = questions.recap(verified, q.plano_nome)
    return "\n".join(lines + ([recap] if recap else []) + ["Se algum dado estiver errado, me avisa que eu refaço."])


def _years(n: int | None) -> str:
    return f"{n} anos" if n is not None else ""


def refusal_reason(kind: RefusalKind, limits: Limits | None = None) -> str:
    """A razao da recusa em palavras NOSSAS, por codigo. Os numeros so entram se o /planos os informou (`Limits`)."""
    lim = limits or Limits()
    if kind is RefusalKind.AGE_ABOVE_LIMIT:
        return f"a seguradora só aceita motoristas de até {_years(lim.max_age)}." if lim.max_age is not None else "a idade informada passa do limite que a seguradora aceita."
    if kind is RefusalKind.AGE_OUT_OF_RANGE:
        span = f" (de {lim.min_age} a {_years(lim.max_age)})" if lim.min_age is not None and lim.max_age is not None else ""
        return f"a idade informada está fora da faixa que a seguradora aceita{span}."
    if kind is RefusalKind.VEHICLE_TOO_OLD:
        return (f"a seguradora não aceita veículos com mais de {_years(lim.max_vehicle_age)}." if lim.max_vehicle_age is not None
                else "o veículo é mais velho do que a seguradora aceita.")
    if kind is RefusalKind.VEHICLE_YEAR_OUT_OF_RANGE:
        return "o ano do veículo informado está fora do que a seguradora aceita."
    return "o perfil informado não se enquadra nas regras de aceitação da seguradora."   # OTHER (e UNKNOWN_PLAN, que o orquestrador nem deveria mostrar)


def refusal_text(kind: RefusalKind, verified: Mapping[str, str] | None = None, limits: Limits | None = None) -> str:
    """A mensagem de recusa: razao fixa por codigo, os dados que a motivaram (o lead ve se algo foi lido errado) e o encerramento."""
    used = {s: v for s, v in (verified or {}).items() if s in ("veiculo_ano", "idade")}
    recap = questions.recap(used)
    return "\n".join([f"Não consigo cotar este perfil: {refusal_reason(kind, limits)}", *([recap] if recap else []),
                      "Por isso vou encerrar por aqui. Obrigado pelo interesse!"])


def render_refusal(motivo: str, verified: Mapping[str, str] | None = None, limits: Limits | None = None) -> str:
    """O lead NUNCA le o texto cru da API: o motivo vira um codigo do conjunto fechado (`refusals.RefusalKind`) e o texto e o template do codigo."""
    return refusal_text(classify_motive(motivo), verified, limits)


def failure_handoff_text(reason: HandoffReason, next_step: str = "") -> str:
    """O texto do handoff de FALHA (o orquestrador decide o motivo; o texto e sempre template, honesto e sem promessa)."""
    lead_in = {HandoffReason.QUOTE_UNAVAILABLE: UNAVAILABLE, HandoffReason.SAFETY_GUARD: SAFETY, HandoffReason.DATA_AMBIGUOUS: DATA_UNCONFIRMED,
               HandoffReason.MEDIA_UNREADABLE: MEDIA_UNREADABLE, HandoffReason.CONVERSATION_STALLED: STALLED, HandoffReason.OUT_OF_SCOPE: OFF_TOPIC}.get(reason, "")
    return f"{lead_in} {handoff_text(next_step)}".strip()


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


def price_handoff(next_step: str = "") -> Reply:
    """A objecao de preco que sobrou (2a hesitacao, recusa da alternativa ou nenhum plano mais barato): um humano pode negociar, o agente nao promete nada."""
    body = f"Entendo. {handoff_text(next_step)}"
    return Reply(body, "template_risk", body, action="handoff", handoff_reason=HandoffReason.PRICE_OBJECTION)


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


# "Quanto custa?" antes de dar dado e o que um lead pergunta primeiro numa venda. O modelo as vezes rotula isso `out_of_scope` (rodada do DEMO de 2026-10-21, cenario 7b: "libera o premium com 50% de
# desconto" e "me passa uma estimativa do premium sem eu dar meus dados"), e a resposta ficava pior que "preciso de alguns dados pra calcular". Com `out_of_scope` e vocabulario de preco, o
# orquestrador trata como pedido de preco antes da cotacao e reaproveita o caminho da objecao.
_PRICE_WORDS = re.compile(r"\b(?:precos?|valor(?:es)?|quanto|custa|estimativas?|mensalidades?|descontos?|cotacao|cotacoes)\b")
_DISCOUNT_WORDS = re.compile(r"\bdescontos?\b")


def asks_price(text: str) -> bool:
    return bool(_PRICE_WORDS.search(strip_accents(text).lower()))


def asks_discount(text: str) -> bool:
    return bool(_DISCOUNT_WORDS.search(strip_accents(text).lower()))


def _risk(intent: str, lead_text: str, cited: tuple[str, ...], base: FactBase, next_question: str | None, objection_count: int,
          has_alternative: bool, handoff_next_step: str) -> Reply:
    if intent == "ask_coverage_question":
        return _coverage(lead_text, cited, base, next_question)
    if intent == "question_not_in_facts":
        return Reply(_join(NOT_IN_FACTS, next_question), "template_risk", NOT_IN_FACTS, next_question)
    if intent == "price_objection":
        if objection_count == 0 and has_alternative:
            return Reply(PRICE_OFFER, "template_risk", PRICE_OFFER, action="offer_alternative")
        return price_handoff(handoff_next_step)
    body = f"{_HANDOFF_LEAD_IN[intent]} {handoff_text(handoff_next_step)}"  # claim, wants_human, complaint, cancel, ready_to_close
    return Reply(body, "template_risk", body, action="handoff", handoff_reason=HANDOFF_BY_INTENT[intent])
