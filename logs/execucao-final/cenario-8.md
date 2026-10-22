# Log de execução — `trc_42844886698b`

- **LLM:** `openrouter/dots-studio/dots-3-note-preview:free` (modo `real`) · **criada em** 2026-10-22T01:30:12.551997+00:00 · **atualizada em** 2026-10-22T01:30:12.553502+00:00
- **Desfecho:** `handoff` · motivo `MEDIA_UNREADABLE` · detalhe `midia_repetida:audio`
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
| Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII) | 0 | `template_question` | — |
| Trocado por desenho (a pergunta de necessidade, as confirmações e o eco do que o lead acabou de dar são do produto) | 0 | `template_question`, `template_echo`, e `template_fallback` nesses turnos | — |
| Template por desenho (risco, cotação, recusa, handoff, estado, mídia) | 2 | `template_*` | template_media ×1, template_state ×1 |

**Fração do modelo:** 0 de 2 respostas ao lead (0%); 0 de 0 em que o texto do modelo poderia ter chegado (—). **Barrados pelo guardrail:** 0 (— das vezes em que o texto do modelo poderia ter chegado).

### Textos do modelo barrados pelo guardrail

> Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu ("grava o texto barrado pelo guardrail", campo `blocked_reply` do `meta`); em banco anterior só a regra foi gravada e a linha diz "não gravado". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada ("texto omitido: pii").

_Nenhum texto do modelo foi barrado pelo guardrail._

## Transcrição

| # | Quando (UTC) | Quem | Tipo | Texto (já mascarado) |
|---|---|---|---|---|
| 1 | 01:30:12.552 | lead | text | [audio] mensagem de voz (12s) |
| 2 | 01:30:12.552 | agente | question | Olá! Sou a assistente virtual da AutoSeguro. Por aqui eu só leio mensagens de texto, então não consegui abrir o seu áudio. Qual é o ano do modelo do seu carro? |
| 3 | 01:30:12.552 | lead | text | [audio] mensagem de voz (5s) |
| 4 | 01:30:12.553 | agente | handoff | Continuo sem conseguir abrir o que você enviou: por aqui eu só leio mensagens de texto. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado. |

## Decisões do agente, mensagem a mensagem

| # | Tipo | Registro (`meta`) |
|---|---|---|
| 1 | lead/text | media="audio" |
| 2 | agent/question | reply_source="template_media"; asked=["veiculo_ano", "ask"]; media="audio" |
| 3 | lead/text | media="audio" |
| 4 | agent/handoff | reply_source="template_state"; media="audio"; handoff_reason="MEDIA_UNREADABLE" |

## Cotações e tentativas da `/quote`

_Nenhuma chamada à `/quote` nesta conversa._
## Estado final dos slots

| Slot | Estado | Valor | Evidência no texto do lead |
|---|---|---|---|
| — | — | — | — |

## Pacote de handoff entregue ao humano

```json
{
  "created_at": "2026-10-22T01:30:12.553191+00:00",
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
  "reason": "MEDIA_UNREADABLE",
  "recent_messages": [
    {
      "role": "lead",
      "text": "[audio] mensagem de voz (12s)",
      "ts": "2026-10-22T01:30:12.552423+00:00"
    },
    {
      "role": "agent",
      "text": "Olá! Sou a assistente virtual da AutoSeguro. Por aqui eu só leio mensagens de texto, então não consegui abrir o seu áudio. Qual é o ano do modelo do seu carro?",
      "ts": "2026-10-22T01:30:12.552647+00:00"
    },
    {
      "role": "lead",
      "text": "[audio] mensagem de voz (5s)",
      "ts": "2026-10-22T01:30:12.552920+00:00"
    }
  ],
  "schema_version": 1,
  "told_to_lead": "Continuo sem conseguir abrir o que você enviou: por aqui eu só leio mensagens de texto. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.",
  "trace_id": "trc_42844886698b"
}
```
