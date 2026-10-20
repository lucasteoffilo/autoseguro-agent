"""Gate de PII e guardrail do `reply`: ACIMA do provedor, nunca dentro de um adaptador.

`GuardedLLM` envolve QUALQUER cliente de LLM (Anthropic, OpenRouter, outro endpoint compativel):
  - ANTES de qualquer chamada, o detector de PII roda no prompt de sistema e na mensagem do usuario; achou algo, levanta `UnsafePayload` e
    nada sai da maquina (nem um byte chega ao adaptador);
  - DEPOIS da resposta (ja validada contra o esquema local), o guardrail confere o `reply` contra a base de fatos; reprovado, o orquestrador
    usa o template do passo.
Trocar de provedor, portanto, nao contorna nenhum dos dois: a fabrica (`llm/factory.py`) so devolve clientes guardados.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..facts import FactBase
from ..guardrail import Violation, check_reply
from ..pii import find_pii
from .base import LLMClient, LLMResult
from .schema import TurnOutput


class UnsafePayload(RuntimeError):
    """Algo que parece PII ou segredo estava prestes a sair da maquina. Nada foi enviado."""


def assert_safe_to_send(*texts: str) -> None:
    kinds = sorted({k for t in texts for k in find_pii(t)})
    if kinds:
        raise UnsafePayload(f"PII/segredo detectado ({', '.join(kinds)}); nada foi enviado")


@dataclass(frozen=True)
class GuardedResult:
    result: LLMResult
    violations: tuple[Violation, ...]

    @property
    def output(self) -> TurnOutput | None:
        return self.result.output

    @property
    def reply_ok(self) -> bool:
        """O `reply` pode ir ao lead: houve saida valida E o guardrail nao achou nada."""
        return self.result.output is not None and not self.violations

    @property
    def reply_source(self) -> str:
        return "llm" if self.reply_ok else "template_fallback"


class GuardedLLM:
    def __init__(self, inner: LLMClient, fact_base: FactBase) -> None:
        self._inner, self._facts = inner, fact_base

    @property
    def inner(self) -> LLMClient:
        return self._inner

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def system_prompt(self) -> str:
        return self._inner.system_prompt

    def __repr__(self) -> str:
        return f"GuardedLLM({self._inner!r})"

    def turn(self, user_message: str, *, lead_texts: Sequence[str] = ()) -> GuardedResult:
        """`lead_texts`: o que o LEAD escreveu (mensagem e janela). So numeros daqui, ou de fatos citados, podem ecoar no `reply`."""
        assert_safe_to_send(self._inner.system_prompt, user_message)  # antes de qualquer chamada
        result = self._inner.turn(user_message)
        violations = () if result.output is None else check_reply(
            result.output.reply, facts_used=result.output.facts_used, base=self._facts, lead_texts=lead_texts)
        return GuardedResult(result, violations)
