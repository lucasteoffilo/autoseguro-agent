"""Orquestrador: a maquina de estados de uma conversa, uma mensagem por vez. Quem decide o proximo passo e o ESTADO, nao o LLM.

Ordem de um turno (o que sai da funcao `handle` e o que o lead le):

  1. dedupe pelo id da mensagem no canal (reentrega devolve as respostas ja enviadas e nao reprocessa nada);
  2. MASCARAR, antes de qualquer outra coisa. O texto cru nao sai de `handle`: nem o LLM, nem o banco, nem o log o veem. O que o mascarador
     deixar passar e conferido pelo detector de PII (`residual_pii`); se ainda achar algo, o turno termina em SAFETY_GUARD (componente masker);
  3. o LLM (`GuardedLLM`, o mesmo para o mock e para o modelo real) PROPOE slots e intencao; o `SlotLedger` decide o que vale (ancoragem, D5);
  4. a resposta: intencoes de RISCO e de handoff, cotacao, recusa e confirmacoes saem de TEMPLATE; o LLM so escreve a conversa neutra (D6);
  5. a cotacao so sai de `QuoteGate`, e todo "R$" da mensagem e conferido contra o numero que a API devolveu antes de enviar.

Garantias (cada uma tem teste): exatamente UMA mensagem terminal por turno; nenhuma excecao deixa o lead sem resposta (vira handoff
`SAFETY_GUARD` com componente `orchestrator`); o turno nao passa do teto de 20s (o LLM roda numa thread com prazo; a `/quote` recebe so o que sobrou);
o pacote de handoff e gravado no SQLite ANTES de a resposta ir ao lead, e a entrega a outros destinos vem depois.

LIMITE ASSUMIDO: o estado da conversa (livro-razao, pergunta pendente, cotacao exibida) vive na memoria do processo; o SQLite guarda o registro
(mensagens, cotacoes, tentativas, handoff, snapshot dos slots), nao o estado vivo. Reiniciar o processo encerra a conversa, nao a apaga.
"""
from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any

from . import budgets, questions, templates
from .anchoring import NotQuotable, QuoteGate, SlotLedger, implied_tier, is_affirmative, is_negative, plano_for, read_text
from .facts import FactBase, strip_accents
from .handoff import (MAX_RECENT_MESSAGES, FailedComponent, HandoffPackage, HandoffReason, HandoffSink, MaskedMessage, QuoteRef, SinkRejected,
                      SinkUnavailable)
from .llm.base import LLMResult, outcome_class
from .llm.guarded import GuardedLLM, GuardedResult, UnsafePayload
from .llm.prompt import build_user_message
from .llm.redact import DETAIL_LIMIT, redact
from .llm.throttle import ProtocolError, QuotaExhausted, ServiceUnstable, is_protocol_error
from .logexport import scan
from .masker import Masker, residual_pii
from .media import media_kind
from .precheck import Rules, precheck
from .quote_client import InvalidInput, Quote, QuoteClient, RealClock, Refused, Unavailable
from .refusals import Limits, RefusalKind, classify_motive
from .slots import QuoteRequest
from .store import RandomIds, SqliteSink, Store, brl, money_in, utc_now

ORDER = ("veiculo_ano", "idade", "cep", "necessidade", "data_inicio")   # a ordem em que o agente pergunta (PLAN, secao 8)
MAX_LEAD_CHARS = 2000
HISTORY_WINDOW = 6
HISTORY_KINDS = ("text", "question", "confirmation", "fallback")        # o que volta ao LLM como historico: nada de cotacao nem de handoff
RESERVE_S = 1.0                                                          # folga para o turno terminar com a mensagem terminal
COVERAGE_INTENTS = ("ask_coverage_question", "question_not_in_facts")    # respondidos por template; se a cotacao sai no mesmo turno, vao antes dela
DATA_ISSUE_REASON = HandoffReason.DATA_AMBIGUOUS
MEDIA_LIMIT = 2         # pedidos de texto seguidos, sem nenhum dado novo no meio: a 2a midia vai ao humano (MEDIA_UNREADABLE)
STALL_LIMIT = 3         # a mesma pergunta sem resposta util 3 vezes seguidas: CONVERSATION_STALLED
OFF_TOPIC_LIMIT = 2     # 2 mensagens fora de cotacao seguidas, sem dado novo: OUT_OF_SCOPE
# O que a pergunta do LLM precisa citar para valer como a pergunta que o ESTADO pede (quem decide o proximo passo e o orquestrador, nao o modelo).
_TOPIC = {"veiculo_ano": re.compile(r"\bano\b"), "idade": re.compile(r"\bidade\b|\banos\b"), "cep": re.compile(r"\bcep\b"),
          "data_inicio": re.compile(r"\b(dia|data|comec\w*|inicio|vigencia)\b")}


class PriceInvariantError(RuntimeError):
    """Uma mensagem trazia um valor em reais que a API nao devolveu. Nunca chega ao lead: o turno vira handoff."""


# --- resultado do turno -------------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Out:
    kind: str                # hold | question | confirmation | text | quote | refusal | handoff | fallback | closed
    text: str
    msg_id: str
    terminal: bool = True    # so o "um instante" (hold) nao e terminal


@dataclass(frozen=True)
class TurnResult:
    trace_id: str
    messages: tuple[Out, ...]
    status: str              # status da conversa depois do turno: open | quoted | refused | handoff
    elapsed_s: float
    duplicate: bool = False

    @property
    def terminal(self) -> tuple[Out, ...]:
        return tuple(m for m in self.messages if m.terminal)


@dataclass(frozen=True)
class _Next:
    slot: str
    kind: str                # "ask" | "confirm"
    text: str


