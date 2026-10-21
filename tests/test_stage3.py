"""Etapa 3: pre-checagem com confirmacao da API, midia sem transcricao, reclamacao, cancelamento, sinistro, conversa que nao avanca e fora de escopo.

Cada cenario roda pelo orquestrador de producao (MockLLM + GuardedLLM + QuoteGate + SQLite em memoria), com o transporte falso de relogio virtual."""
from __future__ import annotations

import json

import pytest

from autoseguro import templates
from autoseguro.guardrail import check_reply
from autoseguro.handoff import HandoffReason
from autoseguro.store import money_in
from tests.fakes import err5xx, ok, refused
from tests.test_orchestrator import BASE, DATA, GREET, HAPPY, NEED_BASIC, START, Harness, ess, only_one_terminal_per_turn

OLD_CAR = "é um fusca 1998, tenho 45 anos e moro no cep 01310-100"
NO_RAW_API_TEXT = ("aceitacao", "faixas aceitas", "Veiculo com")


def package(h):
    return json.loads(h.conv["handoff_package"])


def metas(h):
    return [h.meta(m) for m in h.agent]


# --- pre-checagem: a recusa e antecipada, e quem a diz e a API ------------------------------------------------------------------------------------
def test_the_refusal_is_anticipated_as_soon_as_age_and_year_are_verified_and_the_api_confirms_it_first():
    """O cenario 2 da 2b: o lead respondia CEP, cobertura e data antes de ouvir que o carro nao e aceito. Agora a recusa sai no turno em que idade e ano ficam verificados."""
    h = Harness(refused("Veiculo com mais de 20 anos nao e aceito."))
    last = h.run(GREET, OLD_CAR)
    only_one_terminal_per_turn(h)
    t = last.terminal[0]
    assert t.kind == "refusal" and last.status == "refused" and len(h.agent) == 2, "oi + recusa: nenhuma pergunta de CEP, cobertura ou data no meio"
    assert t.text.startswith("Não consigo cotar este perfil: a seguradora não aceita veículos com mais de 20 anos.") and "Dados usados: modelo 1998 e 45 anos." in t.text
    assert not any(raw in t.text for raw in NO_RAW_API_TEXT) and "01310" not in t.text
    assert h.transport.calls == 1 and h.transport.payloads == [{"plano_id": "essencial", "idade": 45, "veiculo_ano": 1998}]
    q = h.store.quotes(h.trace)
    assert [(x["kind"], x["status"]) for x in q] == [("precheck", "refused")] and h.meta(h.agent[-1])["precheck"] == "recusa_provavel"
    assert h.conv["handoff_reason"] is None and h.store.money_not_in_quotes(h.trace) == []


def test_the_apis_motive_decides_the_text_even_when_the_precheck_predicted_another_reason():
    """A previsao era 'veiculo velho demais'; a API devolveu outra razao. O lead le a da API, e o desencontro fica no registro."""
    h = Harness(refused("Idade acima do limite de aceitacao (75 anos)."))
    last = h.run(GREET, OLD_CAR)
    assert "só aceita motoristas de até 75 anos" in last.terminal[0].text
    m = h.meta(h.agent[-1])
    assert m["precheck_kind"] == "vehicle_too_old" and m["refusal_kind"] == "age_above_limit"


def test_if_the_api_is_down_the_lead_is_never_told_refused_and_the_package_carries_the_precheck_verdict():
    h = Harness(*[err5xx(503, 0.2) for _ in range(4)])
    last = h.run(GREET, OLD_CAR)
    only_one_terminal_per_turn(h)
    t = last.terminal[0]
    assert t.kind == "handoff" and "Não consigo cotar este perfil" not in t.text and "recus" not in t.text.lower() and t.text.startswith(templates.UNAVAILABLE)
    c = h.conv
    assert (c["status"], c["handoff_reason"], c["failed_component"]) == ("handoff", "QUOTE_UNAVAILABLE", "quote_api") and c["handoff_detail"].startswith("precheck:")
    pkg = package(h)
    assert pkg["precheck"] == "recusa_provavel" and pkg["qualification"]["idade"] == 45 and pkg["qualification"]["veiculo_ano"] == 1998
    assert [(x["kind"], x["status"], len(x["attempts"])) for x in h.store.quotes(h.trace)] == [("precheck", "unavailable", 4)]


def test_when_the_api_accepts_what_the_precheck_refused_the_divergence_is_recorded_and_the_partial_price_is_never_shown():
    h = Harness(ok(0.1, plano="essencial", premio=77.77), ess())
    h.run(GREET, "é um fusca 1998, tenho 45 anos")
    mid = h.agent[-1]
    assert mid["kind"] in ("text", "question") and "CEP" in mid["text"] and h.meta(mid)["precheck_divergence"] is True and h.meta(mid)["precheck"] == "recusa_provavel"
    assert h.store.quotes(h.trace)[0]["kind"] == "precheck" and h.store.quotes(h.trace)[0]["status"] == "ok"
    last = h.run("01310-100", NEED_BASIC, START)
    all_text = "\n".join(m["text"] for m in h.agent)
    assert last.terminal[0].kind == "quote" and "R$ 119,90" in all_text and "77,77" not in all_text and "R$ 77" not in all_text
    assert money_in(all_text) and h.store.money_not_in_quotes(h.trace) == [], "a invariante ignora o preco parcial da confirmacao"
    assert [x["kind"] for x in h.store.quotes(h.trace)] == ["precheck", "quote"] and h.transport.calls == 2


