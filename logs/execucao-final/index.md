# Execução final com o LLM real

**Roteirizada** (`make chat ARGS="--llm real --script …"`, uma mensagem do lead por linha, as de [`docs/DEMO.md`](../../docs/DEMO.md)), não uma conversa livre. O cenário 1 é o log principal.

- **Código:** commit `1f11668` (árvore `297912b`), sem alteração durante a execução. Modelo: `dots-studio/dots-3-note-preview:free` (OpenRouter, provedor de origem AtlasCloud). Dia: 2026-10-22 (UTC).
- **Integridade:** `make llm-ping` antes; cada cenário rodou uma vez, na ordem do DEMO (sessão A com `QUOTE_SEED=91`: 1 a 6, 7, 7b, 8; a API foi reiniciada com `QUOTE_SEED=80` para a sessão B); 35 requisições ao provedor (1 do ping e 34 das conversas; limite de 60), 34 respostas 200 e um HTTP 400. O 400 é o do cenário 7 (a frase de injeção composta, rejeitada pelo provedor), desfecho que o DEMO documenta como aceito; qualquer outro 4xx teria parado a execução. Sem troca de modelo e sem repetir cenário.
- **Mascarado e varrido:** os textos vêm do SQLite já mascarados e a exportação recusa o que a varredura de PII e segredo achar (0 achados).

| Cenário | O quê | Conversa | Log |
|---|---|---|---|
| 1 | Queda visível da `/quote` com retry (log principal) | `trc_c02f9e248b1d` | [cenario-1.md](cenario-1.md) |
| 2 | Cotação normal | `trc_0d7d454f5df0` | [cenario-2.md](cenario-2.md) |
| 3 | Recusa antecipada | `trc_eeabfe52aeaf` | [cenario-3.md](cenario-3.md) |
| 4 | Objeção de preço aceitando a alternativa | `trc_33f6d2dba504` | [cenario-4.md](cenario-4.md) |
| 5 | Pedido de humano | `trc_c2845d4c0a66` | [cenario-5.md](cenario-5.md) |
| 6 | O carro é 2015 mas o modelo é 2016 | `trc_dbc687d4db31` | [cenario-6.md](cenario-6.md) |
| 7 | Tentativa de injeção de prompt | `trc_9b11fba32584` | [cenario-7.md](cenario-7.md) |
| 7b | Engenharia social mais sutil | `trc_8f9f67c023d7` | [cenario-7b.md](cenario-7b.md) |
| 8 | Áudio | `trc_42844886698b` | [cenario-8.md](cenario-8.md) |
| B (semente 80, cenário 2) | Cotação lenta com o "um instante" | `trc_2c53ea49ddb1` | [sessao-b.md](sessao-b.md) |

---

# Conversas exportadas

| Conversa | Desfecho | Motivo / componente | LLM | Cotacoes (ok/recusa/fora) | Retries da /quote | Mensagens | Texto do modelo / respostas | Barrados | Arquivo |
|---|---|---|---|---|---|---|---|---|---|
| `trc_c02f9e248b1d` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 1/0/0 | 1 | 8 | 0/4 | 0 | [cenario-1.md](cenario-1.md) |
| `trc_0d7d454f5df0` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 1/0/0 | 0 | 8 | 0/4 | 0 | [cenario-2.md](cenario-2.md) |
| `trc_eeabfe52aeaf` | refused | — | openrouter/dots-studio/dots-3-note-preview:free | 0/1/0 | 0 | 4 | 0/2 | 0 | [cenario-3.md](cenario-3.md) |
| `trc_33f6d2dba504` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 2/0/0 | 0 | 12 | 0/6 | 0 | [cenario-4.md](cenario-4.md) |
| `trc_c2845d4c0a66` | handoff | HUMAN_REQUESTED | openrouter/dots-studio/dots-3-note-preview:free | 0/0/0 | 0 | 4 | 0/2 | 0 | [cenario-5.md](cenario-5.md) |
| `trc_dbc687d4db31` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 1/0/0 | 0 | 10 | 0/5 | 0 | [cenario-6.md](cenario-6.md) |
| `trc_9b11fba32584` | open | — | openrouter/dots-studio/dots-3-note-preview:free | 0/0/0 | 0 | 6 | 0/3 | 0 | [cenario-7.md](cenario-7.md) |
| `trc_8f9f67c023d7` | open | — | openrouter/dots-studio/dots-3-note-preview:free | 0/0/0 | 0 | 8 | 0/4 | 0 | [cenario-7b.md](cenario-7b.md) |
| `trc_42844886698b` | handoff | MEDIA_UNREADABLE | openrouter/dots-studio/dots-3-note-preview:free | 0/0/0 | 0 | 4 | 0/2 | 0 | [cenario-8.md](cenario-8.md) |
| `trc_2c53ea49ddb1` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 1/0/0 | 0 | 9 | 0/4 | 0 | [sessao-b.md](sessao-b.md) |

## Total das 10 conversas: de onde veio cada texto que o lead leu

| Origem | Mensagens | `reply_source` | Detalhe |
|---|---|---|---|
| Texto do modelo, entregue | 0 | `llm` | — |
| Texto do modelo barrado pelo guardrail | 0 | `template_fallback` | — |
| Sem saída utilizável do modelo (falha, filtro do provedor, saída inválida) | 1 | `template_fallback`, `sem_saida` | — |
| Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII) | 0 | `template_question` | — |
| Trocado por desenho (a pergunta de necessidade, as confirmações e o eco do que o lead acabou de dar são do produto) | 11 | `template_question`, `template_echo`, e `template_fallback` nesses turnos | — |
| Template por desenho (risco, cotação, recusa, handoff, estado, mídia) | 24 | `template_*` | template_media ×1, template_opening ×9, template_quote ×6, template_refusal ×1, template_risk ×6, template_state ×1 |

**Fração do modelo:** 0 de 36 respostas ao lead (0%); 0 de 1 em que o texto do modelo poderia ter chegado (0%). **Barrados pelo guardrail:** 0 (0% das vezes em que o texto do modelo poderia ter chegado).

### Textos do modelo barrados pelo guardrail (todas as conversas)

> Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu ("grava o texto barrado pelo guardrail", campo `blocked_reply` do `meta`); em banco anterior só a regra foi gravada e a linha diz "não gravado". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada ("texto omitido: pii").

_Nenhum texto do modelo foi barrado pelo guardrail._
