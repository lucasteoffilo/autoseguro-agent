"""Ancoragem de slots: o preco nao pode depender da acuracia do modelo.

INVARIANTE: nenhum slot chega ao cliente da /quote sem estar ANCORADO no texto do lead ou CONFIRMADO por ele.

O LLM so PROPOE valores. Quem decide se um valor vira dado de cotacao e este modulo, sem modelo nenhum:
  - ANCORADO: o valor aparece LITERALMENTE no que o lead escreveu, e e o UNICO candidato daquele slot nessa mensagem, e nem o modelo
    nem o proprio lead hesitaram. Nao custa turno.
  - PENDENTE: tudo o resto. Valor que nao esta no texto (inventado, calculado ou "completado"), varios candidatos (m08 do smoke: "o carro
    e 2015 mas o modelo e 2016"), dado DERIVADO (ano de nascimento: nunca vira idade; pergunta-se a idade), hesitacao ("acho que",
    "uns 35") ou incerteza marcada pelo modelo. O sistema faz uma pergunta de confirmacao TEMPLATE (`questions.py`), nao redigida pelo LLM.
  - CONFIRMADO: o lead respondeu a confirmacao, ou deu o valor de novo, por escrito.
A flag `uncertain` do modelo so pode ACRESCENTAR confirmacoes, nunca retirar: o smoke mostrou o mesmo modelo marcando a incerteza numa
repeticao e nao marcando na outra.

O unico caminho para um `QuoteRequest` e `SlotLedger.quote_request()`, e o unico chamador do cliente da /quote e `QuoteGate`; ambos so
enxergam `VerifiedSlots`, que so o livro-razao sabe criar. Testes estruturais conferem que nenhum outro modulo faz isso.

LIMITES CONHECIDOS (documentados no README, sem codigo): negacao ("o carro NAO e 2015"), numero por extenso ("trinta e cinco") e numero
com dono errado ("meu filho tem 20 anos") escapam desta checagem; o primeiro e o terceiro passam por serem literais e unicos, o segundo
cai em pergunta. A rede contra eles e a repeticao dos dados na mensagem de cotacao (`questions.recap`).
"""
from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

from . import questions
from .facts import FactBase, strip_accents
from .llm.schema import NECESSIDADES, SLOT_NAMES, SlotValue, TurnOutput
from .quote_client import QuoteClient, QuoteOutcome
from .slots import QuoteRequest, SlotIssue, build_quote_request


class Status(StrEnum):
    ANCHORED = "anchored"
    CONFIRMED = "confirmed"
    PENDING = "pending"


class Reason(StrEnum):
    OUT_OF_TEXT = "fora_do_texto"            # o valor do modelo nao esta no que o lead escreveu
    MANY = "multiplos_candidatos"            # ha mais de um candidato no texto
    TWO_READINGS = "duas_leituras_do_modelo"  # o proprio modelo devolveu dois valores
    UNCERTAIN = "modelo_incerto"             # o modelo marcou uncertain
    HEDGE = "lead_hesitou"                   # "acho que", "uns", "nao tenho certeza"
    DERIVED = "derivado"                     # ano de nascimento (idade) ou data relativa
    NOT_ASKED = "nao_perguntado"             # necessidade citada sem ter sido perguntada
    NOT_AN_ANSWER = "pergunta_nao_e_resposta"
    DENIED = "lead_negou"


@dataclass(frozen=True)
class Cand:
    value: str          # normalizado
    text: str           # trecho literal do lead
    label: str = ""     # "modelo" | "fabricacao" (so veiculo_ano)


@dataclass(frozen=True)
class SlotState:
    slot: str
    status: Status
    value: str | None = None
    evidence: str = ""
    reason: Reason | None = None
    candidates: tuple[str, ...] = ()
    proposed: str | None = None
    note: str = ""      # ex.: o ano de nascimento citado

    @property
    def quotable(self) -> bool:
        return self.status in (Status.ANCHORED, Status.CONFIRMED)


