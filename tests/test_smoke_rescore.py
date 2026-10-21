"""Reaplicar o SlotLedger as extracoes gravadas (sem provedor): o gate de preco e o custo em turnos, lado a lado com o erro cru do modelo (README D7)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoseguro.llm.base import LLMResult
from autoseguro.llm.schema import SlotValue, TurnOutput
from tools import smoke_rescore
from tools.smoke_llm import load_fact_base, score_call
from tools.smoke_messages import SmokeMessage

FIX = Path(__file__).resolve().parent / "fixtures" / "smoke_replay"
RUN1 = json.loads((FIX / "dots-3-note-preview-2026-10-20.json").read_text(encoding="utf-8"))
RUN2 = json.loads((FIX / "dots-3-note-preview-2026-10-20-rerun.json").read_text(encoding="utf-8"))
BASE = load_fact_base()
GATE = "0 slots errados chegariam a /quote sem confirmacao (ancoragem)"


@pytest.mark.parametrize("run,raw,asks,with_slots,ignored,verdict", [(RUN1, 2, 8, 18, 0, False), (RUN2, 1, 7, 17, 2, True)], ids=["1o smoke", "2o smoke"])
def test_the_two_real_runs_side_by_side(run, raw, asks, with_slots, ignored, verdict):
    """Os numeros do README D7. O gate duro dá 0 nas duas; o erro cru do modelo foi 2 e depois 1. No 2o, o m09 nao extraiu idade (nada a confirmar) e o
    m01 trouxe dois marcadores '?' que o sistema ignorou: nenhum dos dois custa turno extra."""
    s, _ = smoke_rescore.rescore(run)
    a = s["anchoring"]
    assert a["wrong_reach_quote"] == 0 and s["checks"][GATE]
    assert a["raw_model_silent_wrong"] == raw == s["silent_wrong"]
    assert (a["confirmations_asked"], a["messages_with_slots"], a["false_confirmations"], a["extractions_ignored"]) == (asks, with_slots, 0, ignored)
    assert a["confirmations_per_message"] == round(asks / with_slots, 3)
    assert s["passes"] is verdict, "o veredito do 1o smoke segue NAO PASSA por outro criterio (guardrail), o do 2o passa"


def test_the_one_raw_silent_error_left_in_the_second_run_is_m08_and_the_ledger_catches_it():
    s, detail = smoke_rescore.rescore(RUN2)
    m08 = next(d for d in detail if d["msg_id"].startswith("m08") and d["repeat"] == 2)
    (slot,) = m08["slots"]
    assert slot["slot"] == "veiculo_ano" and slot["status"] == "pending" and slot["reason"] == "multiplos_candidatos"
    assert slot["proposed"] == "2016" and slot["question"] == "Só pra confirmar: modelo 2016?" and slot["value"] is None


def test_only_ambiguous_messages_ask_for_confirmation_and_no_clean_message_does():
    for run in (RUN1, RUN2):
        _, detail = smoke_rescore.rescore(run)
        asked = {d["msg_id"][:3] for d in detail if any(s["status"] == "pending" and s["question"] and (s["proposed"] or "Você" in s["question"]) for s in d["slots"])}
        quiet = {d["msg_id"][:3] for d in detail if d["slots"] and all(s["status"] != "pending" for s in d["slots"])}
        assert asked <= {"m06", "m08", "m09", "m15"} and {"m06", "m08", "m15"} <= asked, asked
        assert quiet == {"m02", "m03", "m04", "m05", "m07"}


def test_the_gate_can_fail_negation_is_the_known_limit():
    """O gate nao e decorativo: uma negacao ("o carro NAO e 2015") ancora 2015, que e literal e unico. E o limite conhecido (README D5) e aparece aqui."""
    msg = SmokeMessage("neg", "o carro não é 2015", asked_slot="veiculo_ano", expect_ambiguous=frozenset({"veiculo_ano"}))
    out = TurnOutput((SlotValue("veiculo_ano", "2015", False),), "provide_info", (), "Anotado!")
    s = score_call(msg, LLMResult(out, None, 1.0, None, "stop"), BASE)
    assert s["anchor_wrong"] == ["veiculo_ano"] and s["anchor_pending"] == []


def test_a_clean_message_asking_for_confirmation_is_counted_as_a_false_confirmation():
    msg = SmokeMessage("m", "acho que é 2015", asked_slot="veiculo_ano", expected={"veiculo_ano": "2015"})  # o gabarito diz que e limpa, mas o lead hesitou
    out = TurnOutput((SlotValue("veiculo_ano", "2015", False),), "provide_info", (), "Anotado!")
    s = score_call(msg, LLMResult(out, None, 1.0, None, "stop"), BASE)
    assert s["anchor_false_confirmation"] == ["veiculo_ano"] and s["anchor_wrong"] == []


def test_a_hostile_extraction_never_reaches_the_quote_in_the_smoke_scoring_either():
    msg = SmokeMessage("m", "oi, queria cotar", intents=frozenset({"greeting"}))
    out = TurnOutput((SlotValue("idade", "30", False), SlotValue("veiculo_ano", "2024", False)), "provide_info", (), "Vou cotar!")
    s = score_call(msg, LLMResult(out, None, 1.0, None, "stop"), BASE)
    assert s["anchor_wrong"] == [] and s["anchor_pending"] == [] and set(s["anchor_dropped"]) == {"idade", "veiculo_ano"}
    assert s["silent_wrong"] == 2 and s["anchor_asks"] is False, "o modelo errou; o sistema ignorou os dois, sem nem gastar um turno"


def test_the_tool_writes_an_augmented_copy_and_never_touches_the_original(tmp_path, capsys):
    report = {"model": "m:free", "provider": "openrouter", "calls": RUN2["calls"], "summary": {"passes": False, "marker": "original"}}
    src = tmp_path / "smoke-x.json"
    src.write_text(json.dumps(report), encoding="utf-8")
    before = src.read_bytes()
    assert smoke_rescore.main([str(src)]) == 0
    assert src.read_bytes() == before, "o relatorio original nao muda"
    out = json.loads((tmp_path / "smoke-x-ancorado.json").read_text(encoding="utf-8"))
    assert out["summary_original"]["marker"] == "original" and out["summary"]["anchoring"]["wrong_reach_quote"] == 0 and out["anchoring_detail"]
    assert "GATE DE PRECO (ancoragem)" in capsys.readouterr().out
