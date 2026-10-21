"""Os evals: a suite sintetica passa, o carregador do dataset so le colunas que nao vazam o gabarito, a selecao e deterministica e, principalmente, os CRITERIOS TEM DENTES:
cada um reprova diante do defeito que existe para pegar (sem isso, '100%' nao prova nada)."""
from __future__ import annotations

from datetime import date

import pytest

from autoseguro import templates
from autoseguro.handoff import HandoffReason
from autoseguro.orchestrator import Orchestrator
from evals import criteria, dataset, report, scenarios
from evals.runner import Backend, Result, run_conversation
from evals.suite import evaluate, run_dataset, run_synthetic
from tests import synthetic_pii

TODAY = date(2026, 10, 21)
LEAK_COLUMNS = {"conversation_outcome", "lead_idade_informada", "veiculo_texto"}


@pytest.fixture(scope="module")
def backend() -> Backend:
    return Backend.offline(TODAY)


@pytest.fixture(scope="module")
def synthetic(backend):
    return run_synthetic(backend)


def result(**over) -> Result:
    base = dict(id="x", source="synthetic", status="open", reason=None, component=None, detail=None, turns=1, terminal_per_turn=[1], agent=[], lead=[], quotes=[], slots={},
                package=None, stored_text="")
    base.update(over)
    return Result(**base)


# --- a suite sintetica ------------------------------------------------------------------------------------------------------------------------------
def test_the_synthetic_suite_passes_every_criterion(backend, synthetic):
    specs, results = synthetic
    checks = [criteria.price_check(results, backend), criteria.synthetic_check(results, specs), criteria.refusal_check(results, backend),
              criteria.terminal_check(results), criteria.pii_check(results)]
    for c in checks:
        assert c.passed, (c.id, c.failures[:5])
    assert {c.id: c.ratio for c in checks}["C2"] == f"{len(specs)}/{len(specs)}"


def test_every_handoff_reason_has_a_synthetic_scenario(synthetic):
    specs, _ = synthetic
    assert {s.expect_reason for s in specs if s.expect_reason} == {r.value for r in HandoffReason}


@pytest.mark.parametrize("today", [date(2026, 10, 21), date(2027, 1, 1), date(2028, 12, 31), date(2030, 6, 15)])
def test_the_synthetic_scenarios_are_relative_to_the_date_so_they_hold_on_any_day(today):
    b = Backend.offline(today)
    specs, results = run_synthetic(b)
    check = criteria.synthetic_check(results, specs)
    assert check.passed, (today, check.failures)


# --- o dataset: sem gabarito -------------------------------------------------------------------------------------------------------------------------
def fake_rows(*rows):
    seen = {}

    def read(path, columns):
        seen["columns"] = list(columns)
        return [{c: r[c] for c in columns} for r in rows]
    return read, seen


def test_the_dataset_loader_asks_only_for_columns_that_do_not_leak_the_answer_key():
    rows = [dict(conversation_id="c1", message_index=1, sender_role="lead", message_type="text", message_body="B", conversation_outcome="ganho",
                 lead_idade_informada=35, veiculo_texto="Corolla 2008")]
    read, seen = fake_rows(*rows)
    dataset.load_conversations("x.parquet", read_rows=read)
    assert seen["columns"] == dataset.LEAD_COLUMNS and not (set(seen["columns"]) & LEAK_COLUMNS)


def test_the_loader_keeps_only_lead_messages_in_order_per_conversation():
    base = dict(message_type="text")
    read, _ = fake_rows(dict(conversation_id="c2", message_index=0, sender_role="lead", message_body="z", **base),
                        dict(conversation_id="c1", message_index=2, sender_role="lead", message_body="b", **base),
                        dict(conversation_id="c1", message_index=1, sender_role="vendedor", message_body="PRECO", **base),
                        dict(conversation_id="c1", message_index=0, sender_role="lead", message_body="a", **base))
    assert dataset.load_conversations("x", read_rows=read) == {"c1": ["a", "b"], "c2": ["z"]}


def test_the_sample_is_deterministic_spread_across_agent_outcomes_and_independent_of_input_order():
    classes = {f"c{i:04d}": ("quoted" if i % 10 else "refused") for i in range(300)} | {f"h{i}": "handoff:READY_TO_CLOSE" for i in range(3)}
    a = dataset.select(classes, 30, 1)
    b = dataset.select(dict(reversed(list(classes.items()))), 30, 1)
    assert a == b and len(a) == 30 and dataset.select(classes, 30, 2) != a
    assert {classes[c] for c in a} == {"quoted", "refused", "handoff:READY_TO_CLOSE"} and sum(classes[c] == "handoff:READY_TO_CLOSE" for c in a) == 3, "a classe pequena nao some"


