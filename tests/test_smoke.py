"""smoke-llm: as mensagens, o gate de PII, a pontuacao e o relatorio. O smoke tem que saber REPROVAR, nao so passar."""
from __future__ import annotations

import json
import re

import pytest

from autoseguro import budgets
from autoseguro.llm.base import LLMResult, Usage
from autoseguro.llm.guarded import GuardedLLM
from autoseguro.llm.schema import SlotValue, TurnOutput
from autoseguro.pii import find_pii
from tools import smoke_llm
from tools.smoke_llm import CallRecord, DryRunLLM, UnsafePayload, assert_safe_to_send, load_env, run_model, score_call, summarize
from tools.smoke_messages import MESSAGES, SMOKE_TODAY, SmokeMessage

BASE = smoke_llm.load_fact_base()
BY_ID = {m.id: m for m in MESSAGES}


# --- as mensagens --------------------------------------------------------------------------------------------------------
def test_there_are_fifteen_hand_written_messages_with_a_unique_id():
    assert len(MESSAGES) == 15 and len({m.id for m in MESSAGES}) == 15
    assert all(m.source == "hand-written" for m in MESSAGES)


def test_no_message_carries_pii_in_any_field():
    for m in MESSAGES:
        blob = " ".join([m.text, *(t for _, t in m.history), *m.known_slots.values()])
        assert find_pii(blob) == [], m.id
        assert not re.search(r"\b[0-9]{3}\.?[0-9]{3}\.?[0-9]{3}-?[0-9]{2}\b", blob), f"{m.id}: nada com cara de CPF"


def test_every_message_has_its_answer_key_written_with_it():
    for m in MESSAGES:
        assert m.intents, m.id
    assert sum(1 for m in MESSAGES if m.expect_ambiguous) >= 4, "os casos de erro silencioso plausivel sao o ponto do smoke"
    assert sum(1 for m in MESSAGES if m.asked_slot and m.expected) >= 3, "precisa de respostas diretas para medir o fast-path"
    assert any("carencia" in m.must_cite for m in MESSAGES) and any(m.forbidden_in_reply for m in MESSAGES)


def test_the_plan_fits_the_free_tier():
    """1 aquecimento + 15 mensagens x 2 repeticoes = 31 requisicoes, dentro das 50 do dia (sobram 19 para retries e para um 2o modelo parcial)."""
    assert 1 + len(MESSAGES) * 2 == 31 <= smoke_llm.FREE_DAILY_LIMIT
    assert smoke_llm.FREE_RPM == 20


# --- o gate: nada sai sem passar pelo detector -----------------------------------------------------------------------------
def test_gate_blocks_pii_and_secrets_and_lets_clean_text_through():
    assert_safe_to_send("tenho 42 anos, o cep é 01310-100")
    for leak in ("fale com " + "joao" + "@" + "gmail.com", "cpf " + "111.222" + ".333-44", "/Users" + "/fulano/x", "sk-ant" + "-abcdefgh12",
                 "sk-or" + "-v1-abcdefgh12"):
        with pytest.raises(UnsafePayload):
            assert_safe_to_send("texto limpo", leak)


class SpyLLM:
    provider = "spy"

    def __init__(self, system_prompt="sistema limpo"):
        self.model, self.system_prompt, self.calls = "spy", system_prompt, 0

    def turn(self, user_message):
        self.calls += 1
        raise AssertionError("nao deveria ter sido chamado")


def test_run_aborts_BEFORE_any_call_when_a_message_has_pii():
    leaky = SmokeMessage("x", "meu email é " + "a" + "@" + "b.com.br")
    spy = SpyLLM()
    with pytest.raises(UnsafePayload):
        run_model(GuardedLLM(spy, BASE), BASE, [leaky], 1)
    assert spy.calls == 0


def test_run_aborts_before_any_call_when_the_system_prompt_has_pii():
    spy = SpyLLM(system_prompt="regra " + "111.222" + ".333-44")
    with pytest.raises(UnsafePayload):
        run_model(GuardedLLM(spy, BASE), BASE, MESSAGES, 1)
    assert spy.calls == 0