@dataclass
class _Conv:
    trace_id: str
    ledger: SlotLedger = field(default_factory=SlotLedger)
    status: str = "open"
    asked: tuple[str, str] | None = None      # (slot, "ask" | "confirm"): o que a ultima mensagem do agente perguntou
    objections: int = 0
    pending_offer: str | None = None          # plano alternativo oferecido e ainda sem resposta
    last_quote: Quote | None = None
    last_ref: QuoteRef | None = None
    quoted_payload: dict[str, Any] | None = None   # a ultima cotacao PRINCIPAL exibida (para nao recotar sem mudanca)
    streak: int = 0                           # turnos seguidos sem saida utilizavel do LLM (filtro do provedor, saida invalida)
    probed: tuple[str, str] | None = None     # (idade, ano) para os quais a pre-checagem ja rodou: so roda de novo se o lead mudar um deles
    spoke: bool = False                       # o agente ja disse alguma coisa (a 1a mensagem leva a apresentacao)
    media_asks: int = 0                       # midias sem transcricao desde o ultimo dado novo
    offer_repeats: int = 0                    # vezes em que a resposta a oferta de plano alternativo nao foi nem sim nem nao
    stall: int = 0                            # turnos seguidos em que a mesma pergunta ficou sem resposta util
    off_topic: int = 0                        # mensagens fora de cotacao desde o ultimo dado novo
    undelivered: list[tuple[HandoffSink, HandoffPackage]] = field(default_factory=list)


@dataclass
class _Turn:
    conv: _Conv
    arrived: float
    send: Callable[[Out], None] | None
    out: list[Out] = field(default_factory=list)
    llm: dict[str, Any] = field(default_factory=dict)    # meta do LLM neste turno, vai na mensagem terminal
    extra: dict[str, Any] = field(default_factory=dict)  # o que o turno decidiu e vale em TODAS as mensagens dele (ex.: o veredito da pre-checagem)

    @property
    def trace(self) -> str:
        return self.conv.trace_id

    @property
    def has_terminal(self) -> bool:
        return any(o.terminal for o in self.out)


@dataclass(frozen=True)
class _LLMOutcome:
    kind: str                # ok | blocked | unusable | service
    gres: GuardedResult | None
    error: str | None
    attempt: int