def test_a_tiny_population_runs_end_to_end_masks_the_pii_and_passes_the_criteria(backend):
    v = synthetic_pii.values()
    convs = {"c1": ["oi, queria cotar o seguro do meu carro", f"é um onix {TODAY.year - 5}", f"meu cpf é {v['cpf']}, tenho 40 anos, cep 01310-100, email {v['email']}", "ok", "quero fechar"],
             "c2": ["[audio] mensagem de voz (8s)", f"fusca {TODAY.year - 30}, 50 anos, cep 01310100"],
             "c3": ["[documento] documento_do_carro.pdf", "[imagem] foto do carro", "[audio] outra mensagem"]}
    results = run_dataset(backend, convs)
    assert {r.id: r.klass for r in results} == {"c1": "handoff:READY_TO_CLOSE", "c2": "refused", "c3": "handoff:MEDIA_UNREADABLE"}
    assert results[0].scripted == 2, "cobertura e data: o roteiro do vendedor nao as pergunta"
    assert any(q["status"] == "ok" for q in results[0].quotes), "a conversa chegou a uma cotacao antes de o lead pedir para fechar"
    assert v["cpf"] not in results[0].stored_text and v["email"] not in results[0].stored_text and "[CPF]" in results[0].lead[2]["text"]
    for check in (criteria.price_check(results, backend), criteria.refusal_check(results, backend), criteria.terminal_check(results), criteria.pii_check(results)):
        assert check.passed, (check.id, check.failures)


# --- os criterios tem dentes ----------------------------------------------------------------------------------------------------------------------------
def test_c1_catches_a_price_the_service_did_not_return():
    r = result(agent=[{"kind": "text", "text": "Fica só R$ 99,90 por mês.", "quote_id": None, "meta": {}}])
    c = criteria.price_check([r], Backend.offline(TODAY))
    assert not c.passed and "R$ 99,90" in c.failures[0]


def test_c1_catches_a_stored_price_that_differs_from_what_the_service_returns_for_the_same_input():
    import json
    payload = {"plano_id": "essencial", "idade": 34, "veiculo_ano": TODAY.year - 5, "cep": "30130010"}
    status, body = Backend.offline(TODAY).oracle(payload)
    assert status == 200
    stale = dict(body, premio_mensal=body["premio_mensal"] + 10)
    row = dict(id="q1", kind="quote", status="ok", request=json.dumps(payload), response=json.dumps(stale), premio_mensal=stale["premio_mensal"])
    c = criteria.price_check([result(quotes=[row])], Backend.offline(TODAY))
    assert not c.passed and "difere" in c.failures[0]


def test_c3_catches_a_refusal_the_service_does_not_make_and_a_quote_the_service_refuses_and_a_refusal_without_a_registered_one():
    import json
    b = Backend.offline(TODAY)
    fine = {"plano_id": "essencial", "idade": 40, "veiculo_ano": TODAY.year - 5}
    old = {"plano_id": "essencial", "idade": 40, "veiculo_ano": TODAY.year - 30}
    refusal = lambda qid: {"kind": "refusal", "text": "Não consigo cotar este perfil", "quote_id": qid, "meta": {"refusal_kind": "vehicle_too_old"}}  # noqa: E731
    row = lambda qid, payload, status: dict(id=qid, kind="quote", status=status, request=json.dumps(payload), response="{}", premio_mensal=None)  # noqa: E731
    wrong_refusal = result(id="a", agent=[refusal("q1")], quotes=[row("q1", fine, "refused")])
    wrong_quote = result(id="b", agent=[{"kind": "quote", "text": "x", "quote_id": "q2", "meta": {}}], quotes=[row("q2", old, "ok")])
    unregistered = result(id="c", agent=[refusal(None)])
    c = criteria.refusal_check([wrong_refusal, wrong_quote, unregistered], b)
    assert not c.passed and len(c.failures) == 3
    assert any("NÃO recusa" in f for f in c.failures) and any("COTOU" in f for f in c.failures) and any("sem uma recusa registrada" in f for f in c.failures)


def test_c3_catches_a_refusal_with_the_wrong_reason_and_one_that_leaks_the_raw_api_text():
    import json
    b = Backend.offline(TODAY)
    old = {"plano_id": "essencial", "idade": 40, "veiculo_ano": TODAY.year - 30}
    row = dict(id="q1", kind="precheck", status="refused", request=json.dumps(old), response="{}", premio_mensal=None)
    wrong = result(id="a", agent=[{"kind": "refusal", "text": "ok", "quote_id": "q1", "meta": {"refusal_kind": "age_above_limit"}}], quotes=[row])
    raw = result(id="b", agent=[{"kind": "refusal", "text": "Veiculo com mais de 20 anos nao e aceito.", "quote_id": "q1", "meta": {"refusal_kind": "vehicle_too_old"}}], quotes=[row])
    c = criteria.refusal_check([wrong, raw], b)
    assert not c.passed and any("razão dita" in f for f in c.failures) and any("texto cru" in f for f in c.failures)