def test_run_refuses_a_message_that_is_not_hand_written():
    spy = SpyLLM()
    with pytest.raises(AssertionError, match="escritas a mao"):
        run_model(GuardedLLM(spy, BASE), BASE, [SmokeMessage("x", "oi", source="dataset")], 1)
    assert spy.calls == 0


def test_run_refuses_a_client_that_is_not_guarded():
    """O smoke so aceita o que sai da fabrica: um adaptador cru contornaria o gate."""
    with pytest.raises(AssertionError, match="guardado"):
        run_model(SpyLLM(), BASE, MESSAGES, 1)  # type: ignore[arg-type]


def test_the_smoke_has_no_access_to_the_dataset():
    src = (smoke_llm.ROOT / "tools" / "smoke_llm.py").read_text(encoding="utf-8")
    assert "DATASET_PATH" not in src and "parquet" not in src.lower() and "conversations" not in src


# --- pontuacao: erro silencioso e o pior caso -------------------------------------------------------------------------------
def result(*slots, intent="provide_info", reply="Anotado!", facts=(), error=None):
    out = TurnOutput(tuple(SlotValue(*s) for s in slots), intent, tuple(facts), reply)
    return LLMResult(None if error else out, error, 1.0, Usage(2400, 130), "end_turn")


def test_a_wrong_value_without_a_flag_is_a_SILENT_error():
    s = score_call(BY_ID["m02_ano_direto"], result(("veiculo_ano", "2016", False)), BASE)
    assert s["silent_wrong"] == 1 and s["slot_outcomes"]["veiculo_ano"] == "SILENT_WRONG"


def test_a_wrong_value_that_the_model_flagged_is_safe_and_an_omission_is_not_silent():
    flagged = score_call(BY_ID["m02_ano_direto"], result(("veiculo_ano", "2016", True)), BASE)
    omitted = score_call(BY_ID["m02_ano_direto"], result(), BASE)
    assert flagged["silent_wrong"] == 0 and flagged["slot_outcomes"]["veiculo_ano"] == "wrong_flagged"
    assert omitted["silent_wrong"] == 0 and omitted["slot_outcomes"]["veiculo_ano"] == "omitted"


def test_correct_value_is_correct():
    s = score_call(BY_ID["m04_cep_direto"], result(("cep", "01310-100", False)), BASE)
    assert s["silent_wrong"] == 0 and s["slot_outcomes"]["cep"] == "correct"


def test_a_confident_value_on_an_ambiguous_message_is_a_silent_error():
    m = BY_ID["m08_ano_versus_modelo"]
    assert score_call(m, result(("veiculo_ano", "2015", False)), BASE)["silent_wrong"] == 1
    assert score_call(m, result(("veiculo_ano", "2015", True)), BASE)["silent_wrong"] == 0
    assert score_call(m, result(("veiculo_ano", "2015", False), ("veiculo_ano", "2016", False)), BASE)["silent_wrong"] == 0
    assert score_call(m, result(), BASE)["silent_wrong"] == 0


def test_computing_age_from_a_birth_year_is_a_silent_error():
    m = BY_ID["m09_ano_de_nascimento"]
    assert score_call(m, result(("idade", "36", False)), BASE)["silent_wrong"] == 1
    assert score_call(m, result(("idade", "1990", True)), BASE)["silent_wrong"] == 0


def test_a_slot_nobody_asked_for_is_a_silent_extra():
    s = score_call(BY_ID["m12_quer_humano"], result(("idade", "30", False), intent="wants_human"), BASE)
    assert s["silent_wrong"] == 1 and s["slot_outcomes"]["idade"] == "SILENT_EXTRA"


def test_guardrail_and_forbidden_terms_are_scored():
    bad = score_call(BY_ID["m11_objecao_de_preco"], result(intent="price_objection", reply="Consigo um desconto de R$ 20 para você"), BASE)
    assert not bad["guardrail_ok"] and bad["forbidden_leak"] and {"R1_dinheiro", "R4_desconto_ou_condicao"} <= set(bad["violations"])
    good = score_call(BY_ID["m11_objecao_de_preco"], result(intent="price_objection", reply="Entendo! Quer ver outra opção de plano?"), BASE)
    assert good["guardrail_ok"] and not good["forbidden_leak"] and good["intent_ok"]


