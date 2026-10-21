# Log de execução — `trc_83faf169b0b9`

- **LLM:** `openrouter/dots-studio/dots-3-note-preview:free` (modo `real`) · **criada em** 2026-10-21T20:14:52.585230+00:00 · **atualizada em** 2026-10-21T20:15:08.111662+00:00
- **Desfecho:** `quoted`
- **Mensagens:** 10 · **cotações:** 1 · **tentativas da `/quote`:** 1

## Verificações (critérios E3 do PLAN)

| Verificação | Resultado |
|---|---|
| LLM real registrado | sim |
| Existe cotação `ok` | sim: qte_6fe9601b4df4 |
| Existe falha seguida de retry visível | **não** (use uma semente/API que falhe antes de acertar) |
| Todo `R$` dito pelo agente existe numa cotação `ok` desta conversa | sim (2 valor(es)) |
| Sem PII nem segredo no texto exportado | sim (varredura do texto exportado: 0 achados) |

## De onde veio cada texto que o lead leu

| Origem | Mensagens | `reply_source` | Detalhe |
|---|---|---|---|
| Texto do modelo, entregue | 1 | `llm` | — |
| Texto do modelo barrado pelo guardrail | 0 | `template_fallback` | — |
| Sem saída utilizável do modelo (falha, filtro do provedor, saída inválida) | 0 | `template_fallback`, `sem_saida` | — |
| Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII) | 0 | `template_question` | — |
| Trocado por desenho (a pergunta de necessidade, as confirmações e o eco do que o lead acabou de dar são do produto) | 3 | `template_question`, `template_echo`, e `template_fallback` nesses turnos | — |
| Template por desenho (risco, cotação, recusa, handoff, estado, mídia) | 1 | `template_*` | template_quote ×1 |

**Fração do modelo:** 1 de 5 respostas ao lead (20%); 1 de 1 em que o texto do modelo poderia ter chegado (100%). **Barrados pelo guardrail:** 0 (0% das vezes em que o texto do modelo poderia ter chegado).

### Textos do modelo barrados pelo guardrail

> Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu ("grava o texto barrado pelo guardrail", campo `blocked_reply` do `meta`); em banco anterior só a regra foi gravada e a linha diz "não gravado". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada ("texto omitido: pii").

_Nenhum texto do modelo foi barrado pelo guardrail._

## Transcrição

| # | Quando (UTC) | Quem | Tipo | Texto (já mascarado) |
|---|---|---|---|---|
| 1 | 20:14:52.585 | lead | text | oi |
| 2 | 20:14:54.697 | agente | text | Olá! Sou a assistente virtual da AutoSeguro. Tudo bem? Para te dar uma cotação, preciso do ano do modelo do seu carro. |
| 3 | 20:14:54.699 | lead | text | o carro é 2015 mas o modelo é 2016, tenho 34 anos e moro no cep 30130-010 |
| 4 | 20:14:58.731 | agente | confirmation | Anotado: 34 anos e CEP 30130-010. Só pra confirmar: modelo 2016? |
| 5 | 20:14:58.732 | lead | text | sim |
| 6 | 20:15:01.788 | agente | question | Anotado: modelo 2016. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h? |
| 7 | 20:15:01.790 | lead | text | só roubo e colisão |
| 8 | 20:15:04.623 | agente | question | Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer? |
| 9 | 20:15:04.625 | lead | text | pode começar dia 01/11/2026 |
| 10 | 20:15:08.110 | agente | quote | Aqui está a cotação do plano Essencial: ⏎ • Mensalidade: R$ 137,88 ⏎ • Franquia: R$ 4.500,00 ⏎ • Cobre: colisão, roubo e furto ⏎ • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência. ⏎ Dados usados: modelo 2016, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial. ⏎ Se algum dado estiver errado, me avisa que eu refaço. |

## Decisões do agente, mensagem a mensagem

| # | Tipo | Registro (`meta`) |
|---|---|---|
| 1 | lead/text | — |
| 2 | agent/text | intent="greeting"; reply_source="llm"; asked=["veiculo_ano", "ask"]; attempt=1; llm_latency_s=2.106; tokens=1503→42 |
| 3 | lead/text | — |
| 4 | agent/confirmation | intent="provide_info"; reply_source="template_echo"; facts_used=["planos", "necessidades"]; asked=["veiculo_ano", "confirm"]; attempt=1; llm_latency_s=2.986; limiter_wait_s=1.037; tokens=1581→143 |
| 5 | lead/text | — |
| 6 | agent/question | intent="provide_info"; reply_source="template_echo"; facts_used=["necessidades"]; asked=["necessidade", "ask"]; precheck="ok"; attempt=1; llm_latency_s=2.892; limiter_wait_s=0.155; tokens=1636→98 |
| 7 | lead/text | — |
| 8 | agent/question | intent="provide_info"; reply_source="template_echo"; facts_used=["necessidades"]; asked=["data_inicio", "ask"]; attempt=1; llm_latency_s=2.574; limiter_wait_s=0.252; tokens=1711→57 |
| 9 | lead/text | — |
| 10 | agent/quote | reply_source="template_quote"; attempt=1; llm_latency_s=2.894; limiter_wait_s=0.573; quote_elapsed_s=0.01; tokens=1720→101 |

## Cotações e tentativas da `/quote`

### `qte_6fe9601b4df4` — quote · ok · plano `essencial` · 0.01s

- **Entrada normalizada enviada:** `{"cep": "30130010", "data_inicio": "2026-11-01", "idade": 34, "plano_id": "essencial", "veiculo_ano": 2016}`
- **Resposta:** mensalidade 137.88, franquia 4500

| Tentativa | Início (s) | Latência (s) | HTTP | Erro | Decisão |
|---|---|---|---|---|---|
| 1 | 0.0 | 0.009 | 200 | none | accept |

## Estado final dos slots

| Slot | Estado | Valor | Evidência no texto do lead |
|---|---|---|---|
| cep | anchored | 30130010 | 30130-010 |
| data_inicio | anchored | 2026-11-01 | 01/11/2026 |
| idade | anchored | 34 | 34 |
| necessidade | anchored | basica | roubo |
| veiculo_ano | confirmed | 2016 | confirmou: sim |