def test_an_accepted_profile_costs_no_extra_call_and_the_precheck_runs_once_per_age_and_year():
    h = Harness(ess())
    h.run(*HAPPY)
    assert h.transport.calls == 1 and [x["kind"] for x in h.store.quotes(h.trace)] == ["quote"]
    assert h.meta(h.agent[1])["precheck"] == "ok"


def test_a_correction_that_makes_the_profile_ineligible_is_confirmed_by_the_api_and_ends_the_conversation():
    h = Harness(refused("Idade acima do limite de aceitacao (75 anos)."))
    last = h.run(GREET, DATA, "na verdade tenho 80 anos")
    assert last.terminal[0].kind == "refusal" and "Dados usados: modelo 2019 e 80 anos." in last.terminal[0].text and h.transport.calls == 1


def test_a_future_model_year_goes_to_a_human_right_away_without_asking_the_rest():
    h = Harness()
    last = h.run(GREET, "é um carro 2027, tenho 34 anos e moro no cep 30130-010")
    assert last.terminal[0].kind == "handoff" and h.conv["handoff_reason"] == "DATA_AMBIGUOUS" and h.transport.calls == 0
    assert h.conv["handoff_detail"] == "entrada_invalida:veiculo_ano:ano_modelo_futuro" and package(h)["precheck"] == "recusa_provavel"


# --- midia sem transcricao ------------------------------------------------------------------------------------------------------------------------
def test_media_without_transcription_is_answered_by_a_request_for_text_and_the_llm_is_not_called():
    h = Harness()
    r = h.say("[audio] mensagem de voz (12s)")
    t = r.terminal[0]
    assert t.kind == "question" and t.text == (f"{templates.GREETING} Por aqui eu só leio mensagens de texto, então não consegui abrir o seu áudio. "
                                              "Qual é o ano do modelo do seu carro? Se o documento mostra dois anos, como 2015/2016, vale o segundo.")
    assert h.llm.calls == [] and json.loads(h.conv["slots"]) == {}, "o 12 de '(12s)' nao e idade de ninguem"
    assert json.loads(h.store.messages(h.trace)[0]["meta"])["media"] == "audio" and h.meta(h.agent[0])["reply_source"] == "template_media"
    assert check_reply(templates.media_request("audio"), facts_used=(), base=BASE, lead_texts=[]) == ()


@pytest.mark.parametrize("marker,what", [("[audio] mensagem de voz (7s)", "áudio"), ("[imagem] foto do documento do carro", "imagem"), ("[documento] documento_do_carro.pdf", "documento"),
                                         ("[video] vídeo do carro", "vídeo")])
def test_the_second_media_in_a_row_without_any_new_data_goes_to_a_human(marker, what):
    h = Harness()
    h.say(marker)
    assert what in h.agent[0]["text"]
    last = h.say("[imagem] outra foto")
    only_one_terminal_per_turn(h)
    t = last.terminal[0]
    assert t.kind == "handoff" and h.conv["handoff_reason"] == "MEDIA_UNREADABLE" and h.conv["failed_component"] is None and t.text.startswith(templates.MEDIA_UNREADABLE)
    assert package(h)["reason"] == "MEDIA_UNREADABLE" and package(h)["missing"] == ["veiculo_ano", "idade", "cep", "necessidade", "data_inicio"] and h.llm.calls == []


def test_a_media_message_after_new_data_is_a_first_request_again_not_a_handoff():
    h = Harness()
    h.run("[documento] documento_do_carro.pdf", "é um onix 2019")
    last = h.say("[audio] mensagem de voz (5s)")
    assert last.terminal[0].kind == "question" and last.terminal[0].text.endswith("Qual é a sua idade?") and h.conv["status"] == "open"
    assert "Olá" not in last.terminal[0].text, "a apresentacao so vai na primeira mensagem do agente"


def test_media_after_everything_is_known_asks_for_text_without_inventing_a_next_question():
    h = Harness(ess())
    h.run(*HAPPY)
    last = h.say("[imagem] print da cotacao")
    assert last.terminal[0].kind == "text" and last.terminal[0].text.endswith("Pode escrever em texto o que você precisa?")