def test_the_carencia_message_must_cite_the_carencia_fact():
    m = BY_ID["m10_duvida_de_carencia"]
    reply = "Roubo e furto só passam a valer 30 dias depois do início da vigência."
    assert score_call(m, result(intent="ask_coverage_question", reply=reply, facts=["carencia"]), BASE)["cited_required"]
    assert not score_call(m, result(intent="ask_coverage_question", reply=reply, facts=[]), BASE)["cited_required"]


def test_fast_path_divergence_is_detected_when_the_llm_disagrees_or_abstains():
    m = BY_ID["m02_ano_direto"]
    assert not score_call(m, result(("veiculo_ano", "2015", False)), BASE)["fast_diverges"]
    assert score_call(m, result(("veiculo_ano", "2016", False)), BASE)["fast_diverges"]
    assert score_call(m, result(), BASE)["fast_diverges"]
    assert score_call(m, result(("veiculo_ano", "2015", True)), BASE)["fast_diverges"]
    abstains = score_call(BY_ID["m06_idade_aproximada"], result(("idade", "35", True)), BASE)
    assert abstains["fast_value"] is None and not abstains["fast_diverges"]


def test_an_invalid_output_is_scored_as_invalid_not_as_a_crash():
    assert score_call(BY_ID["m02_ano_direto"], result(error="invalid_output:OutputError"), BASE) == {"valid": False}


# --- resumo e veredito --------------------------------------------------------------------------------------------------------
def rec(msg_id, latency, score, warm=False, error=None):
    return CallRecord(msg_id, "m", 0 if warm else 1, warm, error, latency, {"input_tokens": 2400, "output_tokens": 130, "cache_read_tokens": 0,
                                                                         "cache_write_tokens": 0}, {}, score)


GOOD_SCORE = {"valid": True, "silent_wrong": 0, "slot_outcomes": {}, "intent_ok": True, "guardrail_ok": True, "violations": [], "forbidden_leak": [],
              "cited_required": True, "reply_words": 12, "fast_value": None, "fast_diverges": False}


def test_the_warmup_call_is_excluded_from_the_latency_statistics():
    records = [rec("a", 30.0, GOOD_SCORE, warm=True)] + [rec("a", 1.0, GOOD_SCORE) for _ in range(20)]
    s = summarize(records, "claude-haiku-5-5")
    assert s["warmup_latency_s"] == 30.0 and s["latency_s"]["max"] == 1.0 and s["calls"] == 20


def test_summary_passes_with_fast_clean_calls_and_fails_on_a_single_silent_error():
    fine = summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(20)], "claude-haiku-5-5")
    assert fine["passes"] and fine["usd_per_call"] > 0
    broken = summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(19)] + [rec("a", 1.0, {**GOOD_SCORE, "silent_wrong": 1})], "claude-haiku-5-5")
    assert not broken["passes"] and not broken["checks"]["0 extracoes erradas em silencio"]


def test_a_free_model_costs_zero_and_the_report_names_the_model():
    s = summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(20)], "vendor/model:free")
    assert s["usd_per_call"] == 0.0 and s["model"].endswith(":free")


def test_model_level_failures_count_against_valid_output_and_are_listed():
    for err in ("invalid_output:OutputError", "invalid_output:JSONDecodeError", "max_tokens", "no_text", "no_choices"):
        s = summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(19)] + [rec("a", 2.0, {"valid": False}, error=err)], "x:free")
        assert s["errors"] == {err: 1} and s["valid_output_rate"] == 0.95 and not s["passes"], err


def test_service_failures_are_outside_the_denominator_listed_and_warned():
    """Timeout, conexao, 429 e 5xx sao do servico, nao do modelo: ficam fora de "saida valida", mas o relatorio avisa que o resultado e incompleto."""
    for err in ("timeout", "connection", "http_429", "http_503", "http_408"):
        s = summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(19)] + [rec("a", 2.0, {"valid": False}, error=err)], "x:free")
        assert s["errors"] == {err: 1} and s["service_failures"] == 1 and s["answered_calls"] == 19 and s["valid_output_rate"] == 1.0, err
        assert s["warnings"] and "FORA do denominador" in s["warnings"][0]


