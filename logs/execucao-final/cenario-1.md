# Log de execução — `trc_80e2a405a477`

- **LLM:** `openrouter/dots-studio/dots-3-note-preview:free` (modo `real`) · **criada em** 2026-10-21T20:13:40.204734+00:00 · **atualizada em** 2026-10-21T20:13:52.385822+00:00
- **Desfecho:** `quoted`
- **Mensagens:** 8 · **cotações:** 1 · **tentativas da `/quote`:** 2

## Verificações (critérios E3 do PLAN)

| Verificação | Resultado |
|---|---|
| LLM real registrado | sim |
| Existe cotação `ok` | sim: qte_ec477e095aa3 |
| Existe falha seguida de retry visível | sim: 1 tentativa(s) com decisão `retry` |
| Todo `R$` dito pelo agente existe numa cotação `ok` desta conversa | sim (2 valor(es)) |
| Sem PII nem segredo no texto exportado | sim (varredura do texto exportado: 0 achados) |

## De onde veio cada texto que o lead leu

| Origem | Mensagens | `reply_source` | Detalhe |
|---|---|---|---|
| Texto do modelo, entregue | 1 | `llm` | — |
| Texto do modelo barrado pelo guardrail | 0 | `template_fallback` | — |
| Sem saída utilizável do modelo (falha, filtro do provedor, saída inválida) | 0 | `template_fallback`, `sem_saida` | — |
| Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII) | 0 | `template_question` | — |
| Trocado por desenho (a pergunta de necessidade, as confirmações e o eco do que o lead acabou de dar são do produto) | 2 | `template_question`, `template_echo`, e `template_fallback` nesses turnos | — |
| Template por desenho (risco, cotação, recusa, handoff, estado, mídia) | 1 | `template_*` | template_quote ×1 |

**Fração do modelo:** 1 de 4 respostas ao lead (25%); 1 de 1 em que o texto do modelo poderia ter chegado (100%). **Barrados pelo guardrail:** 0 (0% das vezes em que o texto do modelo poderia ter chegado).

### Textos do modelo barrados pelo guardrail

> Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu ("grava o texto barrado pelo guardrail", campo `blocked_reply` do `meta`); em banco anterior só a regra foi gravada e a linha diz "não gravado". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada ("texto omitido: pii").

_Nenhum texto do modelo foi barrado pelo guardrail._

## Transcrição

| # | Quando (UTC) | Quem | Tipo | Texto (já mascarado) |
|---|---|---|---|---|
| 1 | 20:13:40.205 | lead | text | oi |
| 2 | 20:13:41.727 | agente | text | Olá! Sou a assistente virtual da AutoSeguro. Bem-vindo à AutoSeguro. Para começar a cotação, qual é o ano do modelo do seu carro? |
| 3 | 20:13:41.728 | lead | text | é um hb20 2022, tenho 41 anos e moro no cep 01310-100 |
| 4 | 20:13:46.288 | agente | question | Anotado: modelo 2022, 41 anos e CEP 01310-100. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h? |
| 5 | 20:13:46.289 | lead | text | quero cobrir terceiros e vidros também |
| 6 | 20:13:48.427 | agente | question | Anotado: cobertura do plano Completo. Em que dia você quer que o seguro comece a valer? |
| 7 | 20:13:48.428 | lead | text | pode começar dia 01/11/2026 |
| 8 | 20:13:52.385 | agente | quote | Aqui está a cotação do plano Completo: ⏎ • Mensalidade: R$ 209,90 ⏎ • Franquia: R$ 3.000,00 ⏎ • Cobre: colisão, roubo, furto, danos a terceiros e vidros ⏎ • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência. ⏎ Dados usados: modelo 2022, 41 anos, CEP 01310-100, início em 01/11/2026 (domingo) e plano Completo. ⏎ Se algum dado estiver errado, me avisa que eu refaço. |

## Decisões do agente, mensagem a mensagem

| # | Tipo | Registro (`meta`) |
|---|---|---|
| 1 | lead/text | — |
| 2 | agent/text | intent="greeting"; reply_source="llm"; asked=["veiculo_ano", "ask"]; attempt=1; llm_latency_s=1.518; tokens=1503→46 |
| 3 | lead/text | — |
| 4 | agent/question | intent="provide_info"; reply_source="template_fallback"; violations=["R2_numero_nao_permitido", "R7_termo_sem_fato"]; asked=["necessidade", "ask"]; precheck="ok"; attempt=1; llm_latency_s=2.92; limiter_wait_s=1.629; tokens=1578→163 |
| 5 | lead/text | — |
| 6 | agent/question | intent="provide_info"; reply_source="template_echo"; facts_used=["necessidades"]; asked=["data_inicio", "ask"]; attempt=1; llm_latency_s=1.911; limiter_wait_s=0.22; tokens=1687→62 |
| 7 | lead/text | — |
| 8 | agent/quote | reply_source="template_quote"; attempt=1; llm_latency_s=2.531; limiter_wait_s=1.235; quote_elapsed_s=0.182; tokens=1742→85 |

## Cotações e tentativas da `/quote`

### `qte_ec477e095aa3` — quote · ok · plano `completo` · 0.182s

- **Entrada normalizada enviada:** `{"cep": "01310100", "data_inicio": "2026-11-01", "idade": 41, "plano_id": "completo", "veiculo_ano": 2022}`
- **Resposta:** mensalidade 209.9, franquia 3000

| Tentativa | Início (s) | Latência (s) | HTTP | Erro | Decisão |
|---|---|---|---|---|---|
| 1 | 0.0 | 0.005 | 500 | http_5xx | retry |
| 2 | 0.177 | 0.005 | 200 | none | accept |

## Estado final dos slots

| Slot | Estado | Valor | Evidência no texto do lead |
|---|---|---|---|
| cep | anchored | 01310100 | 01310-100 |
| data_inicio | anchored | 2026-11-01 | 01/11/2026 |
| idade | anchored | 41 | 41 |
| necessidade | anchored | terceiros_vidros | terceiros |
| veiculo_ano | anchored | 2022 | 2022 |
