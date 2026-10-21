"""O gate de PII e o guardrail ficam ACIMA do provedor: trocar de provedor nao contorna nenhum dos dois.

Cada teste roda contra os DOIS adaptadores (Anthropic e OpenRouter), ambos atras da fabrica, cada um com seu servidor local falso.
Se algum dia um adaptador passar a ter uma rota que ignora o guarda, o teste correspondente reprova.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from autoseguro.facts import FactBase
from autoseguro.llm.base import LLMResult
from autoseguro.llm.config import LLMConfig
from autoseguro.llm.factory import make_adapter, make_llm
from autoseguro.llm.guarded import GuardedLLM, GuardedResult, UnsafePayload
from autoseguro.llm.throttle import QuotaLog, RateLimiter, ThrottledLLM
from tests.fake_servers import CANARY_KEY, GOOD, FakeServer, anthropic_json, chat_json

anthropic = pytest.importorskip("anthropic", reason="SDK opcional da Anthropic ausente (pip install -e '.[llm]'): o nucleo roda sem ele")

ROOT = Path(__file__).resolve().parent.parent
BASE = FactBase.from_planos(json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8")))
ANTHROPIC_TEST_KEY = "chave-anthropic-de-teste-0000"
PROVIDERS = ["anthropic", "openrouter"]


def envelope(provider: str, text: str) -> dict:
    return anthropic_json(text) if provider == "anthropic" else chat_json(text)


def config(provider: str, url: str, **over) -> LLMConfig:
    if provider == "anthropic":
        base = dict(provider="anthropic", model="claude-haiku-5-5", base_url=url, api_key=ANTHROPIC_TEST_KEY, max_tokens=600, timeout_s=3.0)
    else:
        base = dict(provider="openrouter", model="vendor/model:free", base_url=url, api_key=CANARY_KEY, reasoning_effort="none", timeout_s=3.0)
    base.update(over)
    return LLMConfig(**base)


@pytest.fixture(params=PROVIDERS)
def stack(request):
    """(provider, servidor falso, cliente guardado) para cada adaptador."""
    provider = request.param
    server = FakeServer()
    server.reply(200, envelope(provider, json.dumps(GOOD)))
    llm = make_llm(config(provider, server.url), BASE)
    yield provider, server, llm
    server.close()


def say(provider: str, server: FakeServer, reply: str, facts=(), slots=(), intent="provide_info") -> None:
    """O 'modelo' passa a responder com este reply, no envelope do provedor."""
    server.reply(200, envelope(provider, json.dumps({"slots": list(slots), "intent": intent, "facts_used": list(facts), "reply": reply})))


# --- a fabrica so entrega clientes guardados --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("provider", PROVIDERS)
def test_the_factory_always_returns_a_guarded_client(provider):
    server = FakeServer()
    try:
        llm = make_llm(config(provider, server.url), BASE)
        assert isinstance(llm, GuardedLLM) and llm.provider == provider
        assert not isinstance(make_adapter(config(provider, server.url), BASE), GuardedLLM), "o adaptador cru nao carrega o guarda"
    finally:
        server.close()


def test_every_provider_the_config_accepts_is_guarded():
    server = FakeServer()
    try:
        for cfg in (config("anthropic", server.url), config("openrouter", server.url),
                    LLMConfig(provider="openai_compat", model="acme/m1", base_url=server.url, api_key=CANARY_KEY, structured_output="none")):
            assert isinstance(make_llm(cfg, BASE), GuardedLLM), cfg.provider
    finally:
        server.close()


def test_a_throttling_wrapper_goes_between_the_adapter_and_the_guard_never_outside_it(tmp_path):
    server = FakeServer()
    server.reply(200, chat_json(json.dumps(GOOD)))
    try:
        waits = []
        quota = QuotaLog(tmp_path / "q.jsonl", 50)
        llm = make_llm(config("openrouter", server.url), BASE,
                       wrap=lambda a: ThrottledLLM(a, limiter=RateLimiter(20, clock=lambda: 0.0, sleep=waits.append), quota=quota))
        assert isinstance(llm, GuardedLLM) and isinstance(llm.inner, ThrottledLLM)
        with pytest.raises(UnsafePayload):
            llm.turn("meu email é " + "a" + "@" + "b.com.br")
        assert server.requests == [] and quota.used_today() == 0 and waits == [], "payload barrado nao gasta cota nem espera de rpm"
    finally:
        server.close()


# --- (a) gate de PII: nada sai da maquina, em NENHUM adaptador ---------------------------------------------------------------------------
LEAKS = {"email": "meu email é " + "joao" + "@" + "gmail.com", "cpf": "cpf " + "111.222" + ".333-44",
         "caminho": "arquivo em /Users" + "/fulano/x", "chave_openrouter": "usa a chave sk-or" + "-v1-abcdefgh12345678", "chave_anthropic": "sk-ant" + "-abcdefgh12345678"}


@pytest.mark.parametrize("leak", sorted(LEAKS))
def test_pii_or_a_secret_in_the_user_message_is_blocked_before_any_request(stack, leak):
    provider, server, llm = stack
    with pytest.raises(UnsafePayload):
        llm.turn(LEAKS[leak])
    assert server.requests == [], f"{provider}: o payload com {leak} chegou ao servidor"


def test_negative_control_a_raw_adapter_WOULD_send_the_pii(stack):
    """Sem o guarda, o payload com PII sai. E por isso que o guarda tem que estar ACIMA do provedor, em qualquer adaptador."""
    provider, server, llm = stack
    raw = llm.inner
    raw.turn(LEAKS["email"])
    assert len(server.requests) == 1, f"{provider}: o controle negativo falhou, entao o teste acima poderia estar verde por nada"


def test_pii_in_the_system_prompt_is_blocked_before_any_request(stack):
    provider, server, llm = stack
    llm.inner.system_prompt = llm.inner.system_prompt + " " + LEAKS["email"]
    with pytest.raises(UnsafePayload):
        llm.turn("oi")
    assert server.requests == [], provider


def test_clean_text_does_pass_so_the_gate_is_not_just_a_wall(stack):
    provider, server, llm = stack
    assert llm.turn("tenho 42 anos, o cep é 01310-100").result.output is not None
    assert len(server.requests) == 1


# --- (b) guardrail: o MESMO veredito para o mesmo texto, qualquer adaptador ---------------------------------------------------------------------
def test_money_in_the_reply_is_flagged(stack):
    provider, server, llm = stack
    say(provider, server, "A mensalidade fica R$ 150,00")
    g = llm.turn("quanto custa?")
    assert isinstance(g, GuardedResult) and g.output is not None and not g.reply_ok and g.reply_source == "template_fallback"
    assert "R1_dinheiro" in {v.rule for v in g.violations}


def test_a_coverage_claim_without_a_cited_fact_is_flagged(stack):
    provider, server, llm = stack
    say(provider, server, "O plano Completo cobre vidros.")
    assert "R7_termo_sem_fato" in {v.rule for v in llm.turn("e o completo?").violations}


def test_the_same_claim_with_the_fact_cited_passes(stack):
    provider, server, llm = stack
    say(provider, server, "O plano Completo cobre vidros.", facts=["plano:completo"])
    g = llm.turn("e o completo?")
    assert g.reply_ok and g.reply_source == "llm"


def test_a_cited_fact_that_does_not_exist_is_flagged(stack):
    provider, server, llm = stack
    say(provider, server, "Oi!", facts=["fato:inexistente"])
    assert "R7_fato_inexistente" in {v.rule for v in llm.turn("oi").violations}


def test_numbers_may_only_echo_what_the_lead_wrote(stack):
    provider, server, llm = stack
    say(provider, server, "Anotei 42 anos.")
    assert "R2_numero_nao_permitido" in {v.rule for v in llm.turn("oi").violations}
    assert llm.turn("tenho 42", lead_texts=["tenho 42"]).reply_ok


def test_a_promise_of_discount_or_deadline_is_flagged(stack):
    provider, server, llm = stack
    say(provider, server, "Consigo um desconto e um consultor te liga amanhã")
    assert {"R4_desconto_ou_condicao", "R3_prazo_ou_contato"} <= {v.rule for v in llm.turn("caro").violations}


# --- (c) validacao local do formato: o provedor nao e confiavel -----------------------------------------------------------------------------------
@pytest.mark.parametrize("content,error", [
    ("nao e json", "invalid_output:JSONDecodeError"),
    (json.dumps({**GOOD, "intent": "inventado"}), "invalid_output:OutputError"),
    (json.dumps({**GOOD, "extra": 1}), "invalid_output:OutputError"),
])
def test_output_outside_the_local_schema_never_becomes_data_in_any_adapter(stack, content, error):
    provider, server, llm = stack
    server.reply(200, envelope(provider, content))
    g = llm.turn("oi")
    assert g.output is None and g.result.error == error and not g.reply_ok and g.reply_source == "template_fallback"


# --- (d) o veredito e identico entre provedores ------------------------------------------------------------------------------------------------
REPLIES = [("Oi! Qual o ano do carro?", []), ("Sai por R$ 80", []), ("O plano Premium cobre vidros.", ["plano:premium"]), ("O Essencial cobre vidros.", ["plano:essencial"]),
           ("Um consultor te liga amanhã", []), ("Garantimos tudo, sem carência", ["carencia"])]


def test_both_adapters_reach_the_same_verdict_on_the_same_model_output():
    verdicts: dict[str, list] = {}
    for provider in PROVIDERS:
        server = FakeServer()
        try:
            llm = make_llm(config(provider, server.url), BASE)
            out = []
            for reply, facts in REPLIES:
                say(provider, server, reply, facts)
                g = llm.turn("oi")
                out.append((g.reply_ok, sorted(v.rule for v in g.violations)))
            verdicts[provider] = out
        finally:
            server.close()
    assert verdicts["anthropic"] == verdicts["openrouter"], "trocar de provedor mudou o veredito do guardrail"
    assert [ok for ok, _ in verdicts["openrouter"]] == [True, False, True, False, False, False]


# --- estrutura: nenhum modulo do produto monta um adaptador fora da fabrica ---------------------------------------------------------------------
def test_no_product_module_builds_an_adapter_outside_the_factory():
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if rel not in ("src/autoseguro/llm/factory.py",) and any(f"{name}(" in text for name in ("OpenAICompatLLM", "ClaudeLLM")):
            if not rel.endswith(("llm/openai_compat.py", "llm/claude.py")):  # so a propria definicao
                offenders.append(rel)
    assert offenders == [], f"fora da fabrica: {offenders}"


def test_adapters_contain_no_pii_gate_or_guardrail_of_their_own():
    """A protecao e UMA so, acima do provedor: um adaptador que tivesse a propria copia poderia divergir dela."""
    for name in ("claude.py", "openai_compat.py"):
        text = (ROOT / "src" / "autoseguro" / "llm" / name).read_text(encoding="utf-8")
        assert "find_pii" not in text and "check_reply" not in text and "assert_safe_to_send" not in text, name


def test_llm_result_is_provider_neutral():
    r = LLMResult(None, "timeout", 1.0, None, None)
    assert {"output", "error", "latency_s", "usage", "stop_reason", "served_model", "quota_kind"} <= set(r.__dataclass_fields__)