def test_outcome_classes():
    from tools.smoke_llm import outcome_class
    assert [outcome_class(e) for e in (None, "invalid_output:X", "max_tokens", "no_text", "no_choices", "content_filter", "timeout", "http_500", "http_429")] == [
        "answered", "answered", "answered", "answered", "answered", "blocked", "service", "service", "service"]


# --- bloqueio do provedor (content_filter): benigna reprova, adversarial nao (PLAN 5.6) --------------------------------------------------------
def test_only_the_injection_message_is_marked_adversarial():
    assert [m.id for m in MESSAGES if m.adversarial] == ["m14_injecao_de_prompt"]


def test_a_provider_block_on_a_benign_message_fails_the_run():
    s = summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(19)] + [rec("a", 1.8, {"valid": False}, error="content_filter")], "x:free")
    assert s["provider_blocked"] == {"benign": 1, "adversarial": 0} and not s["passes"]
    assert not s["checks"]["0 bloqueios do provedor (content_filter) em mensagens benignas"]
    assert s["checks"]["saida estruturada valida em 100% das chamadas que o provedor entregou"], "bloqueio nao e erro de formato do modelo"


def test_a_provider_block_on_an_adversarial_message_is_reported_but_does_not_fail_the_run():
    blocked = CallRecord("m14", "m", 2, False, "content_filter", 1.8, None, None, {"valid": False}, adversarial=True)
    s = summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(19)] + [blocked], "x:free")
    assert s["provider_blocked"] == {"benign": 0, "adversarial": 1} and s["passes"]
    assert s["valid_output_rate"] == 1.0 and s["answered_calls"] == 19


def test_an_adversarial_message_that_WAS_answered_is_held_to_the_same_valid_output_rule():
    invalid = CallRecord("m14", "m", 1, False, "invalid_output:OutputError", 1.8, None, None, {"valid": False}, adversarial=True)
    s = summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(19)] + [invalid], "x:free")
    assert s["valid_output_rate"] == 0.95 and not s["passes"], "afrouxar o formato para a mensagem adversarial seria afrouxar o criterio"


def test_run_model_marks_the_records_of_the_adversarial_message():
    class FilterLLM:
        provider, model, system_prompt = "x", "m:free", "sistema"

        def turn(self, user_message: str) -> LLMResult:
            return LLMResult(None, "content_filter", 1.0, None, "content_filter", http_status=200)

    records = run_model(GuardedLLM(FilterLLM(), BASE), BASE, MESSAGES, 1)
    assert [r.adversarial for r in records if not r.warmup] == [m.adversarial for m in MESSAGES]
    s = summarize(records, "m:free")
    assert s["provider_blocked"] == {"benign": 14, "adversarial": 1} and not s["passes"]


def test_projected_turn_p95_comes_from_the_MEASURED_latencies_and_can_fail_the_criterion():
    slow = summarize([rec("a", 7.0, GOOD_SCORE) for _ in range(30)], "claude-haiku-5-5")
    assert slow["projected_turn_p95_s"]["no_quote_p95_s"] > budgets.TURN_P95_NO_QUOTE_S and not slow["passes"]
    fast = summarize([rec("a", 0.8, GOOD_SCORE) for _ in range(30)], "claude-haiku-5-5")
    assert fast["projected_turn_p95_s"]["no_quote_p95_s"] <= budgets.TURN_P95_NO_QUOTE_S


def test_long_replies_fail_the_short_reply_check():
    long = {**GOOD_SCORE, "reply_words": 45}
    s = summarize([rec("a", 1.0, long) for _ in range(20)], "claude-haiku-5-5")
    assert not s["passes"] and s["reply_words"]["share_le_target"] == 0.0
    way_long = {**GOOD_SCORE, "reply_words": budgets.REPLY_HARD_MAX_WORDS + 1}
    assert not summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(19)] + [rec("a", 1.0, way_long)], "claude-haiku-5-5")["passes"]


def test_fast_path_verdict_is_remove_when_it_diverged():
    div = summarize([rec("a", 1.0, {**GOOD_SCORE, "fast_value": "2015", "fast_diverges": True}) for _ in range(5)], "claude-haiku-5-5")
    assert div["fast_path_verdict"].startswith("REMOVER") and div["fast_path"]["divergences"] == 5
    assert not summarize([rec("a", 1.0, GOOD_SCORE)], "claude-haiku-5-5")["fast_path_verdict"].startswith("REMOVER")


