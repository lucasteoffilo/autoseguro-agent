"""O servico de cotacao SEM REDE: a logica vendorizada (vendor/quote-service/app/quote_logic.py) executada em processo, com o relogio fixado em `today`.

E o mesmo codigo que roda no container da API, so sem o FastAPI, sem a instabilidade simulada e sem a rede. Serve de `Transport` para o cliente da /quote
(`VendoredTransport`) e de oraculo para os evals e para o contrato da pre-checagem (`service_verdict`). O modo HTTP (`--api`) usa a API de verdade.
"""
from __future__ import annotations

import importlib.util
import json
import types
from datetime import date
from pathlib import Path
from typing import Any

from autoseguro.quote_client import RawResponse

ROOT = Path(__file__).resolve().parent.parent
LOGIC = ROOT / "vendor" / "quote-service" / "app" / "quote_logic.py"
PLANOS = ROOT / "vendor" / "quote-service" / "data" / "plans.json"


def load_planos() -> dict[str, Any]:
    return json.loads(PLANOS.read_text(encoding="utf-8"))


class VendoredService:
    """`respond(payload)` -> (status, corpo), com as mesmas respostas do main.py: 200 com a cotacao, 422 `cotacao_recusada`, 400 `payload_invalido`."""

    def __init__(self, today: date) -> None:
        spec = importlib.util.spec_from_file_location("vendored_quote_logic", LOGIC)
        assert spec is not None and spec.loader is not None
        self._mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self._mod)

        class FixedDate(date):
            @classmethod
            def today(cls):
                return cls(today.year, today.month, today.day)

        self._mod.dt = types.SimpleNamespace(date=FixedDate)   # o servico so usa dt.date.today() e dt.date.fromisoformat
        self.today = today

    def respond(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        try:
            return 200, self._mod.cotar(dict(payload))
        except self._mod.CotacaoRecusada as exc:
            return 422, {"error": "cotacao_recusada", "motivo": exc.motivo}
        except (KeyError, ValueError, TypeError) as exc:
            return 400, {"error": "payload_invalido", "detalhe": str(exc)}


class _Done:
    def __init__(self, resp: RawResponse) -> None:
        self._resp = resp

    def wait(self, timeout_s: float) -> RawResponse | None:
        return self._resp

    def abandon(self) -> None:
        pass


class VendoredTransport:
    """`Transport` do cliente da /quote em cima do servico em processo. Conta as chamadas (`payloads`) para os evals conferirem."""

    def __init__(self, today: date) -> None:
        self.service = VendoredService(today)
        self.payloads: list[dict[str, Any]] = []

    def start(self, payload: dict[str, Any]) -> _Done:
        self.payloads.append(dict(payload))
        status, body = self.service.respond(payload)
        return _Done(RawResponse(status, json.dumps(body).encode()))