class Orchestrator:
    def __init__(self, *, llm: GuardedLLM, store: Store, quote_client: QuoteClient, planos: Mapping[str, Any], fact_base: FactBase | None = None,
                 masker: Masker | None = None, sinks: Sequence[HandoffSink] = (), ids: Any = None, clock: Any = None,
                 today: Callable[[], date] = date.today, handoff_next_step: str = "", mode: str = "mock",
                 turn_ceiling_s: float = budgets.TURN_CEILING_S, hold_after_s: float = budgets.HOLD_AFTER_S) -> None:
        self._llm, self._store, self._planos = llm, store, planos
        self._facts = fact_base or FactBase.from_planos(planos)
        self._masker = masker or Masker()
        self._gate = QuoteGate(quote_client, planos)
        self._rules = Rules.from_planos(planos)           # as faixas da pre-checagem tambem saem do /planos
        self._limits = Limits.from_planos(planos)       # os numeros que o texto de recusa cita saem do /planos, nao do codigo
        self._record_sink = SqliteSink(store)           # o registro de rastreabilidade: sempre existe, e e o primeiro a receber o pacote
        self._sinks = tuple(sinks)                      # CRM, fila... ALEM do SQLite, nunca no lugar
        self._ids = ids or RandomIds()
        self._clock = clock or RealClock()
        self._today, self._next_step, self._mode = today, handoff_next_step, mode
        self._ceiling, self._hold_after = turn_ceiling_s, hold_after_s
        self._llm_answered = 0                          # chamadas ao LLM que o provedor respondeu (2xx): um 400 so e "do conteudo" depois de o MESMO formato ter dado certo
        self._convs: dict[str, _Conv] = {}

    # --- API ------------------------------------------------------------------------------------------------------------------------------------
    def start(self) -> str:
        trace = self._ids.new("trc")
        self._store.open_conversation(trace, mode=self._mode, provider=self._llm.provider, model=self._llm.model, now=utc_now())
        self._convs[trace] = _Conv(trace)
        return trace

    def handle(self, trace_id: str, text: str, *, external_id: str | None = None, send: Callable[[Out], None] | None = None) -> TurnResult:
        """Processa UMA mensagem do lead. `send` recebe cada mensagem do agente assim que existe (o "um instante" sai no meio do turno)."""
        arrived = self._clock.now()
        conv = self._convs[trace_id]
        if external_id and (prev := self._store.message_by_external(trace_id, external_id)):
            return TurnResult(trace_id, self._replay(trace_id, prev["seq"]), conv.status, 0.0, duplicate=True)

        masked = self._masker.mask(text[:MAX_LEAD_CHARS])
        truncated = len(text) > MAX_LEAD_CHARS
        text = ""                                       # daqui para a frente so existe a versao mascarada
        leftover = residual_pii(masked.text)            # o gate de envio conferindo o mascarador
        shown = masked.text if not leftover else "[mensagem não registrada: dado sensível não mascarado]"
        meta = {"mask_kinds": list(masked.kinds), **({"truncated": True} if truncated else {}), **({"residual_pii": leftover} if leftover else {}),
                **({"media": mk} if (mk := media_kind(masked.text)) else {})}
        self._store.add_message(trace_id, self._ids.new("msg"), role="lead", kind="text", text=shown, ts=utc_now(), status="processed",
                                external_id=external_id, meta=meta)

        t = _Turn(conv, arrived, send)
        try:
            if leftover:
                self._fail(t, HandoffReason.SAFETY_GUARD, FailedComponent.MASKER, detail="pii_residual:" + ",".join(leftover))
            elif not masked.text.strip():
                self._say(t, "fallback", templates.NOT_UNDERSTOOD, meta={"reply_source": "template_fallback"})
            else:
                self._run(t, masked.text)
        except Exception as exc:  # noqa: BLE001 - nenhuma excecao deixa o lead sem resposta
            self._last_resort(t, exc)
        if not t.has_terminal:
            self._last_resort(t, RuntimeError("turno sem mensagem terminal"))
        self._persist_state(conv)
        return TurnResult(trace_id, tuple(t.out), conv.status, self._clock.now() - arrived)

    def redeliver(self, trace_id: str | None = None) -> int:
        """Tenta de novo as entregas de handoff que falharam (`SinkUnavailable`). Devolve quantas foram entregues agora."""
        done = 0
        for conv in ([self._convs[trace_id]] if trace_id else list(self._convs.values())):
            still = []
            for sink, pkg in conv.undelivered:
                try:
                    sink.deliver(pkg)
                    done += 1
                except (SinkUnavailable, SinkRejected):
                    still.append((sink, pkg))
            conv.undelivered = still
        return done

    def reconstruct(self, trace_id: str) -> dict[str, Any]:
        return self._store.reconstruct(trace_id)

    # --- o turno --------------------------------------------------------------------------------------------------------------------------------
    def _run(self, t: _Turn, text: str) -> None:
        conv = t.conv
        if conv.status == "handoff":
            self._say(t, "closed", templates.AFTER_HANDOFF, meta={"reply_source": "template_state"})
            return
        if conv.status == "refused":
            self._say(t, "closed", templates.CLOSED_REFUSED, meta={"reply_source": "template_state"})
            return

        if (media := media_kind(text)) is not None:      # midia sem transcricao: nao e lida, o LLM nao e chamado
            self._media(t, media)
            return

        gres = self._ask_llm(t, text)
        if gres is None:                                 # o turno ja terminou (resposta por template ou handoff)
            return
        out = gres.output
        assert out is not None
        ledger = conv.ledger
        asked_slot, asked_kind = conv.asked or (None, None)
        offer, conv.pending_offer = conv.pending_offer, None
        before = ledger.snapshot()

        # a resposta a uma confirmacao e resolvida SEM o modelo; ele so continua dono da intencao e dos outros slots
        skip: set[str] = set()
        if asked_kind == "confirm" and asked_slot and (st := ledger.state(asked_slot)) is not None and not st.quotable:
            ledger.answer(asked_slot, text)
            skip.add(asked_slot)
            if ledger.attempts(asked_slot) >= 2:         # duas confirmacoes sem resposta util: um humano resolve
                self._fail(t, DATA_ISSUE_REASON, None, detail=f"confirmacao_sem_resposta:{asked_slot}")
                return
        reading = read_text(text, asked_slot)
        # o modelo repetir um dado que o lead nao falou agora nao pode REBAIXAR um slot ja verificado; so uma correcao escrita pelo lead substitui
        kept = tuple(s for s in out.slots if s.slot not in skip and not (ledger.state(s.slot) is not None and ledger.state(s.slot).quotable
                                                                         and not _mentions(reading, s.slot)))
        ledger.ingest(replace(out, slots=kept), text, asked_slot=asked_slot if asked_kind == "ask" else None)

        progress = ledger.snapshot() != before            # algum dado novo ou corrigido neste turno
        if progress:
            conv.stall = conv.media_asks = conv.off_topic = 0
        nq = self._next(conv)
        intent = out.intent
        if offer and nq is None and not progress and intent not in templates.HANDOFF_BY_INTENT:   # resposta a oferta: o LEXICO decide, nao o rotulo do modelo
            self._answer_offer(t, offer, text, gres)
            return

        if intent == "out_of_scope":
            conv.off_topic += 1
            if conv.off_topic >= OFF_TOPIC_LIMIT:        # a 1a vez redireciona; insistir em assunto que nao e cotacao e com um humano
                self._handoff(t, HandoffReason.OUT_OF_SCOPE, templates.failure_handoff_text(HandoffReason.OUT_OF_SCOPE, self._next_step),
                              meta={**t.llm, "reply_source": "template_state", "intent": intent})
                return
            body = templates.OFF_TOPIC
            reply = templates.Reply(f"{body} {nq.text}" if nq else body, "template_risk", body, nq.text if nq else None)
        elif intent == "price_objection" and conv.last_quote is None:
            body = templates.NO_QUOTE_YET
            reply = templates.Reply(f"{body} {nq.text}" if nq else body, "template_risk", body, nq.text if nq else None)
        else:
            reply = templates.select_reply(gres, self._facts, lead_text=text, next_question=nq.text if nq else None, objection_count=conv.objections,
                                           has_alternative=self._alternative(conv) is not None, handoff_next_step=self._next_step)
        if reply.action == "handoff":
            self._reply_action(t, reply, gres)
            return
        if reply.action == "offer_alternative":
            conv.objections += 1
            conv.pending_offer, conv.offer_repeats = self._alternative(conv), 0
            self._say(t, "text", reply.text, meta=self._meta(t, reply, gres, nq))
            conv.asked = ("oferta", "offer")
            return

        if self._eligibility(t, intent, reply):          # idade e ano verificados: a recusa prevista e confirmada pela API antes de ser dita
            return
        if (nq is not None and not progress and intent not in templates.RISK_INTENTS and intent != "out_of_scope"
                and (nq.slot, nq.kind) == (asked_slot, asked_kind)):
            conv.stall += 1                              # a mesma pergunta voltou a ficar sem resposta util
            if conv.stall >= STALL_LIMIT:
                self._handoff(t, HandoffReason.CONVERSATION_STALLED, templates.failure_handoff_text(HandoffReason.CONVERSATION_STALLED, self._next_step),
                              meta={**t.llm, "reply_source": "template_state", "intent": intent}, detail=f"pergunta_repetida:{nq.slot}")
                return

        if nq is None:                                   # tudo verificado: cotar, se ainda nao ha cotacao dos mesmos dados
            built = ledger.quote_request(self._planos, today=self._today())
            if isinstance(built, NotQuotable):
                self._fail(t, DATA_ISSUE_REASON, None, detail="entrada_invalida:" + ",".join(f"{i.slot}:{i.code}" for i in built.issues))
                return
            if built.to_payload() != conv.quoted_payload:
                lead_in = reply.body + "\n\n" if intent in COVERAGE_INTENTS and reply.source == "template_risk" and reply.body else ""
                self._quote(t, request=built, lead_in=lead_in)
                return
        self._converse(t, reply, nq, gres)

    # --- midia ----------------------------------------------------------------------------------------------------------------------------------
    def _media(self, t: _Turn, kind: str) -> None:
        """Midia sem transcricao: pede o dado em texto; a segunda seguida, sem dado novo no meio, vai a um humano. Nao chama o LLM nem le a descricao."""
        conv = t.conv
        conv.media_asks += 1
        if conv.media_asks >= MEDIA_LIMIT:
            self._handoff(t, HandoffReason.MEDIA_UNREADABLE, templates.failure_handoff_text(HandoffReason.MEDIA_UNREADABLE, self._next_step),
                          detail=f"midia_repetida:{kind}", meta={"reply_source": "template_state", "media": kind})
            return
        nq = self._next(conv)
        text = templates.media_request(kind, nq.text if nq else None)
        if not conv.spoke:
            text = f"{templates.GREETING} {text}"
        conv.asked = (nq.slot, nq.kind) if nq else None
        self._say(t, "question" if nq else "text", text, meta={"reply_source": "template_media", "media": kind, **({"asked": [nq.slot, nq.kind]} if nq else {})})

    # --- pre-checagem ---------------------------------------------------------------------------------------------------------------------------
    def _eligibility(self, t: _Turn, intent: str, reply: templates.Reply) -> bool:
        """Idade e ano verificados: a pre-checagem le as faixas do /planos. Se PREVE recusa, a API confirma (so idade e ano, plano mais barato) antes de o lead ouvir
        'recusado'. A API aceitou: a divergencia e registrada, o preco parcial nunca e exibido e a conversa segue. A API fora: humano, com o veredito no pacote.
        True = o turno terminou."""
        conv = t.conv
        v = conv.ledger.verified()
        if "idade" not in v or "veiculo_ano" not in v or conv.probed == (v["idade"], v["veiculo_ano"]):
            return False
        conv.probed = (v["idade"], v["veiculo_ano"])
        built = self._gate.eligibility_request(conv.ledger, today=self._today())
        if isinstance(built, NotQuotable):               # ano-modelo futuro, idade impossivel: um humano decide, sem perguntar CEP, cobertura e data antes
            self._fail(t, DATA_ISSUE_REASON, None, detail="entrada_invalida:" + ",".join(f"{i.slot}:{i.code}" for i in built.issues))
            return True
        verdict = precheck(self._rules, idade=built.idade, veiculo_ano=built.veiculo_ano, today=self._today())
        t.extra["precheck"] = verdict.label
        if verdict.accepts:
            return False
        done = self._call_api(t, built, "precheck", lambda **kw: self._gate.probe(conv.ledger, today=self._today(), **kw))
        if done is None:
            return True
        outcome, qid = done
        meta = {**t.llm, "reply_source": "template_refusal", "quote_id": qid, "precheck_kind": verdict.kind.value if verdict.kind else None}
        if isinstance(outcome, Refused):
            lead_in = reply.body + "\n\n" if intent in COVERAGE_INTENTS and reply.source == "template_risk" and reply.body else ""
            self._refuse(t, outcome, qid, meta, lead_in)
        elif isinstance(outcome, Quote):                 # a pre-checagem previu recusa e a API aceitou: divergencia registrada, nada do preco parcial vai ao lead
            t.extra["precheck_divergence"] = True
            return False
        elif isinstance(outcome, InvalidInput):
            self._fail(t, DATA_ISSUE_REASON, FailedComponent.QUOTE_CLIENT, detail=f"entrada_recusada:{outcome.kind}")
        else:
            self._fail(t, HandoffReason.QUOTE_UNAVAILABLE, FailedComponent.QUOTE_API, detail=f"precheck:{outcome.reason}:{outcome.last_error}")
        return True

    # --- oferta de plano alternativo -------------------------------------------------------------------------------------------------------------
    def _answer_offer(self, t: _Turn, offer: str, text: str, gres: GuardedResult) -> None:
        """A resposta a "Posso te mostrar outro plano?" e decidida pelo LEXICO (`anchoring.is_affirmative` e `is_negative`), nunca pelo rotulo do modelo: com o modelo real, "sim, pode
        mostrar" veio rotulado `price_objection` (rodada de 2026-10-21) e a oferta virava handoff. Sim cota o alternativo; nao e PRICE_OBJECTION; nem um nem outro repete a pergunta UMA vez,
        por template, e a segunda ambiguidade vai a um humano. (As intencoes que ja sao handoff por si, como pedir uma pessoa, nem chegam aqui.)"""
        conv = t.conv
        if is_affirmative(text):
            conv.offer_repeats = 0
            self._quote(t, plano_id=offer, alternative=True)
        elif is_negative(text):
            conv.offer_repeats = 0
            self._reply_action(t, templates.price_handoff(self._next_step), gres)
        else:
            conv.offer_repeats += 1
            if conv.offer_repeats >= 2:
                self._handoff(t, HandoffReason.PRICE_OBJECTION, templates.price_handoff(self._next_step).text, detail="oferta_sem_resposta",
                              meta={**t.llm, "reply_source": "template_risk", "intent": gres.output.intent if gres.output else None})
                return
            conv.pending_offer, conv.asked = offer, ("oferta", "offer")
            self._say(t, "question", templates.OFFER_AGAIN, meta={**t.llm, "reply_source": "template_risk", "intent": gres.output.intent if gres.output else None, "asked": ["oferta", "offer"]})

    # --- LLM ------------------------------------------------------------------------------------------------------------------------------------
    def _ask_llm(self, t: _Turn, text: str) -> GuardedResult | None:
        """Chama o LLM com prazo. Devolve a resposta utilizavel, ou None depois de ja ter encerrado o turno (template ou handoff)."""
        conv = t.conv
        history, lead_texts = self._history(t.trace)
        verified = dict(conv.ledger.verified())
        message = build_user_message(today=self._today(), known_slots=verified, asked_slot=conv.asked[0] if conv.asked and conv.asked[1] != "offer" else None,
                                     history=history, message=text)
        outcome = self._call_with_retry(t, message, [*lead_texts, text])
        if isinstance(outcome, tuple):                   # falha dura: (componente, codigo, resultado do provedor, se houve)
            component, code, res = outcome
            t.llm = self._result_meta(res)
            self._fail(t, HandoffReason.SAFETY_GUARD, component, detail=self._detail_text(code, res),
                       lead_in=templates.SAFETY if component is FailedComponent.MASKER else templates.LLM_DOWN)
            return None
        t.llm = self._llm_meta(outcome)
        if outcome.kind == "ok":
            conv.streak = 0
            return outcome.gres
        conv.streak += 1                                 # filtrado pelo provedor ou saida inutil: nao extrai nada, o ledger nao e tocado
        if conv.streak >= 2:
            self._fail(t, HandoffReason.SAFETY_GUARD, FailedComponent.LLM, detail=self._detail_text(outcome.error or "sem_saida", outcome.gres.result if outcome.gres else None))
            return None
        nq = self._next(conv)
        conv.asked = (nq.slot, nq.kind) if nq else None
        self._say(t, "fallback", nq.text if nq else (templates.AFTER_QUOTE if conv.last_quote else templates.NOT_UNDERSTOOD),
                  meta={**t.llm, "reply_source": "template_fallback", "violations": ["sem_saida"], "llm_error": outcome.error})
        return None

    def _call_with_retry(self, t: _Turn, message: str, lead_texts: list[str]) -> _LLMOutcome | tuple[FailedComponent, str, LLMResult | None]:
        error: str | None = None
        gres: GuardedResult | None = None
        for attempt in (1, 2):
            remaining = self._ceiling - (self._clock.now() - t.arrived) - RESERVE_S
            if attempt == 2 and remaining < budgets.LLM_CALL_TIMEOUT_S:
                break                                    # sem prazo para uma segunda tentativa
            try:
                gres = self._call_llm(message, lead_texts, max(0.0, remaining))
            except UnsafePayload:
                return FailedComponent.MASKER, "gate_de_pii", None
            except QuotaExhausted:
                return FailedComponent.LLM, "cota_diaria", None
            except ProtocolError as exc:
                return self._protocol_failure(exc.result, attempt)
            except ServiceUnstable as exc:
                return FailedComponent.LLM, "servico_instavel", exc.result
            error = gres.result.error
            klass = outcome_class(error)
            if is_protocol_error(gres.result):           # um LLM sem o limitador devolve o 4xx como resultado; a regra e a mesma
                return self._protocol_failure(gres.result, attempt)
            if klass == "answered":
                self._llm_answered += 1
            if error is None and gres.output is not None:
                return _LLMOutcome("ok", gres, None, attempt)
            if klass == "answered":                      # o provedor respondeu mal (saida fora do schema, truncada): repetir nao melhora
                return _LLMOutcome("unusable", gres, error, attempt)
            # "blocked" (filtro do provedor) e "service" (timeout, 5xx...): uma nova tentativa
        kind = "blocked" if outcome_class(error) == "blocked" else "service"
        if kind == "service":
            return FailedComponent.LLM, error or "servico", gres.result if gres else None
        return _LLMOutcome(kind, gres, error, attempt)

    def _protocol_failure(self, res: LLMResult, attempt: int) -> _LLMOutcome | tuple[FailedComponent, str, LLMResult | None]:
        """Um 4xx do provedor. 400 e 422 ISOLADOS, depois de chamadas que o provedor respondeu com o mesmo formato, sao do CONTEUDO daquela mensagem (rodada de 2026-10-21: o mesmo corpo,
        reenviado, deu o mesmo 400 do provedor de origem, "bad request"): entram na regra do `content_filter` (a pergunta pendente por template, sem extrair, e dois turnos seguidos viram
        SAFETY_GUARD/llm), SEM repetir o pedido, que e deterministico. 401, 402, 403, 404 e o resto (e um 400 antes de qualquer sucesso) sao problema do PEDIDO ou da conta: direto a SAFETY_GUARD."""
        if res.http_status in (400, 422) and self._llm_answered > 0:
            return _LLMOutcome("blocked", GuardedResult(res, ()), res.error, attempt)
        return FailedComponent.LLM, f"protocolo:{res.http_status}", res

    def _call_llm(self, message: str, lead_texts: list[str], timeout_s: float) -> GuardedResult:
        """O LLM numa thread com prazo: o teto do turno vale mesmo que o provedor demore ou o limitador de taxa durma."""
        box: dict[str, Any] = {}
        done = threading.Event()

        def run() -> None:
            try:
                box["r"] = self._llm.turn(message, lead_texts=lead_texts)
            except BaseException as exc:  # noqa: BLE001 - repassada a quem chamou
                box["e"] = exc
            finally:
                done.set()

        threading.Thread(target=run, daemon=True).start()
        if not done.wait(timeout_s):
            return GuardedResult(LLMResult(None, "timeout", timeout_s, None, None), ())
        if "e" in box:
            raise box["e"]
        return box["r"]

    def _llm_meta(self, o: _LLMOutcome) -> dict[str, Any]:
        return {"attempt": o.attempt, **self._result_meta(o.gres.result if o.gres else None)}

    def _result_meta(self, res: LLMResult | None) -> dict[str, Any]:
        """O que o provedor respondeu, para o meta: latencia, tokens, o codigo do erro e, se houver, o DETALHE do erro (mascarado e truncado, ver `_excerpt`)."""
        meta: dict[str, Any] = {}
        if res is not None:
            meta["llm_latency_s"] = round(res.latency_s, 3)
            if res.usage:
                meta["usage"] = {"input_tokens": res.usage.input_tokens, "output_tokens": res.usage.output_tokens}
            if res.error:
                meta["llm_error"] = res.error
                if res.detail:
                    shown = self._excerpt(res.detail)
                    meta.update({"llm_error_detail": shown} if shown is not None else {"llm_error_detail_omitted": "pii"})
        return meta

    def _detail_text(self, code: str, res: LLMResult | None) -> str:
        """O `handoff_detail` de uma falha do LLM: o codigo e, se o provedor deu um detalhe, ele (redigido, truncado, sem PII)."""
        if res is None or not res.detail:
            return code
        shown = self._excerpt(res.detail)
        return f"{code} | {shown if shown is not None else 'detalhe omitido: pii'}"

    def _excerpt(self, text: str) -> str | None:
        """Um trecho que pode ir para o banco e para o export: passa pelo mascarador, depois por `redact` (chaves) e e truncado em `DETAIL_LIMIT`, mascarando ANTES de truncar. Se a varredura
        que o export usa ainda achar PII ou segredo, devolve None: quem chama grava so a marca, e o export nunca recusa a conversa por causa disto."""
        masked = self._masker.mask(text).text
        shown = redact(masked, limit=DETAIL_LIMIT)
        return None if (scan(shown) or scan(masked)) else shown

    # --- cotacao --------------------------------------------------------------------------------------------------------------------------------
    def _call_api(self, t: _Turn, request: QuoteRequest, kind: str, call: Callable[..., Any]) -> tuple[Any, str] | None:
        """UMA chamada a /quote (cotacao, alternativa ou confirmacao da pre-checagem), com o orcamento do que sobrou do turno, e o registro de tudo no banco.
        Devolve (resultado, id da cotacao), ou None se o gate recusou chamar (e o turno ja terminou em handoff)."""
        conv = t.conv
        elapsed = self._clock.now() - t.arrived
        budget = max(0.0, min(budgets.QUOTE_BUDGET_S, self._ceiling - elapsed - budgets.OVERHEAD_S))
        qid = self._ids.new("qte")

        def on_hold() -> None:                           # best-effort: se falhar, o cliente registra e a chamada segue
            self._say(t, "hold", templates.HOLD_TEXT, terminal=False, meta={"quote_phase": True})

        outcome = call(budget_s=budget, hold_after_s=max(0.0, self._hold_after - elapsed), on_hold=on_hold)
        if isinstance(outcome, NotQuotable):
            self._fail(t, DATA_ISSUE_REASON, None, detail="entrada_invalida")
            return None
        status = {Quote: "ok", Refused: "refused", InvalidInput: "invalid", Unavailable: "unavailable"}[type(outcome)]
        response: Any = (outcome.raw if isinstance(outcome, Quote) else {"motivo": outcome.motivo} if isinstance(outcome, Refused)
                         else {"kind": outcome.kind, "detail": outcome.detail} if isinstance(outcome, InvalidInput)
                         else {"reason": outcome.reason, "last_error": outcome.last_error})
        self._store.add_quote(t.trace, qid, kind=kind, status=status, request=request.to_payload(), response=response,
                              plano_id=request.plano_id, premio_mensal=outcome.premio_mensal if isinstance(outcome, Quote) else None,
                              elapsed_s=round(outcome.elapsed_s, 3), now=utc_now())
        for a in outcome.attempts:
            self._store.add_attempt(t.trace, qid, self._ids.new("att"), n=a.n, started_s=round(a.started_s, 3), latency_s=round(a.latency_s, 3),
                                    http_status=a.http_status, error_kind=a.error_kind, decision=a.decision)
        if kind != "precheck" or not isinstance(outcome, Quote):   # o preco parcial da confirmacao nao entra nem na referencia que o humano recebe
            conv.last_ref = QuoteRef(qid, request.plano_id, status, outcome.premio_mensal if isinstance(outcome, Quote) else None)  # type: ignore[arg-type]
        return outcome, qid

    def _quote(self, t: _Turn, *, request: QuoteRequest | None = None, plano_id: str | None = None, alternative: bool = False, lead_in: str = "") -> None:
        conv = t.conv
        if request is None:
            built = conv.ledger.quote_request(self._planos, today=self._today(), plano_id=plano_id)
            if isinstance(built, NotQuotable):
                self._fail(t, DATA_ISSUE_REASON, None, detail="entrada_invalida")
                return
            request = built
        done = self._call_api(t, request, "alternative" if alternative else "quote",
                              lambda **kw: self._gate.quote(conv.ledger, today=self._today(), plano_id=plano_id, **kw))
        if done is None:
            return
        outcome, qid = done
        meta = {**t.llm, "reply_source": "template_quote", "quote_id": qid, "hold_fired": outcome.hold_fired, "quote_elapsed_s": round(outcome.elapsed_s, 3)}

        if isinstance(outcome, Quote):
            text = lead_in + templates.render_quote(outcome, dict(conv.ledger.verified()), alternative=alternative)
            self._assert_prices(text, outcome)
            conv.last_quote, conv.status = outcome, "quoted"
            if not alternative:
                conv.quoted_payload, conv.objections = request.to_payload(), 0
            conv.asked = None
            self._say(t, "quote", text, quote_id=qid, meta=meta)
        elif isinstance(outcome, Refused):
            if alternative:                              # o plano mais barato foi recusado para o mesmo perfil: quem resolve e um humano
                self._reply_action(t, templates.price_handoff(self._next_step), None)
                return
            self._refuse(t, outcome, qid, meta)
        elif isinstance(outcome, InvalidInput):          # o servico recusou a entrada que o agente montou: erro nosso, nunca do lead
            self._fail(t, DATA_ISSUE_REASON, FailedComponent.QUOTE_CLIENT, detail=f"entrada_recusada:{outcome.kind}")
        else:
            self._fail(t, HandoffReason.QUOTE_UNAVAILABLE, FailedComponent.QUOTE_API, detail=f"{outcome.reason}:{outcome.last_error}")

    def _refuse(self, t: _Turn, outcome: Refused, qid: str, meta: Mapping[str, Any], lead_in: str = "") -> None:
        """A API recusou (a palavra final). O lead le o template do CODIGO do motivo, nunca o texto cru dela."""
        conv = t.conv
        kind = classify_motive(outcome.motivo)
        if kind is RefusalKind.UNKNOWN_PLAN:             # o plano que NOS pedimos nao existe: erro do agente, nunca "perfil recusado"
            self._fail(t, DATA_ISSUE_REASON, FailedComponent.QUOTE_CLIENT, detail="plano_recusado_pela_api")
            return
        conv.status, conv.asked = "refused", None
        self._store.update_conversation(t.trace, utc_now(), status="refused")
        self._say(t, "refusal", lead_in + templates.refusal_text(kind, dict(conv.ledger.verified()), self._limits), quote_id=qid,
                  meta={**meta, "reply_source": "template_refusal", "refusal_kind": kind.value})

    @staticmethod
    def _assert_prices(text: str, q: Quote) -> None:
        allowed = {brl(q.premio_mensal), brl(q.franquia)} | ({brl(q.primeiro_pagamento)} if q.primeiro_pagamento is not None else set())
        stray = [m for m in money_in(text) if m not in allowed]
        if stray:
            raise PriceInvariantError(f"{len(stray)} valor(es) em reais que a API nao devolveu")

    def _alternative(self, conv: _Conv) -> str | None:
        """O plano logo abaixo do cotado (um plano REAL, cotado de novo na API). None se o cotado ja e o mais barato ou nao ha cotacao."""
        if conv.last_quote is None:
            return None
        tiers = [p["id"] for p in sorted(self._planos["planos"], key=lambda p: len(p["coberturas"]))]
        i = tiers.index(conv.last_quote.plano_id) if conv.last_quote.plano_id in tiers else 0
        return tiers[i - 1] if i > 0 else None

    # --- conversa e handoff ---------------------------------------------------------------------------------------------------------------------
    def _next(self, conv: _Conv) -> _Next | None:
        for slot in ORDER:
            st = conv.ledger.state(slot)
            if st is not None and st.quotable:
                continue
            if st is not None and st.needs_confirmation:
                return _Next(slot, "confirm", conv.ledger.question(slot, self._facts))
            return _Next(slot, "ask", questions.ask(slot, self._facts))
        return None

    def _converse(self, t: _Turn, reply: templates.Reply, nq: _Next | None, gres: GuardedResult) -> None:
        conv = t.conv
        source, kind, text = reply.source, "text", reply.text
        if source == "llm":
            asked_ok = nq is not None and nq.kind == "ask" and nq.slot != "necessidade" and _asks(nq.slot, text)
            clean = not self._masker.mask(text).kinds and not residual_pii(text)       # o que o modelo escreve tambem passa pelo mascarador
            if nq is None:
                text, source = templates.AFTER_QUOTE, "template_state"
            elif not (asked_ok and clean):               # confirmacao e pergunta de necessidade sao do produto, nao do modelo (D6)
                text, source = nq.text, "template_question"
                kind = "confirmation" if nq.kind == "confirm" else "question"
        elif source == "template_fallback":
            if nq is None:
                text = templates.AFTER_QUOTE
            kind = "fallback" if nq is None else ("confirmation" if nq.kind == "confirm" else "question")
        conv.asked = (nq.slot, nq.kind) if nq else None
        meta = self._meta(t, reply, gres, nq, source=source)
        if source == "template_fallback" and gres.output is not None and gres.violations:    # o guardrail barrou o texto do modelo: grava-o, para julgar falso positivo pelo texto
            meta.update(self._blocked_text(gres.output.reply))
        self._say(t, kind, text, meta=meta)

    def _blocked_text(self, reply: str) -> dict[str, str]:
        """O texto que o guardrail barrou, para o autor julgar se a barragem foi falso positivo. NUNCA vai ao lead. Passa pelo mascarador e e truncado no mesmo limite do detalhe de erro
        (`DETAIL_LIMIT`, mascarando ANTES de truncar). Se ainda sobrar PII ou segredo, pela varredura que o export usa, grava so a marca `blocked_reply_omitted`: o export nunca recusa a conversa por causa disto."""
        shown = self._excerpt(reply)
        return {"blocked_reply_omitted": "pii"} if shown is None else {"blocked_reply": shown}

    def _reply_action(self, t: _Turn, reply: templates.Reply, gres: GuardedResult | None) -> None:
        self._handoff(t, reply.handoff_reason or HandoffReason.OUT_OF_SCOPE, reply.text,
                      meta={**t.llm, "reply_source": reply.source, "intent": gres.output.intent if gres and gres.output else None})

    def _fail(self, t: _Turn, reason: HandoffReason, component: FailedComponent | None, *, detail: str, lead_in: str | None = None) -> None:
        text = templates.failure_handoff_text(reason, self._next_step) if lead_in is None else f"{lead_in} {templates.handoff_text(self._next_step)}"
        self._handoff(t, reason, text, component=component, detail=detail, meta={**t.llm, "reply_source": "template_failure"})

    def _handoff(self, t: _Turn, reason: HandoffReason, text: str, *, component: FailedComponent | None = None, detail: str = "",
                 meta: Mapping[str, Any] | None = None) -> None:
        conv = t.conv
        conv.status, conv.asked = "handoff", None
        self._store.update_conversation(t.trace, utc_now(), status="handoff", handoff_reason=reason.value,
                                        failed_component=component.value if component else None, handoff_detail=detail or None,
                                        slots=conv.ledger.snapshot(), llm_blocked_streak=conv.streak)
        package = self._package(conv, reason, component, text)
        self._deliver(conv, self._record_sink, package)          # 1) o registro no SQLite  2) a resposta ao lead  3) os outros destinos
        self._say(t, "handoff", text, meta={**(meta or {}), "handoff_reason": reason.value})
        for sink in self._sinks:
            self._deliver(conv, sink, package)

    @staticmethod
    def _deliver(conv: _Conv, sink: HandoffSink, package: HandoffPackage) -> None:
        try:
            sink.deliver(package)
        except (SinkUnavailable, SinkRejected):          # o handoff fica pendente; o que o lead leu continua verdadeiro (o registro local existe)
            conv.undelivered.append((sink, package))

    def _package(self, conv: _Conv, reason: HandoffReason, component: FailedComponent | None, told: str) -> HandoffPackage:
        v = dict(conv.ledger.verified())
        plano = plano_for(v["necessidade"], self._planos) if "necessidade" in v else None
        qualification = {"idade": int(v["idade"]) if "idade" in v else None, "veiculo_ano": int(v["veiculo_ano"]) if "veiculo_ano" in v else None,
                         "cep": v.get("cep"), "plano_id": plano or (conv.last_ref.plano_id if conv.last_ref else None), "data_inicio": v.get("data_inicio")}
        recent = [m for m in self._store.messages(conv.trace_id) if m["kind"] != "hold"][-MAX_RECENT_MESSAGES:]
        verdict = (precheck(self._rules, idade=int(v["idade"]), veiculo_ano=int(v["veiculo_ano"]), today=self._today()).label
                   if v.get("idade", "").isdigit() and v.get("veiculo_ano", "").isdigit() else None)
        return HandoffPackage(
            trace_id=conv.trace_id, reason=reason, created_at=utc_now(), qualification=qualification,
            missing=tuple(s for s in ORDER if s not in v), last_quote=conv.last_ref,
            recent_messages=tuple(MaskedMessage(m["role"], m["text"], datetime.fromisoformat(m["ts"])) for m in recent),
            told_to_lead=told, failed_component=component, precheck=verdict)

    def _last_resort(self, t: _Turn, exc: BaseException) -> None:
        """Excecao inesperada: o lead recebe uma resposta honesta e a conversa vai a um humano. So o NOME da excecao e registrado (nunca a mensagem)."""
        detail = type(exc).__name__
        if t.has_terminal:                               # a mensagem terminal ja saiu; so registra
            try:
                self._store.update_conversation(t.trace, utc_now(), handoff_detail=f"erro_apos_resposta:{detail}")
            except Exception:  # noqa: BLE001
                pass
            return
        try:
            self._fail(t, HandoffReason.SAFETY_GUARD, FailedComponent.ORCHESTRATOR, detail=detail)
        except Exception:  # noqa: BLE001 - nem o banco responde: o lead ainda assim le algo
            text = f"{templates.SAFETY} {templates.handoff_text(self._next_step)}"
            out = Out("handoff", text, self._ids.new("msg"))
            t.out.append(out)
            if t.send:
                try:
                    t.send(out)
                except Exception:  # noqa: BLE001
                    pass

    # --- registro -------------------------------------------------------------------------------------------------------------------------------
    def _say(self, t: _Turn, kind: str, text: str, *, quote_id: str | None = None, meta: Mapping[str, Any] | None = None, terminal: bool = True) -> Out:
        mid = self._ids.new("msg")
        self._store.add_message(t.trace, mid, role="agent", kind=kind, text=text, ts=utc_now(), status="sent", quote_id=quote_id, meta={**t.extra, **(meta or {})})
        if terminal:
            t.conv.spoke = True
        out = Out(kind, text, mid, terminal)
        t.out.append(out)
        if t.send:
            try:
                t.send(out)
            except Exception:  # noqa: BLE001 - o canal falhar nao desfaz o que ja foi registrado
                pass
        return out

    @staticmethod
    def _meta(t: _Turn, reply: templates.Reply, gres: GuardedResult, nq: _Next | None, *, source: str | None = None) -> dict[str, Any]:
        out = gres.output
        violations = list(reply.violations) or sorted({v.rule for v in gres.violations})
        return {**t.llm, "reply_source": source or reply.source, "intent": out.intent if out else None, "facts_used": list(reply.facts_used),
                "violations": violations, **({"asked": [nq.slot, nq.kind]} if nq else {})}

    def _persist_state(self, conv: _Conv) -> None:
        try:
            self._store.update_conversation(conv.trace_id, utc_now(), slots=conv.ledger.snapshot(), llm_blocked_streak=conv.streak, status=conv.status)
        except Exception:  # noqa: BLE001 - o snapshot e auditoria, nao pode derrubar o turno
            pass

    def _history(self, trace_id: str) -> tuple[list[tuple[str, str]], list[str]]:
        """(historico para o prompt, textos do lead). Tudo ja mascarado; sem cotacao, recusa nem handoff (nada de preco volta ao modelo)."""
        msgs = [m for m in self._store.messages(trace_id) if m["role"] == "lead" or m["kind"] in HISTORY_KINDS]
        msgs = msgs[:-1][-HISTORY_WINDOW:]               # a ultima e a mensagem de AGORA, que vai separada
        return ([("lead" if m["role"] == "lead" else "assistente", m["text"]) for m in msgs], [m["text"] for m in msgs if m["role"] == "lead"])

    def _replay(self, trace_id: str, lead_seq: int) -> tuple[Out, ...]:
        out = []
        for m in self._store.messages(trace_id):
            if m["seq"] <= lead_seq:
                continue
            if m["role"] == "lead":
                break
            out.append(Out(m["kind"], m["text"], m["id"], m["kind"] != "hold"))
        return tuple(out)


def _asks(slot: str, text: str) -> bool:
    """O reply do modelo faz UMA pergunta sobre o dado que o estado pede? Senao, quem pergunta e o produto."""
    return "?" in text and bool(_TOPIC[slot].search(strip_accents(text).lower()))


def _mentions(reading: Any, slot: str) -> bool:
    """A mensagem de agora traz algo sobre este slot? Um slot ja verificado so e substituido se o lead escreveu um valor novo para ele."""
    if slot in ("veiculo_ano", "cep"):
        return bool(reading.candidates(slot))
    if slot == "idade":
        return bool(reading.candidates(slot)) or bool(reading.birth_years)
    if slot == "necessidade":
        return implied_tier(reading.plain) is not None
    return bool(reading.dates) or bool(reading.relative_date)