# --- leitura do texto do lead (sem modelo) --------------------------------------------------------------------------------------------------
_CEP_RX = re.compile(r"(?<!\d)(\d{2})\.?(\d{3})-?(\d{3})(?!\d)")
_ISO_RX = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_BR_DATE_RX = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
_PARTIAL_DATE_RX = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d|/\d)")
_SLASH_YEARS_RX = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*/\s*((?:19|20)\d{2})(?!\d)")
_BIRTH_RX = re.compile(r"nasc\w*\W{0,3}(?:em\W{0,3})?(?:no ano de\W{0,3})?((?:19|20)\d{2})")
_YEAR_RX = re.compile(r"(?<!\d)((?:19[5-9]|20[0-3])\d)(?!\d)")
_AGE_MARKER_RX = (re.compile(r"\btenho\s+(\d{1,3})\b"), re.compile(r"(?<!\d)(\d{1,3})\s+anos\b"), re.compile(r"\bidade\W{0,12}(\d{1,3})\b"))
_ANY_SMALL_NUMBER_RX = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
_RELATIVE_DATE_RX = re.compile(r"\b(hoje|amanha|depois de amanha|segunda|terca|quarta|quinta|sexta|sabado|domingo|semana que vem|"
                               r"mes que vem|proximo mes|dia \d{1,2}|assim que|o quanto antes)\b")
_HEDGE_RX = re.compile(r"\b(acho|achando|acredito|creio|talvez|quase|uns|umas|mais ou menos|aproximadamente|por volta|chuto|chutando|"
                       r"n tenho certeza|nao tenho certeza|nao sei|n sei|sei la)\b")
_AGE_MIN, _AGE_MAX = 16, 110

_TIER_WORDS = (
    ("completa", re.compile(r"\b(complet[oa]|carro[- ]reserva|assistencia|premium)")),
    ("terceiros_vidros", re.compile(r"\b(terceir\w*|vidro\w*)")),
    ("basica", re.compile(r"\b(basic[oa]|essencial|roubo|furto|colis\w*)")),
)
_YES_RX = re.compile(r"^\s*(sim|isso|isso mesmo|isso ai|correto|certo|exato|exatamente|confirmo|confirmado|pode ser|ss|s|uhum|aham|positivo)\b")
_NO_RX = re.compile(r"^\s*(nao|negativo|errado|nada disso|n)\s*([,.!]|$)")


def _blank(s: str, span: tuple[int, int]) -> str:
    return s[:span[0]] + " " * (span[1] - span[0]) + s[span[1]:]


@dataclass(frozen=True)
class TextReading:
    """O que um LEITOR DETERMINISTICO enxerga na mensagem do lead. Independente de qualquer modelo."""

    plain: str
    ceps: tuple[Cand, ...] = ()
    years: tuple[Cand, ...] = ()
    ages: tuple[Cand, ...] = ()
    dates: tuple[Cand, ...] = ()
    birth_years: tuple[int, ...] = ()
    relative_date: bool = False
    hedge: bool = False
    question: bool = False

    def candidates(self, slot: str) -> tuple[Cand, ...]:
        return {"cep": self.ceps, "veiculo_ano": self.years, "idade": self.ages, "data_inicio": self.dates}.get(slot, ())


def read_text(text: str, asked_slot: str | None = None) -> TextReading:
    plain = strip_accents(text).lower()
    rest = plain
    ceps: list[Cand] = []
    for m in _CEP_RX.finditer(plain):
        ceps.append(Cand("".join(m.groups()), m.group(0)))
        rest = _blank(rest, m.span())

    dates: list[Cand] = []
    for m in _ISO_RX.finditer(rest):
        dates.append(Cand(m.group(0), m.group(0)))
    rest = _ISO_RX.sub(lambda m: " " * len(m.group(0)), rest)
    for m in _BR_DATE_RX.finditer(rest):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dates.append(Cand(date(y, mo, d).isoformat(), m.group(0)))
        except ValueError:
            pass
    rest = _BR_DATE_RX.sub(lambda m: " " * len(m.group(0)), rest)
    partial = bool(_PARTIAL_DATE_RX.search(rest))
    rest = _PARTIAL_DATE_RX.sub(lambda m: " " * len(m.group(0)), rest)

    years: list[Cand] = []
    slash_spans = []
    for m in _SLASH_YEARS_RX.finditer(rest):  # 2015/2016: fabricacao/modelo, como no documento do carro
        years += [Cand(m.group(1), m.group(1), "fabricacao"), Cand(m.group(2), m.group(2), "modelo")]
        slash_spans.append(m.span())
    for sp in slash_spans:
        rest = _blank(rest, sp)

    births = []
    for m in _BIRTH_RX.finditer(rest):
        births.append(int(m.group(1)))
        rest = _blank(rest, m.span())

    for m in _YEAR_RX.finditer(rest):
        before, after = rest[max(0, m.start() - 16):m.start()], rest[m.end():m.end() + 12]
        if re.search(r"model\w*\W*(?:e|eh|:|=)?\W*$", before) or re.match(r"\W{0,3}\(?model", after):
            label = "modelo"
        elif re.search(r"fabrica\w*\W*(?:e|eh|:)?\W*$", before) or re.match(r"\W{0,3}\(?fabric", after):
            label = "fabricacao"
        else:
            label = ""
        years.append(Cand(m.group(1), m.group(1), label))
    rest = _YEAR_RX.sub(lambda m: " " * len(m.group(0)), rest)

    found: list[str] = []
    if asked_slot == "idade":
        found = _ANY_SMALL_NUMBER_RX.findall(rest)
    else:
        for rx in _AGE_MARKER_RX:
            found += rx.findall(rest)
    ages = [Cand(str(int(n)), n) for n in dict.fromkeys(found) if _AGE_MIN <= int(n) <= _AGE_MAX]
    ages = list({c.value: c for c in ages}.values())

    return TextReading(
        plain=plain, ceps=tuple(ceps), years=tuple({c.value + c.label: c for c in years}.values()), ages=tuple(ages),
        dates=tuple({c.value: c for c in dates}.values()), birth_years=tuple(births),
        relative_date=partial or bool(_RELATIVE_DATE_RX.search(plain)), hedge=bool(_HEDGE_RX.search(plain)), question="?" in text)


