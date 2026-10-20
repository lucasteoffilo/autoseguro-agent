"""Relogio virtual e transporte roteirizado para testar o cliente da /quote sem `sleep` e sem rede."""
from __future__ import annotations

import json
from dataclasses import dataclass

from autoseguro.quote_client import RawResponse, TransportConnectionError


class VirtualClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0, "sleep negativo"
        self.t += seconds


@dataclass
class Step:
    """Uma chamada roteirizada: leva `duration` s e responde `status`/`body`. status=None => erro de conexao ao completar."""

    duration: float
    status: int | None = 200
    body: bytes | dict | str = b""


def _encode(body: bytes | dict | str) -> bytes:
    return body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body).encode())


def ok_body(plano: str = "completo", premio: float = 209.9, *, pro_rata: bool = False, **over) -> dict:
    b = {
        "plano_id": plano, "plano_nome": plano.capitalize(), "premio_mensal": premio, "franquia": 3000,
        "coberturas": ["colisao", "roubo", "furto", "terceiros", "vidros"],
        "multiplicadores": {"faixa_etaria": 1.0, "idade_veiculo": 1.0, "regiao": 1.0},
        "carencia": {"coberturas": ["roubo", "furto"], "dias": 30, "observacao": "Roubo e furto so valem apos a carencia."},
        "moeda": "BRL",
    }
    if pro_rata:
        b["primeiro_pagamento_pro_rata"] = {"dias_no_mes": 30, "dias_cobrados": 16, "valor_primeiro_pagamento": 111.95}
    b.update(over)
    return b


def ok(duration: float = 0.1, **kw) -> Step:
    return Step(duration, 200, ok_body(**kw))


def err5xx(status: int = 503, duration: float = 0.1) -> Step:
    return Step(duration, status, {"error": "upstream_unavailable", "message": "Servico de cotacao temporariamente indisponivel."})


def refused(motivo: str = "Idade acima do limite de aceitacao (75 anos).", duration: float = 0.1) -> Step:
    return Step(duration, 422, {"error": "cotacao_recusada", "motivo": motivo})


def pydantic422(duration: float = 0.05) -> Step:
    return Step(duration, 422, {"detail": [{"type": "missing", "loc": ["body", "idade"], "msg": "Field required", "input": {}}]})


class FakeTransport:
    """Conta as chamadas 'em voo': iniciadas e ainda nao concluidas nem abandonadas pelo cliente."""

    def __init__(self, clock: VirtualClock, steps: list[Step]) -> None:
        self.clock, self.steps = clock, list(steps)
        self.calls = 0
        self.inflight = 0
        self.max_inflight = 0
        self.payloads: list[dict] = []

    def start(self, payload: dict) -> _FakePending:
        if self.calls >= len(self.steps):
            raise AssertionError("o cliente fez mais chamadas do que o roteiro previa")
        step = self.steps[self.calls]
        self.calls += 1
        self.payloads.append(payload)
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        return _FakePending(self, step)


class _FakePending:
    def __init__(self, transport: FakeTransport, step: Step) -> None:
        self._t, self._step = transport, step
        self._finish = transport.clock.now() + step.duration
        self._closed = False

    def wait(self, timeout_s: float):
        assert not self._closed, "wait() depois de concluida ou abandonada"
        clock = self._t.clock
        clock.sleep(max(0.0, min(self._finish, clock.now() + timeout_s) - clock.now()))
        if clock.now() >= self._finish - 1e-9:
            self._close()
            if self._step.status is None:
                raise TransportConnectionError("simulado")
            return RawResponse(self._step.status, _encode(self._step.body))
        return None

    def abandon(self) -> None:
        self._close()

    def _close(self) -> None:
        if not self._closed:
            self._closed = True
            self._t.inflight -= 1
