"""A fronteira adaptador -> diagnostico: o `provider_name` que o OpenRouter manda em `error.metadata` chega ao texto do 404, de ponta a ponta.

Fica separado de test_diagnose.py porque depende do adaptador guardar o metadata no detalhe (`provedor=<nome>`): sem ele, o texto do 404 fica generico.
O formato `... | provedor=<nome> | retorno=...` e um contrato entre openai_compat.py e diagnose.py; aqui os dois sao exercitados juntos.
"""
from __future__ import annotations

import pytest

from tests.fake_servers import CANARY_KEY, FakeServer, error_json
from tools import llm_ping, smoke_llm


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", CANARY_KEY)
    s = FakeServer()
    s.reply(404, error_json(404, "Provider returned error", provider_name="Nvidia", raw="model endpoint is not available"))
    yield s
    s.close()


def test_the_ping_names_the_provider_the_metadata_reported(tmp_path, server, capsys):
    assert llm_ping.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--timeout", "3"]) == 6
    err = capsys.readouterr().err
    assert "detalhe do provedor: Provider returned error | provedor=Nvidia | retorno=model endpoint is not available" in err
    assert "(1) o modelo ou o provedor Nvidia (o que devolveu o erro) esta fora do ar, ou o modelo nao existe" in err
    assert "(2) nenhum provedor aceita TODOS os parametros" in err


def test_the_smoke_abort_names_the_provider_the_metadata_reported(tmp_path, server, capsys):
    code = smoke_llm.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--rpm", "60000", "--no-remote-check", "--repeats", "1", "--timeout", "3"])
    err = capsys.readouterr().err
    assert code == 6 and len(server.requests) == 1
    assert "provedor=Nvidia" in err and "o provedor Nvidia (o que devolveu o erro) esta fora do ar" in err


def test_a_404_without_metadata_stays_generic_end_to_end(tmp_path, server, capsys):
    server.reply(404, error_json(404, "Provider returned error"))
    assert llm_ping.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--timeout", "3"]) == 6
    err = capsys.readouterr().err
    assert "o provedor dele esta fora do ar" in err and "o que devolveu o erro" not in err


def test_a_key_echoed_inside_the_metadata_reaches_neither_the_detail_nor_the_diagnosis(tmp_path, server, capsys):
    server.reply(404, error_json(404, "Provider returned error", provider_name=f"Prov-{CANARY_KEY}", raw=f"rejected {CANARY_KEY}"))
    assert llm_ping.main(["--base-url", server.url, "--out-dir", str(tmp_path), "--timeout", "3"]) == 6
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert CANARY_KEY not in text and "CANARY" not in text and "sk-or" not in text and "[REDACTED]" in text
