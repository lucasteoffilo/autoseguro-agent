# Execução final com o LLM real

**Roteirizada** (`make chat ARGS="--llm real --script …"`, uma mensagem do lead por linha, as de [`docs/DEMO.md`](../../docs/DEMO.md)), não uma conversa livre. O cenário 1 é o log principal.

- **Código:** commit `f6960f7` (árvore `05eba31`), sem alteração durante a execução. Modelo: `dots-studio/dots-3-note-preview:free` (OpenRouter, provedor de origem AtlasCloud). Dia: 2026-10-21.
- **Integridade:** `make llm-ping` antes; cada cenário rodou uma vez, na ordem do DEMO (sessão A com `QUOTE_SEED=91`: 1 a 6, 7, 7b, 8; a API foi reiniciada com `QUOTE_SEED=80` para a sessão B); 35 requisições ao provedor (1 do ping e 34 das conversas; limite de 60), 34 respostas 200 e um HTTP 400. O 400 é o do cenário 7 (a frase de injeção composta, rejeitada pelo provedor), desfecho que o DEMO documenta como aceito; qualquer outro 4xx teria parado a execução. Sem troca de modelo e sem repetir cenário.
- **Mascarado e varrido:** os textos vêm do SQLite já mascarados e a exportação recusa o que a varredura de PII e segredo achar (0 achados).

| Cenário | O quê | Conversa | Log |
|---|---|---|---|
| 1 | Queda visível da `/quote` com retry (log principal) | `trc_80e2a405a477` | [cenario-1.md](cenario-1.md) |
| 2 | Cotação normal | `trc_99128913749b` | [cenario-2.md](cenario-2.md) |
| 3 | Recusa antecipada | `trc_3a56c6f16fab` | [cenario-3.md](cenario-3.md) |
| 4 | Objeção de preço aceitando a alternativa | `trc_1b2d427d77b9` | [cenario-4.md](cenario-4.md) |
| 5 | Pedido de humano | `trc_0d474ab1d240` | [cenario-5.md](cenario-5.md) |
| 6 | O carro é 2015 mas o modelo é 2016 | `trc_83faf169b0b9` | [cenario-6.md](cenario-6.md) |
| 7 | Tentativa de injeção de prompt | `trc_652ef1f40537` | [cenario-7.md](cenario-7.md) |
| 7b | Engenharia social mais sutil | `trc_4d6ee769706a` | [cenario-7b.md](cenario-7b.md) |
| 8 | Áudio | `trc_96271ffba662` | [cenario-8.md](cenario-8.md) |
| B (semente 80, cenário 2) | Cotação lenta com o "um instante" | `trc_c8aa88100a9d` | [sessao-b.md](sessao-b.md) |

---

# Conversas exportadas

| Conversa | Desfecho | Motivo / componente | LLM | Cotacoes (ok/recusa/fora) | Retries da /quote | Mensagens | Texto do modelo / respostas | Barrados | Arquivo |
|---|---|---|---|---|---|---|---|---|---|
| `trc_80e2a405a477` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 1/0/0 | 1 | 8 | 1/4 | 0 | [cenario-1.md](cenario-1.md) |
| `trc_99128913749b` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 1/0/0 | 0 | 8 | 0/4 | 0 | [cenario-2.md](cenario-2.md) |
| `trc_3a56c6f16fab` | refused | — | openrouter/dots-studio/dots-3-note-preview:free | 0/1/0 | 0 | 4 | 1/2 | 0 | [cenario-3.md](cenario-3.md) |
| `trc_1b2d427d77b9` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 2/0/0 | 0 | 12 | 0/6 | 0 | [cenario-4.md](cenario-4.md) |
| `trc_0d474ab1d240` | handoff | HUMAN_REQUESTED | openrouter/dots-studio/dots-3-note-preview:free | 0/0/0 | 0 | 4 | 0/2 | 0 | [cenario-5.md](cenario-5.md) |
| `trc_83faf169b0b9` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 1/0/0 | 0 | 10 | 1/5 | 0 | [cenario-6.md](cenario-6.md) |
| `trc_652ef1f40537` | open | — | openrouter/dots-studio/dots-3-note-preview:free | 0/0/0 | 0 | 6 | 0/3 | 0 | [cenario-7.md](cenario-7.md) |
| `trc_4d6ee769706a` | handoff | OUT_OF_SCOPE | openrouter/dots-studio/dots-3-note-preview:free | 0/0/0 | 0 | 8 | 0/4 | 0 | [cenario-7b.md](cenario-7b.md) |
| `trc_96271ffba662` | handoff | MEDIA_UNREADABLE | openrouter/dots-studio/dots-3-note-preview:free | 0/0/0 | 0 | 4 | 0/2 | 0 | [cenario-8.md](cenario-8.md) |
| `trc_c8aa88100a9d` | quoted | — | openrouter/dots-studio/dots-3-note-preview:free | 1/0/0 | 0 | 9 | 1/4 | 0 | [sessao-b.md](sessao-b.md) |

## Total das 10 conversas: de onde veio cada texto que o lead leu

| Origem | Mensagens | `reply_source` | Detalhe |
|---|---|---|---|
| Texto do modelo, entregue | 4 | `llm` | — |
| Texto do modelo barrado pelo guardrail | 0 | `template_fallback` | — |
| Sem saída utilizável do modelo (falha, filtro do provedor, saída inválida) | 1 | `template_fallback`, `sem_saida` | — |
| Texto do modelo trocado pelo orquestrador (não perguntava o dado pendente, ou tinha PII) | 4 | `template_question` | — |
| Trocado por desenho (a pergunta de necessidade, as confirmações e o eco do que o lead acabou de dar são do produto) | 11 | `template_question`, `template_echo`, e `template_fallback` nesses turnos | — |
| Template por desenho (risco, cotação, recusa, handoff, estado, mídia) | 16 | `template_*` | template_media ×1, template_quote ×6, template_refusal ×1, template_risk ×6, template_state ×2 |

**Fração do modelo:** 4 de 36 respostas ao lead (11%); 4 de 9 em que o texto do modelo poderia ter chegado (44%). **Barrados pelo guardrail:** 0 (0% das vezes em que o texto do modelo poderia ter chegado).

### Textos do modelo barrados pelo guardrail (todas as conversas)

> Nenhum destes textos chegou ao lead: ele leu o template que está na transcrição. O texto barrado só existe em execuções feitas depois do commit que o introduziu ("grava o texto barrado pelo guardrail", campo `blocked_reply` do `meta`); em banco anterior só a regra foi gravada e a linha diz "não gravado". Vem mascarado e truncado em 500 caracteres; se sobrar PII depois de mascarar, só a regra é gravada ("texto omitido: pii").

_Nenhum texto do modelo foi barrado pelo guardrail._