def implied_tier(plain: str) -> tuple[str, str] | None:
    """(necessidade, palavra) pela MAIOR cobertura que o lead nomeou, ou None. Lexico fechado: o que nao esta aqui nao ancora."""
    for tier, rx in _TIER_WORDS:
        if m := rx.search(plain):
            return tier, m.group(0)
    return None


# --- normalizacao do valor que o MODELO propos -------------------------------------------------------------------------------------------------
def _norm(slot: str, raw: str) -> str | None:
    s = raw.strip()
    if slot == "idade":
        m = re.fullmatch(r"(\d{1,3})\s*(?:anos)?", s.lower())
        return str(int(m.group(1))) if m else None
    if slot == "veiculo_ano":
        return s if re.fullmatch(r"\d{4}", s) else None
    if slot == "cep":
        d = re.sub(r"[.\-\s]", "", s)
        return d if re.fullmatch(r"\d{8}", d) else None
    if slot == "necessidade":
        return s.lower() if s.lower() in NECESSIDADES else None
    if slot == "data_inicio":
        try:
            return date.fromisoformat(s).isoformat() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else None
        except ValueError:
            return None
    return None


def _pending(slot: str, reason: Reason, *, candidates: Sequence[str] = (), proposed: str | None = None, note: str = "") -> SlotState:
    return SlotState(slot, Status.PENDING, reason=reason, candidates=tuple(candidates), proposed=proposed, note=note)


def _anchored(slot: str, value: str, evidence: str) -> SlotState:
    return SlotState(slot, Status.ANCHORED, value=value, evidence=evidence)


def anchor(slot: str, entries: Sequence[SlotValue], reading: TextReading, *, asked_slot: str | None) -> SlotState:
    """Classifica o que o modelo propos para UM slot. Nao confia em nada que o modelo diz alem do valor, e so aceita o valor se ele estiver
    no texto do lead."""
    values = [v for e in entries if (v := _norm(slot, e.value)) is not None]
    llm_values = list(dict.fromkeys(values))
    uncertain = any(e.uncertain for e in entries)

    if slot == "necessidade":
        return _anchor_need(llm_values, uncertain, reading, asked_slot)
    if slot == "data_inicio":
        return _anchor_date(llm_values, uncertain, reading)

    cands = reading.candidates(slot)
    cvals = tuple(dict.fromkeys(c.value for c in cands))
    if len(llm_values) > 1:
        return _pending(slot, Reason.TWO_READINGS, candidates=cvals)
    if not cands:
        if slot == "idade" and reading.birth_years:
            return _pending(slot, Reason.DERIVED, note=str(reading.birth_years[0]))  # nunca calcula: pergunta a idade
        return _pending(slot, Reason.OUT_OF_TEXT)
    if len(cvals) > 1:
        labeled = [c.value for c in cands if c.label == "modelo"]
        return _pending(slot, Reason.MANY, candidates=cvals, proposed=labeled[0] if slot == "veiculo_ano" and len(labeled) == 1 else None)
    c = cands[0]
    if not llm_values or llm_values[0] != c.value:
        return _pending(slot, Reason.OUT_OF_TEXT, candidates=(c.value,), proposed=c.value)
    if uncertain:
        return _pending(slot, Reason.UNCERTAIN, proposed=c.value)
    if reading.hedge:
        return _pending(slot, Reason.HEDGE, proposed=c.value)
    return _anchored(slot, c.value, c.text)