def test_c2_catches_a_wrong_reason_a_wrong_component_a_missing_package_and_a_reason_without_scenario(backend):
    spec = scenarios.Synthetic("s", ("oi",), "handoff", "COMPLAINT")
    for bad in (result(id="s", status="handoff", reason="CANCELLATION", package={"reason": "CANCELLATION"}),
                result(id="s", status="handoff", reason="COMPLAINT", component="llm", package={"reason": "COMPLAINT"}),
                result(id="s", status="handoff", reason="COMPLAINT", package=None),
                result(id="s", status="open")):
        c = criteria.synthetic_check([bad], [spec])
        assert not c.passed, bad
    ok = criteria.synthetic_check([result(id="s", status="handoff", reason="COMPLAINT", package={"reason": "COMPLAINT"})], [spec])
    assert any("sem cenário sintético" in f for f in ok.failures) and not any(f.startswith("s:") for f in ok.failures)


def test_c4_catches_silence_and_double_answers():
    assert not criteria.terminal_check([result(terminal_per_turn=[1, 0])]).passed
    assert not criteria.terminal_check([result(terminal_per_turn=[2])]).passed
    assert criteria.terminal_check([result(terminal_per_turn=[1, 1])]).passed


def test_c5_catches_pii_in_the_stored_text_including_a_valid_cpf_without_punctuation():
    v = synthetic_pii.values()
    for leaked in (f"cel {v['tel_plus']}", f"mail {v['email']}", f"cpf {v['cpf_digits']}", f"cpf {v['cpf']}", f"placa {v['placa_mercosul']}"):
        assert not criteria.pii_check([result(stored_text=leaked)]).passed, leaked
    assert criteria.pii_check([result(stored_text="cep 01310-100, 34 anos, modelo 2019")]).passed


# --- mutacao de ponta a ponta: um defeito real no produto reprova o eval ---------------------------------------------------------------------------------------
def test_mutation_an_invented_discount_line_in_the_quote_message_is_caught_by_c1(backend, monkeypatch):
    real = templates.render_quote
    monkeypatch.setattr(templates, "render_quote", lambda *a, **k: real(*a, **k) + "\n• Desconto à vista: R$ 10,00")
    monkeypatch.setattr(Orchestrator, "_assert_prices", staticmethod(lambda text, q: None))   # tira a rede interna: o eval tem que pegar sozinho
    r = run_conversation(backend, "m1", scenarios.build(TODAY)[0].lines)
    assert r.status == "quoted"
    c = criteria.price_check([r], backend)
    assert not c.passed and "R$ 10,00" in c.failures[0]


def test_mutation_the_oracle_is_independent_of_the_service_the_agent_talked_to(backend):
    """O defeito grave: recusar quem a API aceita. Aqui o servico que o AGENTE consulta mente (422 para tudo) e confirma a recusa; o eval ainda reprova, porque cada decisao e
    refeita no servico de verdade (o oraculo) com a mesma entrada."""
    class Liar:
        def __init__(self, real):
            self.real = real
            self.today = real.today

        def respond(self, payload):
            return 422, {"error": "cotacao_recusada", "motivo": "Veiculo com mais de 20 anos nao e aceito."}

        def __getattr__(self, name):
            return getattr(self.real, name)

    from evals import runner
    real_transport = runner.VendoredTransport

    class LyingTransport(real_transport):
        def __init__(self, today):
            super().__init__(today)
            self.service = Liar(self.service)

    lying = Backend(backend.label, backend.today, backend.planos, backend.oracle, lambda: LyingTransport(backend.today))
    r = run_conversation(lying, "m2", scenarios.build(TODAY)[0].lines)
    assert r.status == "refused"
    assert not criteria.refusal_check([r], backend).passed, "o oraculo (o servico de verdade) discorda da recusa que o agente disse"


def test_the_report_has_no_message_text_from_the_dataset_only_ids_and_aggregates(backend):
    convs = {"conv_x": ["oi, queria cotar um seguro com muito texto que nao pode vazar", f"é um onix {TODAY.year - 5}, 34 anos, cep 01310-100"]}
    out = evaluate_with(backend, convs)
    text = report.markdown(backend_label=backend.label, today="2026-10-21", seed=1, checks=out["checks"], synthetic=out["specs"], synth_results=out["synth"], dataset=out["dataset"],
                           sample=out["sample"])
    assert "conv_x" in text and "muito texto que nao pode vazar" not in text and "onix" not in text.split("## Cenários sintéticos")[0]


def evaluate_with(backend, convs):
    from evals import report as rep
    specs, synth = run_synthetic(backend)
    ds = run_dataset(backend, convs)
    checks = [criteria.price_check(synth + ds, backend), criteria.synthetic_check(synth, specs), criteria.refusal_check(synth + ds, backend),
              criteria.terminal_check(synth + ds), criteria.pii_check(synth + ds)]
    info = {"conversations": len(ds), "lead_messages": sum(len(v) for v in convs.values()), "seconds": 0.1, "with_media": 0, "with_pii": 0, "scripted_answers": 0,
            "reached_quote": 0, "distribution": rep.distribution(ds)}
    return {"specs": specs, "synth": synth, "dataset": info, "sample": ds, "checks": checks}
