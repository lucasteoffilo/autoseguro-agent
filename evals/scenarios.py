"""Cenarios SINTETICOS escritos a mao: um por motivo de handoff, mais cotacao, recusa e as bordas da elegibilidade. Sao o gabarito dos evals ("100% de motivo correto").

Os anos saem do `today` (`build(today)`): um carro de 7 anos continua sendo aceito em qualquer data, e um de 28 continua sendo recusado.
Nenhuma linha vem do dataset; os evals derivados do dataset estao em `evals/dataset.py` e nao tem gabarito.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Synthetic:
    id: str
    lines: tuple[str, ...]
    expect_status: str                       # quoted | refused | handoff | open
    expect_reason: str | None = None         # HandoffReason, se for handoff
    expect_component: str | None = None      # FailedComponent, onde o motivo exige (QUOTE_UNAVAILABLE, SAFETY_GUARD)
    expect_refusal_kind: str | None = None   # RefusalKind, se for recusa
    api: str = "service"                     # service | down
    llm_failures: tuple[str | None, ...] = ()
    note: str = ""


def _first_of_next_month(today: date) -> date:
    return date(today.year + (today.month == 12), today.month % 12 + 1, 1)


def build(today: date) -> list[Synthetic]:
    y = today.year
    nxt = _first_of_next_month(today)
    start = f"{nxt.day:02d}/{nxt.month:02d}/{nxt.year}"
    mid = f"15/{nxt.month:02d}/{nxt.year}"
    new = f"é um onix {y - 7}, tenho 34 anos e moro no cep 30130-010"
    happy = ["oi", new, "só roubo e colisão", f"começando dia {start}"]
    quoted = [*happy[:3], f"pode começar dia {start}"]
    return [
        # --- cotacao ---------------------------------------------------------------------------------------------------------------------------
        Synthetic("cotacao-essencial", tuple(happy), "quoted"),
        Synthetic("cotacao-completo", ("oi", new, "quero cobrir terceiros e vidros também", f"começando dia {start}"), "quoted"),
        Synthetic("cotacao-premium", ("oi", new, "quero carro reserva e assistência 24h, a completa", f"começando dia {start}"), "quoted"),
        Synthetic("cotacao-pro-rata", ("oi", new, "só roubo e colisão", f"começando dia {mid}"), "quoted", note="inicio no meio do mes: primeiro pagamento proporcional"),
        Synthetic("cotacao-quatro-dados-numa-mensagem", (f"oi, quero cotar: onix {y - 3}, 29 anos, cep 01310-100, começando dia {start}", "só roubo e colisão"), "quoted",
                  note="a necessidade so vale como resposta a pergunta dela (D5): o agente a pergunta, os outros quatro dados ja estavam ancorados"),
        Synthetic("cotacao-com-correcao-que-recusa", (*happy, "errei, tenho 80 anos"), "refused", expect_refusal_kind="age_above_limit",
                  note="depois da cotacao, a correcao leva a um perfil recusado: a API confirma"),
        Synthetic("cotacao-duvida-de-cobertura-no-meio", ("oi", "e a carência, como funciona?", new, "só roubo e colisão", f"começando dia {start}"), "quoted"),
        Synthetic("cotacao-midia-no-meio", ("oi", "[audio] mensagem de voz (9s)", new, "só roubo e colisão", f"começando dia {start}"), "quoted"),
        # --- recusa (a API e a palavra final; a pre-checagem antecipa) ---------------------------------------------------------------------------
        Synthetic("recusa-carro-velho", ("oi", f"é um fusca {y - 28}, tenho 45 anos e moro no cep 01310-100"), "refused", expect_refusal_kind="vehicle_too_old"),
        Synthetic("recusa-idade-acima", ("oi", f"é um onix {y - 7}, tenho 80 anos e moro no cep 01310-100"), "refused", expect_refusal_kind="age_above_limit"),
        Synthetic("recusa-menor-de-idade", ("oi", f"é um onix {y - 7}, tenho 17 anos e moro no cep 01310-100"), "refused", expect_refusal_kind="age_out_of_range"),
        Synthetic("borda-aceita-75-anos-e-carro-de-20", ("oi", f"é um gol {y - 20}, tenho 75 anos e moro no cep 30130-010", "só roubo e colisão", f"começando dia {start}"),
                  "quoted", note="as duas bordas de dentro: a pre-checagem nao pode recusar"),
        Synthetic("borda-recusada-76-anos", ("oi", f"é um onix {y - 7}, tenho 76 anos e moro no cep 30130-010"), "refused", expect_refusal_kind="age_above_limit"),
        Synthetic("borda-recusada-carro-de-21", ("oi", f"é um gol {y - 21}, tenho 40 anos e moro no cep 30130-010"), "refused", expect_refusal_kind="vehicle_too_old"),
        Synthetic("borda-aceita-18-anos", ("oi", f"é um onix {y - 7}, tenho 18 anos e moro no cep 30130-010", "só roubo e colisão", f"começando dia {start}"), "quoted"),
        # --- um cenario por motivo de handoff ----------------------------------------------------------------------------------------------------
        Synthetic("handoff-quote-unavailable", tuple(quoted), "handoff", "QUOTE_UNAVAILABLE", "quote_api", api="down"),
        Synthetic("handoff-quote-unavailable-na-pre-checagem", ("oi", f"é um fusca {y - 28}, tenho 45 anos e moro no cep 01310-100"), "handoff", "QUOTE_UNAVAILABLE",
                  "quote_api", api="down", note="a pre-checagem previu recusa e a API esta fora: o lead nao ouve 'recusado'"),
        Synthetic("handoff-human-requested", ("oi", "prefiro falar com uma pessoa"), "handoff", "HUMAN_REQUESTED"),
        Synthetic("handoff-human-requested-no-meio", ("oi", new, "quero falar com um atendente"), "handoff", "HUMAN_REQUESTED"),
        Synthetic("handoff-complaint", ("oi", "isso é um absurdo, quero fazer uma reclamação"), "handoff", "COMPLAINT"),
        Synthetic("handoff-claim-sinistro", ("oi", "bati o carro ontem e preciso acionar o seguro"), "handoff", "CLAIM_SINISTRO"),
        Synthetic("handoff-cancellation", ("oi", "quero cancelar o meu seguro"), "handoff", "CANCELLATION"),
        Synthetic("handoff-data-ambiguous-ano-futuro", ("oi", f"é um carro {y + 1}, tenho 34 anos e moro no cep 30130-010"), "handoff", "DATA_AMBIGUOUS"),
        Synthetic("handoff-data-ambiguous-confirmacao-sem-resposta", ("oi", f"o carro é {y - 8} mas o modelo é {y - 7}", "sei lá", "não sei"), "handoff", "DATA_AMBIGUOUS",
                  note="duas confirmacoes sem resposta util"),
        Synthetic("handoff-media-unreadable", ("[audio] mensagem de voz (9s)", "[documento] documento_do_carro.pdf"), "handoff", "MEDIA_UNREADABLE"),
        Synthetic("handoff-ready-to-close", (*happy, "gostei, quero fechar"), "handoff", "READY_TO_CLOSE"),
        Synthetic("handoff-conversation-stalled", ("oi", "hmm", "não sei", "sei lá"), "handoff", "CONVERSATION_STALLED"),
        Synthetic("handoff-price-objection-oferta-recusada", ("oi", new, "quero cobrir terceiros e vidros também", f"começando dia {start}", "achei caro", "não, obrigado"),
                  "handoff", "PRICE_OBJECTION", note="1a objecao: uma alternativa real; o lead recusa: humano, sem desconto"),
        Synthetic("handoff-price-objection-oferta-sem-resposta", ("oi", new, "quero cobrir terceiros e vidros também", f"começando dia {start}", "achei caro", "talvez", "sei lá"),
                  "handoff", "PRICE_OBJECTION", note="a resposta a oferta nao e sim nem nao duas vezes: a pergunta e repetida uma vez, depois humano"),
        Synthetic("handoff-price-objection-sem-plano-mais-barato", (*happy, "tá muito caro"), "handoff", "PRICE_OBJECTION", note="ja e o plano mais barato"),
        Synthetic("handoff-out-of-scope", ("oi", "quero um seguro de vida", "e um seguro de viagem?"), "handoff", "OUT_OF_SCOPE"),
        Synthetic("handoff-safety-guard-llm-fora", ("oi",), "handoff", "SAFETY_GUARD", "llm", llm_failures=("http_503", "http_503")),
        Synthetic("handoff-safety-guard-filtro-do-provedor", ("oi", "oi de novo"), "handoff", "SAFETY_GUARD", "llm", llm_failures=("content_filter",) * 4,
                  note="o provedor filtra dois turnos seguidos"),
        # --- nao e handoff -------------------------------------------------------------------------------------------------------------------------
        Synthetic("sem-handoff-desconto-antes-da-cotacao", ("oi", "me dá um desconto de 50%?"), "open", note="nao ha cotacao a descontar: o agente nao promete nem inventa valor"),
        Synthetic("sem-handoff-objecao-com-alternativa-aceita", ("oi", new, "quero cobrir terceiros e vidros também", f"começando dia {start}", "achei caro", "sim, pode mostrar"),
                  "quoted", note="a alternativa e um plano real, cotado de novo na API"),
    ]