# --- reclamacao, cancelamento, sinistro ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("message,reason,lead_in", [
    ("isso é um absurdo, quero fazer uma reclamação do atendimento", HandoffReason.COMPLAINT, templates.COMPLAINT),
    ("quero cancelar o meu seguro", HandoffReason.CANCELLATION, templates.CANCEL),
    ("bati o carro ontem, preciso acionar o seguro", HandoffReason.CLAIM_SINISTRO, templates.CLAIM),
])
def test_complaint_cancellation_and_claim_each_end_in_their_own_handoff_with_a_template_and_the_data_collected_so_far(message, reason, lead_in):
    h = Harness()
    last = h.run(GREET, DATA, message)
    only_one_terminal_per_turn(h)
    t = last.terminal[0]
    assert t.kind == "handoff" and t.text == f"{lead_in} {templates.handoff_text()}" and not money_in(t.text)
    assert (h.conv["status"], h.conv["handoff_reason"], h.conv["failed_component"]) == ("handoff", reason.value, None)
    assert h.meta(h.agent[-1])["reply_source"] == "template_risk", "o LLM nao redige nada que leve a um handoff"
    pkg = package(h)
    assert pkg["reason"] == reason.value and pkg["told_to_lead"] == t.text and pkg["precheck"] == "ok"
    assert pkg["qualification"] == {"idade": 34, "veiculo_ano": 2019, "cep": "30130010", "plano_id": None, "data_inicio": None}
    assert pkg["missing"] == ["necessidade", "data_inicio"] and h.transport.calls == 0
    for forbidden in ("amanh", "em breve", "horas", "minutos", "desconto", "garant", "reembols", "indeniza"):
        assert forbidden not in t.text.lower()
    again = h.say("alô?")
    assert again.terminal[0].kind == "closed" and again.terminal[0].text == templates.AFTER_HANDOFF


@pytest.mark.parametrize("message,reason", [("quero cancelar", HandoffReason.CANCELLATION), ("isso é um absurdo", HandoffReason.COMPLAINT),
                                            ("roubaram meu carro", HandoffReason.CLAIM_SINISTRO)])
def test_the_handoff_works_as_the_very_first_message_with_nothing_collected(message, reason):
    h = Harness()
    last = h.say(message)
    assert last.terminal[0].kind == "handoff" and h.conv["handoff_reason"] == reason.value and package(h)["precheck"] is None
    assert package(h)["missing"] == ["veiculo_ano", "idade", "cep", "necessidade", "data_inicio"]


# --- conversa que nao avanca ------------------------------------------------------------------------------------------------------------------------
def test_the_same_question_unanswered_three_times_in_a_row_ends_in_conversation_stalled():
    h = Harness()
    h.run(GREET, "hmm", "não sei")
    assert h.conv["status"] == "open"
    last = h.say("sei lá")
    only_one_terminal_per_turn(h)
    t = last.terminal[0]
    assert t.kind == "handoff" and t.text == f"{templates.STALLED} {templates.handoff_text()}"
    assert (h.conv["handoff_reason"], h.conv["failed_component"], h.conv["handoff_detail"]) == ("CONVERSATION_STALLED", None, "pergunta_repetida:veiculo_ano")
    assert package(h)["reason"] == "CONVERSATION_STALLED" and h.llm.calls and len(h.agent) == 4


def test_a_new_piece_of_data_resets_the_stall_counter():
    h = Harness()
    h.run(GREET, "hmm", "não sei", "é um onix 2019", "hmm", "não sei")
    assert h.conv["status"] == "open" and h.meta(h.agent[-1])["asked"] == ["idade", "ask"]


def test_coverage_questions_are_not_a_stall_even_though_the_pending_question_is_repeated():
    h = Harness()
    h.run(GREET, "o que cobre o plano completo?", "e a carência, como é?", "e a franquia do essencial?", "e o premium cobre o quê?")
    assert h.conv["status"] == "open"


# --- fora de escopo ---------------------------------------------------------------------------------------------------------------------------------
def test_off_topic_is_redirected_once_and_insisting_goes_to_a_human():
    h = Harness()
    first = h.run(GREET, "quero um seguro de vida")
    assert first.terminal[0].text.startswith(templates.OFF_TOPIC) and h.conv["status"] == "open"
    last = h.say("e um seguro de viagem?")
    assert last.terminal[0].kind == "handoff" and h.conv["handoff_reason"] == "OUT_OF_SCOPE"
    assert last.terminal[0].text == f"{templates.OFF_TOPIC} {templates.handoff_text()}"


def test_off_topic_between_pieces_of_data_does_not_count_as_insisting():
    h = Harness()
    h.run(GREET, "quero um seguro de vida", "é um onix 2019", "e um seguro de casa?")
    assert h.conv["status"] == "open"


def test_every_new_static_template_passes_the_strict_guardrail():
    for text in (templates.MEDIA_UNREADABLE, templates.STALLED, templates.GREETING, templates.media_request("image", "Qual é a sua idade?"),
                 templates.media_request("video"), templates.failure_handoff_text(HandoffReason.MEDIA_UNREADABLE),
                 templates.failure_handoff_text(HandoffReason.CONVERSATION_STALLED), templates.failure_handoff_text(HandoffReason.OUT_OF_SCOPE)):
        assert check_reply(text, facts_used=(), base=BASE, lead_texts=[]) == (), text
