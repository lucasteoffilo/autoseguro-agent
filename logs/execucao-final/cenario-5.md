# Log de execução — `trc_0d474ab1d240`

- **LLM:** `openrouter/dots-studio/dots-3-note-preview:free` (modo `real`) · **criada em** 2026-10-21T20:14:43.665057+00:00 · **atualizada em** 2026-10-21T20:14:48.918330+00:00
- **Desfecho:** `handoff` · motivo `HUMAN_REQUESTED`
- **Mensagens:** 4 · **cotações:** 0 · **tentativas da `/quote`:** 0

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
| Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII) | 1 | `template_question` | — |
| Trocado por desenho (a pergunta de necessidade, as confirmações e o eco do que o lead acabou de dar são do produto) | 0 | `template_question`, `template_echo`, e `template_fallback` nesses turnos | — |
| Template por desenho (risco, cotação, recusa, handoff, estado, mídia) | 1 | `template_*` | template_risk ×1 |

**Fração do modelo:** 0 de 2 respostas ao lead (0%); 0 de 1 em que o texto do modelo poderia ter chegado (0%). **Barrados pelo guardrail:** 0 (0% das vezes em que o texto do modelo poderia ter chegado).

### Textos do modelo barrados pelo guardrail

> Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu ("grava o texto barrado pelo guardrail", campo `blocked_reply` do `meta`); em banco anterior só a regra foi gravada e a linha diz "não gravado". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada ("texto omitido: pii").

_Nenhum texto do modelo foi barrado pelo guardrail._

## Transcrição

| # | Quando (UTC) | Quem | Tipo | Texto (já mascarado) |
|---|---|---|---|---|
| 1 | 20:14:43.665 | lead | text | oi |
| 2 | 20:14:45.712 | agente | question | Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro? |
| 3 | 20:14:45.713 | lead | text | prefiro falar com uma pessoa |
| 4 | 20:14:48.917 | agente | handoff | Claro. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado. |

## Decisões do agente, mensagem a mensagem

| # | Tipo | Registro (`meta`) |
|---|---|---|
| 1 | lead/text | — |
| 2 | agent/question | intent="greeting"; reply_source="template_question"; asked=["veiculo_ano", "ask"]; attempt=1; llm_latency_s=2.042; tokens=1503→45 |
| 3 | lead/text | — |
| 4 | agent/handoff | intent="wants_human"; reply_source="template_risk"; attempt=1; llm_latency_s=2.093; limiter_wait_s=1.104; handoff_reason="HUMAN_REQUESTED"; tokens=1537→39 |

## Cotações e tentativas da `/quote`

_Nenhuma chamada à `/quote` nesta conversa._
## Estado final dos slots

| Slot | Estado | Valor | Evidência no texto do lead |
|---|---|---|---|
| — | — | — | — |

## Pacote de handoff entregue ao humano

```json
{
  "created_at": "2026-10-21T20:14:48.917231+00:00",
  "failed_component": null,
  "last_quote": null,
  "missing": [
    "veiculo_ano",
    "idade",
    "cep",
    "necessidade",
    "data_inicio"
  ],
  "precheck": null,
  "qualification": {
    "cep": null,
    "data_inicio": null,
    "idade": null,
    "plano_id": null,
    "veiculo_ano": null
  },
  "reason": "HUMAN_REQUESTED",
  "recent_messages": [
    {
      "role": "lead",
      "text": "oi",
      "ts": "2026-10-21T20:14:43.665416+00:00"
    },
    {
      "role": "agent",
      "text": "Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?",
      "ts": "2026-10-21T20:14:45.712277+00:00"
    },
    {
      "role": "lead",
      "text": "prefiro falar com uma pessoa",
      "ts": "2026-10-21T20:14:45.713812+00:00"
    }
  ],
  "schema_version": 1,
  "told_to_lead": "Claro. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.",
  "trace_id": "trc_0d474ab1d240"
}
```