def _anchor_need(llm_values: list[str], uncertain: bool, reading: TextReading, asked_slot: str | None) -> SlotState:
    """Necessidade e CLASSIFICACAO, nao leitura: so ancora como resposta a pergunta de necessidade, com palavra do lexico fechado e sem '?'."""
    slot = "necessidade"
    if reading.question:
        return _pending(slot, Reason.NOT_AN_ANSWER)
    if asked_slot != slot:
        return _pending(slot, Reason.NOT_ASKED)
    tier = implied_tier(reading.plain)
    if tier is None or len(llm_values) != 1 or llm_values[0] != tier[0]:
        return _pending(slot, Reason.OUT_OF_TEXT)
    if uncertain:
        return _pending(slot, Reason.UNCERTAIN)
    if reading.hedge:
        return _pending(slot, Reason.HEDGE)
    return _anchored(slot, tier[0], tier[1])


def _anchor_date(llm_values: list[str], uncertain: bool, reading: TextReading) -> SlotState:
    """Data por extenso e completa ancora. Data relativa ("segunda que vem") e DERIVADA: o lead confirma a data CALCULADA, mostrada na pergunta."""
    slot = "data_inicio"
    cvals = tuple(c.value for c in reading.dates)
    v = llm_values[0] if len(llm_values) == 1 else None
    if len(cvals) > 1:
        return _pending(slot, Reason.MANY, candidates=cvals)
    if len(cvals) == 1:
        if v == cvals[0] and not uncertain and not reading.hedge:
            return _anchored(slot, v, reading.dates[0].text)
        return _pending(slot, Reason.OUT_OF_TEXT if v != cvals[0] else Reason.UNCERTAIN, candidates=cvals, proposed=cvals[0])
    if v is not None and reading.relative_date:
        return _pending(slot, Reason.DERIVED, proposed=v)
    return _pending(slot, Reason.OUT_OF_TEXT)


# --- livro-razao, tipo verificado e pedido de cotacao -------------------------------------------------------------------------------------------
_MINT = object()


class VerifiedSlots(Mapping[str, str]):
    """Slots que passaram pela ancoragem ou pela confirmacao. So `SlotLedger.verified()` sabe criar um: quem tenta de fora leva TypeError."""

    __slots__ = ("_data",)

    def __init__(self, token: object, data: Mapping[str, str]) -> None:
        if token is not _MINT:
            raise TypeError("VerifiedSlots so e criado pelo SlotLedger: um dado nao verificado nao vira pedido de cotacao")
        self._data = dict(data)

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"VerifiedSlots({self._data!r})"


@dataclass(frozen=True)
class NotQuotable:
    """Nao ha pedido de cotacao: o que falta (nunca dito), o que esta pendente (dito mas nao verificado) e o que a higiene de entrada recusou."""

    missing: tuple[str, ...]
    pending: tuple[SlotState, ...]
    issues: tuple[SlotIssue, ...] = ()


def plano_for(necessidade: str, planos: Mapping[str, Any]) -> str | None:
    """Necessidade -> plano pelo numero de coberturas (o menor plano que cobre o pedido). None se nao ha plano para a opcao."""
    tiers = sorted(planos["planos"], key=lambda p: len(p["coberturas"]))
    idx = NECESSIDADES.index(necessidade)
    return tiers[idx]["id"] if idx < len(tiers) else None


