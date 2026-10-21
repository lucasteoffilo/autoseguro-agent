"""Destino do handoff: o agente entrega um `HandoffPackage` a um `HandoffSink` e nao sabe o que ha do outro lado.

Padrao (Etapa 2b): `SqliteSink`. Para plugar CRM ou fila, implemente `HandoffSink` e passe a suite de
`tests/sink_contract.py`; o agente nao muda. Aqui vive SO a interface: nenhuma integracao esta implementada.

Contrato de um sink (cada item e verificado por `tests/sink_contract.py`):
  1. Idempotente por `package.trace_id`: entregar de novo devolve o mesmo recibo e nao duplica nada.
  2. Nao altera o pacote.
  3. Falha transitoria -> `SinkUnavailable` (o chamador mantem o handoff pendente e tenta de novo).
     Falha permanente (o destino recusa o pacote) -> `SinkRejected` (repetir nao adianta; alertar).
     Nunca perde o pacote em silencio e nao lanca outra excecao para esses dois casos.
  4. Sincrono. Cada sink aplica o proprio timeout; o orquestrador nao deixa o lead esperando por ele (ordem abaixo).
  5. Nao grava nem loga nada alem dos campos do pacote, que e livre de identificadores diretos por construcao.

Ordem no orquestrador (2b): 1) grava o pacote no SQLite, que e o registro de rastreabilidade e sempre existe;
2) responde ao lead; 3) entrega ao sink configurado. Se o sink falhar, o handoff fica `pending` para nova tentativa e o
que foi dito ao lead continua verdadeiro, porque o registro local ja existe. Um CRM entra ALEM do SQLite, nunca no lugar.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Protocol, runtime_checkable

SCHEMA_VERSION = 1
MAX_RECENT_MESSAGES = 10
# Unicos campos de qualificacao permitidos no pacote. Um campo novo (ex.: "cpf", "nome") e rejeitado de proposito.
QUALIFICATION_SLOTS = ("idade", "veiculo_ano", "cep", "plano_id", "data_inicio")


class HandoffReason(StrEnum):
    """Motivo fixo do handoff. Vocabulario versionado: mudar um valor quebra quem consome o pacote."""

    QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"
    HUMAN_REQUESTED = "HUMAN_REQUESTED"
    COMPLAINT = "COMPLAINT"
    CLAIM_SINISTRO = "CLAIM_SINISTRO"
    CANCELLATION = "CANCELLATION"
    DATA_AMBIGUOUS = "DATA_AMBIGUOUS"
    MEDIA_UNREADABLE = "MEDIA_UNREADABLE"
    READY_TO_CLOSE = "READY_TO_CLOSE"
    CONVERSATION_STALLED = "CONVERSATION_STALLED"
    PRICE_OBJECTION = "PRICE_OBJECTION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    SAFETY_GUARD = "SAFETY_GUARD"


class FailedComponent(StrEnum):
    """Componente que falhou. O MOTIVO e a causa raiz e decide o codigo; o componente diz ONDE olhar. As duas coisas sao logadas."""

    LLM = "llm"
    GUARDRAIL = "guardrail"
    QUOTE_API = "quote_api"
    QUOTE_CLIENT = "quote_client"
    PRECHECK = "precheck"
    MASKER = "masker"
    STORE = "store"
    SINK = "sink"
    ORCHESTRATOR = "orchestrator"   # excecao inesperada no proprio orquestrador: o lead nunca fica sem resposta


# Estes motivos descrevem uma FALHA, entao exigem dizer qual componente falhou. Os demais sao decisoes (pedido do lead etc).
REASONS_REQUIRING_COMPONENT = frozenset({HandoffReason.QUOTE_UNAVAILABLE, HandoffReason.SAFETY_GUARD})


@dataclass(frozen=True)
class QuoteRef:
    """Referencia a ultima cotacao da conversa (o valor so existe quando a API respondeu 200)."""

    quote_id: str
    plano_id: str
    status: Literal["ok", "refused", "invalid", "unavailable"]
    premio_mensal: float | None = None


@dataclass(frozen=True)
class MaskedMessage:
    """Mensagem ja mascarada. O mascaramento e feito antes de chegar aqui; o pacote nunca carrega texto cru."""

    role: Literal["lead", "agent"]
    text: str
    ts: datetime


@dataclass(frozen=True)
class HandoffPackage:
    trace_id: str
    reason: HandoffReason
    created_at: datetime  # com fuso (UTC)
    qualification: Mapping[str, str | int | None]
    missing: tuple[str, ...]
    last_quote: QuoteRef | None
    recent_messages: tuple[MaskedMessage, ...]
    told_to_lead: str  # o texto EXATO enviado ao lead: o humano precisa saber o que foi prometido
    precheck: Literal["ok", "recusa_provavel"] | None = None
    failed_component: FailedComponent | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.reason in REASONS_REQUIRING_COMPONENT and self.failed_component is None:
            raise ValueError(f"{self.reason.value} exige failed_component: o motivo diz o que houve, o componente diz onde")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at precisa ter fuso horario (UTC)")
        if not self.told_to_lead.strip():
            raise ValueError("told_to_lead vazio: o pacote nao pode existir sem o que foi dito ao lead")
        extra = set(self.qualification) - set(QUALIFICATION_SLOTS)
        if extra:
            raise ValueError(f"campos de qualificacao nao permitidos: {sorted(extra)}")
        if len(self.recent_messages) > MAX_RECENT_MESSAGES:
            raise ValueError(f"no maximo {MAX_RECENT_MESSAGES} mensagens recentes")
        object.__setattr__(self, "qualification", MappingProxyType(dict(self.qualification)))  # somente leitura

    def to_dict(self) -> dict[str, object]:
        """Forma serializavel (JSON) entregue aos sinks. Estavel por `schema_version`."""
        q = self.last_quote
        return {
            "schema_version": self.schema_version,
            "trace_id": self.trace_id,
            "reason": self.reason.value,
            "created_at": self.created_at.isoformat(),
            "qualification": dict(self.qualification),
            "missing": list(self.missing),
            "last_quote": None if q is None else {"quote_id": q.quote_id, "plano_id": q.plano_id,
                                                   "status": q.status, "premio_mensal": q.premio_mensal},
            "precheck": self.precheck,
            "failed_component": None if self.failed_component is None else self.failed_component.value,
            "recent_messages": [{"role": m.role, "text": m.text, "ts": m.ts.isoformat()} for m in self.recent_messages],
            "told_to_lead": self.told_to_lead,
        }


@dataclass(frozen=True)
class DeliveryReceipt:
    trace_id: str
    status: Literal["delivered", "queued"]  # delivered: o destino confirmou; queued: aceito para entrega assincrona
    delivered_at: datetime
    external_ref: str | None = None  # id no CRM/fila, se houver


class SinkUnavailable(Exception):
    """Falha transitoria do destino: o handoff fica pendente e a entrega e repetida depois."""


class SinkRejected(Exception):
    """Falha permanente: o destino recusou este pacote. Repetir nao adianta; alertar um humano."""


@runtime_checkable
class HandoffSink(Protocol):
    def deliver(self, package: HandoffPackage) -> DeliveryReceipt:
        """Entrega o pacote. Ver o contrato no docstring do modulo."""
        ...
