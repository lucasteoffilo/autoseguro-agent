"""Orcamentos de tempo do turno: fonte unica para o cliente, o smoke, os simuladores e os testes.

CRITERIO de latencia (UM so, aprovado): p95 do TURNO <= 5s sem cotacao e <= 12s com cotacao.
Todo o resto abaixo e MECANISMO para cumprir o criterio ou rede de seguranca. Em particular, o limite por chamada de LLM
NAO e um numero solto: e DERIVADO do criterio (analysis/e2e_latency_sim.py: `derive_llm_call_limit`), e o smoke projeta o
p95 do turno a partir das latencias medidas (`project_turn_p95`).
"""
from __future__ import annotations

# --- criterio (aprovado) -----------------------------------------------------------------------------
TURN_P95_NO_QUOTE_S = 5.0
TURN_P95_WITH_QUOTE_S = 12.0

# --- mecanismos --------------------------------------------------------------------------------------
HOLD_GRACE_S = 1.0          # "um instante" so sai se a /quote ainda estiver pendente 1s DEPOIS DE COMECAR (contado do inicio da cotacao, nao do turno)
HOLD_AFTER_S = 2.5          # a politica ANTERIOR (2,5s desde a chegada da mensagem): fica porque as simulacoes de analysis/ a modelam; o orquestrador usa HOLD_GRACE_S
TURN_CEILING_S = 20.0       # rede de seguranca: estourou => mensagem honesta + handoff, nunca silencio
OVERHEAD_S = 0.10           # webhook/terminal + SQLite + mascaramento + render de template

LLM_CALL_TIMEOUT_S = 6.0    # por tentativa
LLM_MAX_ATTEMPTS = 2        # 1 retry

# --- politica B da /quote ----------------------------------------------------------------------------
QUOTE_BUDGET_S = 15.0
QUOTE_ATTEMPT_TIMEOUT_S = 10.0
QUOTE_MAX_CALLS = 4
QUOTE_BACKOFF_BASE_S = 0.3
QUOTE_MIN_ATTEMPT_S = 1.0   # com menos orcamento que isso, nem tenta

# --- reply do LLM ------------------------------------------------------------------------------------
REPLY_TARGET_WORDS = 40     # pedido no prompt (tom de WhatsApp)
REPLY_HARD_MAX_WORDS = 50   # o guardrail reprova acima disso
