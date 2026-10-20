"""Fumaca da API de teste (docker-compose.test.yml, porta 8100). Rode com `make test-integration`."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.integration
URL = os.getenv("QUOTE_API_URL", "http://localhost:8100")
PAYLOAD = {"plano_id": "completo", "idade": 35, "veiculo_ano": 2022, "cep": "01310-100"}


def _req(path: str, payload: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(URL + path, data=data, headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def test_health():
    assert _req("/health") == (200, {"status": "ok"})


def test_planos_expoe_os_dados_que_a_precheck_vai_ler():
    status, body = _req("/planos")
    assert status == 200
    assert [p["id"] for p in body["planos"]] == ["essencial", "completo", "premium"]
    regras = body["regras"]
    assert {"faixa_etaria", "idade_veiculo", "regiao_cep", "carencia"} <= set(regras)
    assert regras["regiao_cep"]["prefixos_alto_risco"]


def test_instancia_de_teste_nao_injeta_falhas():
    statuses = {_req("/quote", PAYLOAD)[0] for _ in range(40)}
    assert statuses == {200}