class SlotLedger:
    """O estado de verificacao dos slots de UMA conversa. O orquestrador alimenta com `ingest` (saida do LLM + texto do lead) e `answer`
    (resposta do lead a uma confirmacao), pergunta o que esta pendente com `question`, e so cota por `quote_request`."""

    def __init__(self) -> None:
        self._states: dict[str, SlotState] = {}
        self._attempts: dict[str, int] = {}

    def state(self, slot: str) -> SlotState | None:
        return self._states.get(slot)

    def attempts(self, slot: str) -> int:
        """Quantas vezes a confirmacao deste slot falhou (o orquestrador leva ao humano depois de 2: `DATA_AMBIGUOUS`)."""
        return self._attempts.get(slot, 0)

    def ingest(self, output: TurnOutput, lead_text: str, *, asked_slot: str | None = None) -> tuple[SlotState, ...]:
        """Confere cada slot que o modelo propos contra o texto do lead. Um valor novo SUBSTITUI o anterior do mesmo slot (correcao)."""
        reading = read_text(lead_text, asked_slot)
        out = []
        for slot in dict.fromkeys(s.slot for s in output.slots):
            st = anchor(slot, output.entries(slot), reading, asked_slot=asked_slot)
            self._states[slot] = st
            self._attempts.pop(slot, None)
            out.append(st)
        return tuple(out)

    def answer(self, slot: str, lead_text: str) -> SlotState | None:
        """Resolve uma confirmacao pendente com a resposta do lead, SEM LLM: "sim" confirma o valor proposto; um valor escrito pelo lead, unico
        e sem hesitacao, vale como dado dele. Qualquer outra coisa deixa pendente e conta uma tentativa."""
        st = self._states.get(slot)
        if st is None or st.quotable:
            return st
        reading = read_text(lead_text, slot)
        yes, no = bool(_YES_RX.match(reading.plain)), bool(_NO_RX.match(reading.plain))
        if yes and st.proposed is not None and not reading.hedge:
            new = SlotState(slot, Status.CONFIRMED, value=st.proposed, evidence=f"confirmou: {lead_text.strip()[:40]}")
        else:
            new = self._from_reply(slot, st, reading, denied=no)
        if not new.quotable:
            self._attempts[slot] = self._attempts.get(slot, 0) + 1
        self._states[slot] = new
        return new

    @staticmethod
    def _from_reply(slot: str, st: SlotState, reading: TextReading, *, denied: bool) -> SlotState:
        if slot == "necessidade":
            tier = None if reading.question else implied_tier(reading.plain)
            if tier is not None and not reading.hedge:
                return SlotState(slot, Status.CONFIRMED, value=tier[0], evidence=tier[1])
        else:
            cands = reading.candidates(slot)
            if len(cands) == 1 and not reading.hedge:
                return SlotState(slot, Status.CONFIRMED, value=cands[0].value, evidence=cands[0].text)
        return _pending(slot, Reason.DENIED if denied else (st.reason or Reason.OUT_OF_TEXT), candidates=st.candidates,
                        proposed=None if denied else st.proposed, note=st.note)

    def pending(self) -> tuple[SlotState, ...]:
        return tuple(st for st in self._states.values() if not st.quotable)

    def question(self, slot: str, base: FactBase | None = None) -> str:
        """A pergunta de confirmacao (template) para um slot pendente, ou a pergunta do produto se ele ainda nao existe."""
        st = self._states.get(slot)
        if st is None or st.quotable:
            return questions.ask(slot, base)
        return questions.confirm(slot, proposed=st.proposed, candidates=st.candidates,
                                 derived_from=st.note if st.reason is Reason.DERIVED and st.note else None, base=base)

    def verified(self) -> VerifiedSlots:
        return VerifiedSlots(_MINT, {s: st.value for s, st in self._states.items() if st.quotable and st.value is not None})

    def quote_request(self, planos: Mapping[str, Any], *, today: date) -> QuoteRequest | NotQuotable:
        """O UNICO caminho para um `QuoteRequest`. Cada campo vem de um slot verificado; `plano_id` sai da necessidade verificada."""
        v = self.verified()
        pend = self.pending()
        pending_slots = {st.slot for st in pend}
        missing = tuple(s for s in SLOT_NAMES if s not in v and s not in pending_slots)
        if missing or pend:
            return NotQuotable(missing, pend)
        plano = plano_for(v["necessidade"], planos)
        if plano is None:
            return NotQuotable((), (), (SlotIssue("necessidade", "sem_plano_correspondente"),))
        built = build_quote_request(
            {"plano_id": plano, "idade": v["idade"], "veiculo_ano": v["veiculo_ano"], "cep": v["cep"], "data_inicio": v["data_inicio"]},
            today=today, known_plans=[p["id"] for p in planos["planos"]])
        return NotQuotable((), (), built) if isinstance(built, tuple) else built


class QuoteGate:
    """O unico chamador do cliente da /quote. Se algum slot nao esta verificado, o cliente NAO e chamado."""

    def __init__(self, client: QuoteClient, planos: Mapping[str, Any]) -> None:
        self._client, self._planos = client, planos

    def quote(self, ledger: SlotLedger, *, today: date, **client_kwargs: Any) -> QuoteOutcome | NotQuotable:
        built = ledger.quote_request(self._planos, today=today)
        if isinstance(built, NotQuotable):
            return built
        return self._client.quote(built, **client_kwargs)