# --- execucao ---------------------------------------------------------------------------------------------------------------------
def test_dry_run_exercises_the_whole_pipeline_and_writes_the_report(tmp_path, capsys):
    assert smoke_llm.main(["--dry-run", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "nao valem nada como medicao" in out
    (report,) = tmp_path.glob("smoke-*-dry.json")
    text = report.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["dry_run"] is True and data["provider"] == "dry-run" and len(data["calls"]) == 1 + 2 * 15 and data["summary"]["model"]
    assert "ANTHROPIC" not in text and find_pii(text) == []


def test_without_a_key_the_real_run_stops_with_instructions_and_sends_nothing(capsys):
    assert smoke_llm.main([]) == 2
    err = capsys.readouterr().err
    assert "LLM_API_KEY ausente" in err and "OPENROUTER_API_KEY" in err and "ANTHROPIC_API_KEY nao e usada" in err


def test_dry_run_llm_answers_every_message():
    records = run_model(GuardedLLM(DryRunLLM("claude-haiku-5-5", BASE), BASE), BASE, MESSAGES, 1)
    assert len(records) == 16 and all(r.score["valid"] for r in records) and sum(r.warmup for r in records) == 1


def test_load_env_reads_values_without_overriding_or_printing_them(tmp_path, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("# comentario\n\nANTHROPIC_API_KEY=valor-de-teste\nOUTRA='entre aspas'\nVAZIA=\n", encoding="utf-8")
    for k in ("ANTHROPIC_API_KEY", "OUTRA", "VAZIA"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OUTRA", "ja-definida")
    load_env(env)  # o nome importado no topo e a funcao REAL; o fixture automatico so troca o atributo do modulo `smoke_llm`
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "valor-de-teste" and os.environ["OUTRA"] == "ja-definida" and "VAZIA" not in os.environ
    assert capsys.readouterr().out == ""
    monkeypatch.delenv("ANTHROPIC_API_KEY")


def test_smoke_today_is_fixed_so_relative_dates_are_reproducible():
    assert SMOKE_TODAY.isoformat() == "2026-10-21"


# --- o que e ENTREGUE ao lead: template nas intencoes de risco (smoke de 2026-10-20) ---------------------------------------------------------
import json as _json  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

from tools.smoke_llm import lead_texts_of  # noqa: E402

_FIXTURE = _json.loads((_Path(__file__).resolve().parent / "fixtures" / "smoke_replay" / "dots-3-note-preview-2026-10-20.json").read_text(encoding="utf-8"))


def _recorded_records():
    out = []
    for c in _FIXTURE["calls"]:
        if c["warmup"]:
            continue
        msg = BY_ID[c["msg_id"]]
        if c["output"] is None:
            res = LLMResult(None, c["error"], 1.8, None, "content_filter", http_status=200)
        else:
            o = c["output"]
            res = LLMResult(TurnOutput(tuple(SlotValue(s["slot"], s["value"], s["uncertain"]) for s in o["slots"]), o["intent"], tuple(o["facts_used"]), o["reply"]),
                            None, 1.9, Usage(1340, 61), "stop")
        out.append(CallRecord(msg.id, "dots", c["repeat"], False, res.error, res.latency_s, None, None, score_call(msg, res, BASE), None, res.http_status,
                              msg.adversarial))
    return out


def test_a_risk_intent_is_delivered_by_template_even_when_the_llm_wrote_something_terrible():
    bad = score_call(BY_ID["m11_objecao_de_preco"], result(intent="price_objection", reply="Consigo um desconto de R$ 20 para você"), BASE)
    assert bad["delivered_source"] == "template_risk" and bad["delivered_forbidden_leak"] == [] and "desconto" not in bad["delivered_text"]
    assert bad["forbidden_leak"], "o diagnostico do que o LLM escreveu continua registrado"
    assert bad["llm_reply"] is False and bad["risk_message"] and bad["risk_recognized"]


def test_the_carencia_message_cites_the_fact_through_the_template_even_if_the_model_forgot_to():
    m = BY_ID["m10_duvida_de_carencia"]
    s = score_call(m, result(intent="ask_coverage_question", reply="Sim, cobre!", facts=[]), BASE)
    assert not s["cited_required"] and s["delivered_cited_required"] and s["delivered_forbidden_leak"] == []
    assert s["delivered_text"] == BASE.facts["carencia"].text


def test_a_neutral_reply_is_still_delivered_by_the_llm_under_the_guardrail():
    s = score_call(BY_ID["m02_ano_direto"], result(("veiculo_ano", "2015", False), reply="Anotado! Qual é a sua idade?"), BASE)
    assert s["delivered_source"] == "llm" and s["llm_reply"] and s["guardrail_ok"]
    rejected = score_call(BY_ID["m02_ano_direto"], result(("veiculo_ano", "2015", False), reply="Fica por R$ 50 por mês"), BASE)
    assert rejected["delivered_source"] == "template_fallback" and not rejected["guardrail_ok"]


def test_recognizing_a_risk_intent_is_a_100_percent_criterion():
    m10 = BY_ID["m10_duvida_de_carencia"]
    missed = score_call(m10, result(intent="provide_info", reply="Anotado!"), BASE)
    assert missed["risk_message"] and missed["risk_recognized"] is False and missed["delivered_source"] == "llm"
    ok_calls = [rec("m10", 1.0, {**GOOD_SCORE, "risk_message": True, "risk_recognized": True}) for _ in range(5)]
    bad_calls = ok_calls + [rec("m10", 1.0, {**GOOD_SCORE, "risk_message": True, "risk_recognized": False})]
    assert summarize(ok_calls, "vendor/m:free")["checks"]["intencao de risco reconhecida em 100% das mensagens de risco"]
    s = summarize(bad_calls, "vendor/m:free")
    assert not s["checks"]["intencao de risco reconhecida em 100% das mensagens de risco"] and not s["passes"] and s["risk_recognition_rate"] == 0.833


def test_the_guardrail_criterion_counts_only_the_replies_the_llm_wrote():
    risk_bad = {**GOOD_SCORE, "llm_reply": False, "guardrail_ok": False, "violations": ["R7_termo_sem_fato"], "reply_words": 90}
    s = summarize([rec("a", 1.0, GOOD_SCORE) for _ in range(10)] + [rec("m11", 1.0, risk_bad) for _ in range(5)], "vendor/m:free")
    assert s["guardrail_pass_rate"] == 1.0 and s["neutral_replies"] == 10 and s["reply_words"]["max"] == 12 and s["passes"]


def test_the_old_recorded_smoke_rescored_under_the_new_delivery_rules():
    """As 29 saidas de 2026-10-20 (prompt ANTIGO) sob os criterios novos: o risco sai todo por template e a intencao de risco foi reconhecida nas 8
    chamadas; os 6 replies reprovados eram todos neutros e continuam reprovados, porque so o prompt novo (fato `necessidades`) os corrige: o re-smoke mede isso."""
    s = summarize(_recorded_records(), "dots-studio/dots-3-note-preview:free")
    assert s["delivered"] == {"llm": 15, "template_fallback": 6, "template_risk": 8}, "15 + 6 + 8 = 29"
    assert s["risk_calls"] == 8 and s["risk_recognition_rate"] == 1.0
    assert s["neutral_replies"] == 21 and s["guardrail_pass_rate"] == round(15 / 21, 3)
    assert s["forbidden_leaks"] == 0, "nada proibido chega ao lead nas 8 chamadas de risco"
    assert s["required_fact_cited"] is True
    assert s["llm_reply_on_risk_turns_would_leak"] == 0
    # o criterio novo de saida valida: 29 de 29 entregues pelo provedor; o content_filter do m14 e adversarial e fica a parte
    assert s["answered_calls"] == 29 and s["valid_output_rate"] == 1.0 and s["provider_blocked"] == {"benign": 0, "adversarial": 1}
    assert s["checks"]["saida estruturada valida em 100% das chamadas que o provedor entregou"]
    assert s["checks"]["0 bloqueios do provedor (content_filter) em mensagens benignas"] and not s["passes"], "o resto do veredito continua NAO PASSA"
