# Log de execução — `trc_3a56c6f16fab`

- **LLM:** `openrouter/dots-studio/dots-3-note-preview:free` (modo `real`) · **criada em** 2026-10-21T20:14:11.693476+00:00 · **atualizada em** 2026-10-21T20:14:17.619381+00:00
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
| Texto do modelo, entregue | 1 | `llm` | — |
| Texto do modelo barrado pelo guardrail | 0 | `template_fallback` | — |
| Sem saída utilizável do modelo (falha, filtro do provedor, saída inválida) | 0 | `template_fallback`, `sem_saida` | — |
| Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII) | 0 | `template_question` | — |
| Trocado por desenho (a pergunta de necessidade, as confirmações e o eco do que o lead acabou de dar são do produto) | 0 | `template_question`, `template_echo`, e `template_fallback` nesses turnos | — |
| Template por desenho (risco, cotação, recusa, handoff, estado, mídia) | 1 | `template_*` | template_refusal ×1 |

**Fração do modelo:** 1 de 2 respostas ao lead (50%); 1 de 1 em que o texto do modelo poderia ter chegado (100%). **Barrados pelo guardrail:** 0 (0% das vezes em que o texto do modelo poderia ter chegado).

### Textos do modelo barrados pelo guardrail

> Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu ("grava o texto barrado pelo guardrail", campo `blocked_reply` do `meta`); em banco anterior só a regra foi gravada e a linha diz "não gravado". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada ("texto omitido: pii").

_Nenhum texto do modelo foi barrado pelo guardrail._

## Transcrição

| # | Quando (UTC) | Quem | Tipo | Texto (já mascarado) |
|---|---|---|---|---|
| 1 | 20:14:11.693 | lead | text | oi, quero cotar um fusca |
| 2 | 20:14:13.545 | agente | text | Olá! Sou a assistente virtual da AutoSeguro. Que bom que você quer cotar o Fusca. Para começarmos, qual é o ano do modelo do seu carro? |
| 3 | 20:14:13.547 | lead | text | é um fusca 1998, tenho 45 anos e moro no cep 01310-100 |
| 4 | 20:14:17.618 | agente | refusal | Não consigo cotar este perfil: a seguradora não aceita veículos com mais de 20 anos. ⏎ Dados usados: modelo 1998 e 45 anos. ⏎ Por isso vou encerrar por aqui. Obrigado pelo interesse! |

## Decisões do agente, mensagem a mensagem

| # | Tipo | Registro (`meta`) |
|---|---|---|
| 1 | lead/text | — |
| 2 | agent/text | intent="greeting"; reply_source="llm"; asked=["veiculo_ano", "ask"]; attempt=1; llm_latency_s=1.848; tokens=1511→46 |
| 3 | lead/text | — |
| 4 | agent/refusal | reply_source="template_refusal"; precheck="recusa_provavel"; precheck_kind="vehicle_too_old"; refusal_kind="vehicle_too_old"; attempt=1; llm_latency_s=2.756; limiter_wait_s=1.299; tokens=1585→153 |

## Cotações e tentativas da `/quote`

### `qte_c2ac2e59d44b` — precheck · refused · plano `essencial` · 0.006s

- **Entrada normalizada enviada:** `{"idade": 45, "plano_id": "essencial", "veiculo_ano": 1998}`
- **Resposta:** {"motivo": "Veiculo com mais de 20 anos nao e aceito."}

| Tentativa | Início (s) | Latência (s) | HTTP | Erro | Decisão |
|---|---|---|---|---|---|
| 1 | 0.0 | 0.006 | 422 | refused | stop_refused |

## Estado final dos slots

| Slot | Estado | Valor | Evidência no texto do lead |
|---|---|---|---|
| cep | anchored | 01310100 | 01310-100 |
| idade | anchored | 45 | 45 |
| veiculo_ano | anchored | 1998 | 1998 |
