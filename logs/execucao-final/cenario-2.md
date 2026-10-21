# Log de execução — `trc_99128913749b`

- **LLM:** `openrouter/dots-studio/dots-3-note-preview:free` (modo `real`) · **criada em** 2026-10-21T20:13:55.990921+00:00 · **atualizada em** 2026-10-21T20:14:07.794390+00:00
- **Desfecho:** `quoted`
- **Mensagens:** 8 · **cotações:** 1 · **tentativas da `/quote`:** 1

## Verificações (critérios E3 do PLAN)

| Verificação | Resultado |
|---|---|
| LLM real registrado | sim |
| Existe cotação `ok` | sim: qte_b3245041c06f |
| Existe falha seguida de retry visível | **não** (use uma semente/API que falhe antes de acertar) |
| Todo `R$` dito pelo agente existe numa cotação `ok` desta conversa | sim (2 valor(es)) |
| Sem PII nem segredo no texto exportado | sim (varredura do texto exportado: 0 achados) |

## De onde veio cada texto que o lead leu

| Origem | Mensagens | `reply_source` | Detalhe |
|---|---|---|---|
| Texto do modelo, entregue | 0 | `llm` | — |
| Texto do modelo barrado pelo guardrail | 0 | `template_fallback` | — |
| Sem saída utilizável do modelo (falha, filtro do provedor, saída inválida) | 0 | `template_fallback`, `sem_saida` | — |
| Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII) | 1 | `template_question` | — |
| Trocado por desenho (a pergunta de necessidade, as confirmações e o eco do que o lead acabou de dar são do produto) | 2 | `template_question`, `template_echo`, e `template_fallback` nesses turnos | — |
| Template por desenho (risco, cotação, recusa, handoff, estado, mídia) | 1 | `template_*` | template_quote ×1 |

**Fração do modelo:** 0 de 4 respostas ao lead (0%); 0 de 1 em que o texto do modelo poderia ter chegado (0%). **Barrados pelo guardrail:** 0 (0% das vezes em que o texto do modelo poderia ter chegado).

### Textos do modelo barrados pelo guardrail

> Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu ("grava o texto barrado pelo guardrail", campo `blocked_reply` do `meta`); em banco anterior só a regra foi gravada e a linha diz "não gravado". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada ("texto omitido: pii").

_Nenhum texto do modelo foi barrado pelo guardrail._

## Transcrição

| # | Quando (UTC) | Quem | Tipo | Texto (já mascarado) |
|---|---|---|---|---|
| 1 | 20:13:55.991 | lead | text | oi |
| 2 | 20:13:57.491 | agente | question | Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro? |
| 3 | 20:13:57.491 | lead | text | é um onix 2021, tenho 34 anos e moro no cep 30130-010 |
| 4 | 20:14:02.093 | agente | question | Anotado: modelo 2021, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h? |
| 5 | 20:14:02.094 | lead | text | só roubo e colisão |
| 6 | 20:14:04.659 | agente | question | Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer? |
| 7 | 20:14:04.660 | lead | text | pode começar dia 01/11/2026 |
| 8 | 20:14:07.794 | agente | quote | Aqui está a cotação do plano Essencial: ⏎ • Mensalidade: R$ 119,90 ⏎ • Franquia: R$ 4.500,00 ⏎ • Cobre: colisão, roubo e furto ⏎ • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência. ⏎ Dados usados: modelo 2021, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial. ⏎ Se algum dado estiver errado, me avisa que eu refaço. |

## Decisões do agente, mensagem a mensagem

| # | Tipo | Registro (`meta`) |
|---|---|---|
| 1 | lead/text | — |
| 2 | agent/question | intent="greeting"; reply_source="template_question"; asked=["veiculo_ano", "ask"]; attempt=1; llm_latency_s=1.496; tokens=1503→42 |
| 3 | lead/text | — |
| 4 | agent/question | intent="provide_info"; reply_source="template_fallback"; violations=["R2_numero_nao_permitido", "R7_termo_sem_fato"]; asked=["necessidade", "ask"]; precheck="ok"; attempt=1; llm_latency_s=2.94; limiter_wait_s=1.653; tokens=1561→124 |
| 5 | lead/text | — |
| 6 | agent/question | intent="provide_info"; reply_source="template_echo"; facts_used=["necessidades"]; asked=["data_inicio", "ask"]; attempt=1; llm_latency_s=2.359; limiter_wait_s=0.199; tokens=1667→61 |
| 7 | lead/text | — |
| 8 | agent/quote | reply_source="template_quote"; attempt=1; llm_latency_s=2.327; limiter_wait_s=0.787; quote_elapsed_s=0.01; tokens=1718→91 |

## Cotações e tentativas da `/quote`

### `qte_b3245041c06f` — quote · ok · plano `essencial` · 0.01s

- **Entrada normalizada enviada:** `{"cep": "30130010", "data_inicio": "2026-11-01", "idade": 34, "plano_id": "essencial", "veiculo_ano": 2021}`
- **Resposta:** mensalidade 119.9, franquia 4500

| Tentativa | Início (s) | Latência (s) | HTTP | Erro | Decisão |
|---|---|---|---|---|---|
| 1 | 0.0 | 0.01 | 200 | none | accept |

## Estado final dos slots

| Slot | Estado | Valor | Evidência no texto do lead |
|---|---|---|---|
| cep | anchored | 30130010 | 30130-010 |
| data_inicio | anchored | 2026-11-01 | 01/11/2026 |
| idade | anchored | 34 | 34 |
| necessidade | anchored | basica | roubo |
| veiculo_ano | anchored | 2021 | 2021 |
