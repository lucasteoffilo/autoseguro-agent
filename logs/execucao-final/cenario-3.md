# Log de execução — `trc_eeabfe52aeaf`

- **LLM:** `openrouter/dots-studio/dots-3-note-preview:free` (modo `real`) · **criada em** 2026-10-22T01:28:48.688340+00:00 · **atualizada em** 2026-10-22T01:28:55.588973+00:00
- **Desfecho:** `refused`
- **Mensagens:** 4 · **cotações:** 1 · **tentativas da `/quote`:** 1

## Verificações (critérios E3 do PLAN)

| Verificação | Resultado |
|---|---|
| LLM real registrado | sim |
| Existe cotação `ok` | **não** |
| Existe falha seguida de retry visível | **não** (use uma semente/API que falhe antes de acertar) |
| Todo `R$` dito pelo agente existe numa cotação `ok` desta conversa | sim (0 valor(es)) |
| Sem PII nem segredo no texto exportado | sim (varredura do texto exportado: 0 achados) |

## De onde veio cada texto que o lead leu

| Origem | Mensagens | `reply_source` | Detalhe |
|---|---|---|---|
| Texto do modelo, entregue | 0 | `llm` | — |
| Texto do modelo barrado pelo guardrail | 0 | `template_fallback` | — |
| Sem saída utilizável do modelo (falha, filtro do provedor, saída inválida) | 0 | `template_fallback`, `sem_saida` | — |
| Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII) | 0 | `template_question` | — |
| Trocado por desenho (a pergunta de necessidade, as confirmações e o eco do que o lead acabou de dar são do produto) | 0 | `template_question`, `template_echo`, e `template_fallback` nesses turnos | — |
| Template por desenho (risco, cotação, recusa, handoff, estado, mídia) | 2 | `template_*` | template_opening ×1, template_refusal ×1 |

**Fração do modelo:** 0 de 2 respostas ao lead (0%); 0 de 0 em que o texto do modelo poderia ter chegado (—). **Barrados pelo guardrail:** 0 (— das vezes em que o texto do modelo poderia ter chegado).

### Textos do modelo barrados pelo guardrail

> Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu ("grava o texto barrado pelo guardrail", campo `blocked_reply` do `meta`); em banco anterior só a regra foi gravada e a linha diz "não gravado". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada ("texto omitido: pii").

_Nenhum texto do modelo foi barrado pelo guardrail._

## Transcrição

| # | Quando (UTC) | Quem | Tipo | Texto (já mascarado) |
|---|---|---|---|---|
| 1 | 01:28:48.688 | lead | text | oi, quero cotar um fusca |
| 2 | 01:28:50.784 | agente | question | Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro? |
| 3 | 01:28:50.786 | lead | text | é um fusca 1998, tenho 45 anos e moro no cep 01310-100 |
| 4 | 01:28:55.588 | agente | refusal | Não consigo cotar este perfil: a seguradora não aceita veículos com mais de 20 anos. ⏎ Dados usados: modelo 1998 e 45 anos. ⏎ Por isso vou encerrar por aqui. Obrigado pelo interesse! |

## Decisões do agente, mensagem a mensagem

| # | Tipo | Registro (`meta`) |
|---|---|---|
| 1 | lead/text | — |
| 2 | agent/question | intent="greeting"; reply_source="template_opening"; asked=["veiculo_ano", "ask"]; attempt=1; llm_latency_s=2.09; tokens=1511→44 |
| 3 | lead/text | — |
| 4 | agent/refusal | reply_source="template_refusal"; precheck="recusa_provavel"; precheck_kind="vehicle_too_old"; refusal_kind="vehicle_too_old"; attempt=1; llm_latency_s=3.722; limiter_wait_s=1.059; tokens=1569→147 |

## Cotações e tentativas da `/quote`

### `qte_bbc31fbf9fcd` — precheck · refused · plano `essencial` · 0.008s

- **Entrada normalizada enviada:** `{"idade": 45, "plano_id": "essencial", "veiculo_ano": 1998}`
- **Resposta:** {"motivo": "Veiculo com mais de 20 anos nao e aceito."}

| Tentativa | Início (s) | Latência (s) | HTTP | Erro | Decisão |
|---|---|---|---|---|---|
| 1 | 0.0 | 0.007 | 422 | refused | stop_refused |

## Estado final dos slots

| Slot | Estado | Valor | Evidência no texto do lead |
|---|---|---|---|
| cep | anchored | 01310100 | 01310-100 |
| idade | anchored | 45 | 45 |
| veiculo_ano | anchored | 1998 | 1998 |
