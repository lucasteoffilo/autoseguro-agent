# Relatório dos evals — PASSA

- **Gerado em:** 2026-10-21 16:37 UTC · **relógio dos evals:** 2026-10-21 · **semente da seleção:** 20261021
- **Backend da `/quote` e oráculo:** API HTTP http://localhost:8100 (relogio do servidor, UTC)
- **LLM:** `MockLLM` (determinístico) atrás do mesmo `GuardedLLM` e do mesmo orquestrador de produção; nenhuma chamada de rede para LLM.

## Critérios do PLAN

| # | Critério | Resultado | Alvo | Veredito |
|---|---|---|---|---|
| C1 | Nenhum preço inventado | 3933/3933 (100.0%) | 100%: todo R$ dito ao lead vem do serviço para a entrada daquela cotação | **PASSA** |
| C2 | Motivo de handoff correto nos sintéticos | 34/34 (100.0%) | 100%: status, motivo e componente esperados em cada cenário escrito à mão | **PASSA** |
| C3 | Recusas e cotações batem com a API | 2521/2521 (100.0%) | 100%: cada cotação e cada recusa dita ao lead concorda com o serviço para a mesma entrada; recusa dita sempre liga a uma recusa registrada | **PASSA** |
| C4 | Uma mensagem terminal por turno | 20078/20078 (100.0%) | 100% dos turnos: nem silêncio, nem duas respostas | **PASSA** |
| C5 | Nenhuma PII gravada | 2534/2534 (100.0%) | 0 achados no banco, nas mensagens e no pacote (detector do gate de envio + CPF com verificadores válidos) | **PASSA** |

- **C1** — mensagens com R$: 1764; valores em reais conferidos: 3933; cotações recalculadas no serviço: 1764
- **C2** — cenários de handoff: 17; motivos cobertos: 12/12
- **C3** — recusas ditas ao lead: 757; cotações ditas ao lead: 1764; perfil recusável que terminou sem recusa (handoff ou aberto): 2

### C3: o que explicar (2)

Perfis que a API recusaria e que **não** terminaram em recusa. Não são falhas do critério (nenhum foi cotado); são os dois caminhos em que o agente deliberadamente não diz "recusado":

- `handoff-quote-unavailable-na-pre-checagem` terminou em `handoff:QUOTE_UNAVAILABLE` (precheck:attempts_exhausted:connection), e a API recusaria: a pré-checagem previu a recusa e a API estava fora. O agente só diz "recusado" depois que a API confirma, então a conversa foi a um humano com o veredito (`precheck: recusa_provavel`) no pacote. É o comportamento projetado, não um erro.
- `handoff-data-ambiguous-ano-futuro` terminou em `handoff:DATA_AMBIGUOUS` (entrada_invalida:veiculo_ano:ano_modelo_futuro), e a API recusaria: ano-modelo futuro. A API o recusaria como "fora das faixas", mas pode ser um modelo do próximo ano, então a decisão é de um humano (`DATA_AMBIGUOUS`) em vez de uma recusa automática. É a regra do PLAN, não um erro.

## Cenários sintéticos (34, escritos à mão)

| Cenário | Esperado | Obteve | |
|---|---|---|---|
| `cotacao-essencial` | quoted | quoted | ✅ |
| `cotacao-completo` | quoted | quoted | ✅ |
| `cotacao-premium` | quoted | quoted | ✅ |
| `cotacao-pro-rata` | quoted | quoted | ✅ |
| `cotacao-quatro-dados-numa-mensagem` | quoted | quoted | ✅ |
| `cotacao-com-correcao-que-recusa` | refused · age_above_limit | refused · age_above_limit | ✅ |
| `cotacao-duvida-de-cobertura-no-meio` | quoted | quoted | ✅ |
| `cotacao-midia-no-meio` | quoted | quoted | ✅ |
| `recusa-carro-velho` | refused · vehicle_too_old | refused · vehicle_too_old | ✅ |
| `recusa-idade-acima` | refused · age_above_limit | refused · age_above_limit | ✅ |
| `recusa-menor-de-idade` | refused · age_out_of_range | refused · age_out_of_range | ✅ |
| `borda-aceita-75-anos-e-carro-de-20` | quoted | quoted | ✅ |
| `borda-recusada-76-anos` | refused · age_above_limit | refused · age_above_limit | ✅ |
| `borda-recusada-carro-de-21` | refused · vehicle_too_old | refused · vehicle_too_old | ✅ |
| `borda-aceita-18-anos` | quoted | quoted | ✅ |
| `handoff-quote-unavailable` | handoff · QUOTE_UNAVAILABLE | handoff:QUOTE_UNAVAILABLE | ✅ |
| `handoff-quote-unavailable-na-pre-checagem` | handoff · QUOTE_UNAVAILABLE | handoff:QUOTE_UNAVAILABLE | ✅ |
| `handoff-human-requested` | handoff · HUMAN_REQUESTED | handoff:HUMAN_REQUESTED | ✅ |
| `handoff-human-requested-no-meio` | handoff · HUMAN_REQUESTED | handoff:HUMAN_REQUESTED | ✅ |
| `handoff-complaint` | handoff · COMPLAINT | handoff:COMPLAINT | ✅ |
| `handoff-claim-sinistro` | handoff · CLAIM_SINISTRO | handoff:CLAIM_SINISTRO | ✅ |
| `handoff-cancellation` | handoff · CANCELLATION | handoff:CANCELLATION | ✅ |
| `handoff-data-ambiguous-ano-futuro` | handoff · DATA_AMBIGUOUS | handoff:DATA_AMBIGUOUS | ✅ |
| `handoff-data-ambiguous-confirmacao-sem-resposta` | handoff · DATA_AMBIGUOUS | handoff:DATA_AMBIGUOUS | ✅ |
| `handoff-media-unreadable` | handoff · MEDIA_UNREADABLE | handoff:MEDIA_UNREADABLE | ✅ |
| `handoff-ready-to-close` | handoff · READY_TO_CLOSE | handoff:READY_TO_CLOSE | ✅ |
| `handoff-conversation-stalled` | handoff · CONVERSATION_STALLED | handoff:CONVERSATION_STALLED | ✅ |
| `handoff-price-objection-duas-vezes` | handoff · PRICE_OBJECTION | handoff:PRICE_OBJECTION | ✅ |
| `handoff-price-objection-sem-plano-mais-barato` | handoff · PRICE_OBJECTION | handoff:PRICE_OBJECTION | ✅ |
| `handoff-out-of-scope` | handoff · OUT_OF_SCOPE | handoff:OUT_OF_SCOPE | ✅ |
| `handoff-safety-guard-llm-fora` | handoff · SAFETY_GUARD | handoff:SAFETY_GUARD | ✅ |
| `handoff-safety-guard-filtro-do-provedor` | handoff · SAFETY_GUARD | handoff:SAFETY_GUARD | ✅ |
| `sem-handoff-desconto-antes-da-cotacao` | open | open | ✅ |
| `sem-handoff-objecao-com-alternativa-aceita` | quoted | quoted | ✅ |

## Conversas derivadas do dataset (população inteira)

- **2500 conversas** reproduzidas (16470 mensagens do lead, 26s). Colunas lidas: `conversation_id`, `message_index`, `sender_role`, `message_type`, `message_body` — nenhuma das que vazam o gabarito.
- **O harness responde só o que o roteiro do vendedor nunca pergunta:** a cobertura e a data de início, uma vez cada e só quando o agente pergunta (3498 respostas no total). Todo o resto é a fala do próprio lead. Chegaram a uma cotação `ok`: 1749 conversas.
- Conversas com mídia sem transcrição: 1420 (56.8%) · com PII mascarada: 2500 (100.0%)

| Desfecho do agente | Conversas | % |
|---|---|---|
| quoted | 1146 | 45.8% |
| refused | 751 | 30.0% |
| handoff:READY_TO_CLOSE | 294 | 11.8% |
| handoff:MEDIA_UNREADABLE | 231 | 9.2% |
| handoff:PRICE_OBJECTION | 78 | 3.1% |

### Amostra determinística de 30 conversas (espalhada pelos desfechos do agente; os textos ficam em `var/evals/`, fora do repo)

| Conversa | Turnos | Desfecho do agente | Cotações (ok/recusa/fora) | Mídia | Pré-checagem |
|---|---|---|---|---|---|
| `conv_00185` | 8 | handoff:MEDIA_UNREADABLE | 1/0/0 | 2 | ok |
| `conv_00304` | 9 | quoted | 1/0/0 | 1 | ok |
| `conv_00433` | 7 | refused | 0/1/0 | 1 | recusa_provavel |
| `conv_00567` | 7 | handoff:READY_TO_CLOSE | 1/0/0 | 0 | ok |
| `conv_00594` | 9 | handoff:READY_TO_CLOSE | 1/0/0 | 1 | ok |
| `conv_00745` | 8 | handoff:READY_TO_CLOSE | 1/0/0 | 1 | ok |
| `conv_00768` | 8 | handoff:PRICE_OBJECTION | 1/0/0 | 0 | ok |
| `conv_00786` | 10 | handoff:MEDIA_UNREADABLE | 1/0/0 | 2 | ok |
| `conv_00808` | 8 | refused | 0/1/0 | 1 | recusa_provavel |
| `conv_00811` | 5 | refused | 0/1/0 | 0 | recusa_provavel |
| `conv_00820` | 7 | refused | 0/1/0 | 1 | recusa_provavel |
| `conv_00868` | 10 | handoff:PRICE_OBJECTION | 1/0/0 | 1 | ok |
| `conv_00883` | 8 | handoff:READY_TO_CLOSE | 1/0/0 | 0 | ok |
| `conv_01002` | 7 | handoff:READY_TO_CLOSE | 1/0/0 | 0 | ok |
| `conv_01014` | 11 | handoff:MEDIA_UNREADABLE | 1/0/0 | 2 | ok |
| `conv_01064` | 9 | handoff:MEDIA_UNREADABLE | 1/0/0 | 2 | ok |
| `conv_01412` | 8 | handoff:PRICE_OBJECTION | 1/0/0 | 0 | ok |
| `conv_01503` | 6 | refused | 0/1/0 | 0 | recusa_provavel |
| `conv_01575` | 8 | quoted | 1/0/0 | 1 | ok |
| `conv_01577` | 8 | quoted | 1/0/0 | 0 | ok |
| `conv_01607` | 10 | handoff:PRICE_OBJECTION | 1/0/0 | 1 | ok |
| `conv_01678` | 7 | quoted | 1/0/0 | 1 | ok |
| `conv_01715` | 8 | quoted | 1/0/0 | 1 | ok |
| `conv_01775` | 9 | handoff:PRICE_OBJECTION | 1/0/0 | 0 | ok |
| `conv_01778` | 9 | handoff:PRICE_OBJECTION | 1/0/0 | 1 | ok |
| `conv_01877` | 10 | quoted | 1/0/0 | 1 | ok |
| `conv_01903` | 10 | handoff:MEDIA_UNREADABLE | 1/0/0 | 2 | ok |
| `conv_01949` | 7 | refused | 0/1/0 | 1 | recusa_provavel |
| `conv_01973` | 8 | handoff:READY_TO_CLOSE | 1/0/0 | 0 | ok |
| `conv_02082` | 10 | handoff:MEDIA_UNREADABLE | 1/0/0 | 2 | ok |

## O que estes números NÃO provam

- O `MockLLM` extrai com o mesmo leitor determinístico da ancoragem: **o mock prova o encanamento, não a qualidade da conversa.** Estes números dizem que o sistema não deixa o modelo (qualquer um) inventar preço nem recusa; não medem a naturalidade das respostas nem a taxa de acerto do modelo real (isso é a Etapa 7).
- As conversas do dataset são **reproduções**: as mensagens do lead respondem ao vendedor humano, não ao agente. Perguntas fora de ordem e dados que o agente já pediu viram parte da rotina. Por isso o desfecho do agente (cotada, recusada, handoff) **não é comparado com o desfecho do dataset**, que não é usado.
- O oráculo é o serviço de cotação (a lógica vendorizada, ou a API HTTP no modo `--api`). Perto de 31/12 o relógio do agente e o do servidor (UTC) podem discordar por horas.
- Os cenários sintéticos são o gabarito do motivo de handoff: foram escritos por quem escreveu o código. Cobrem cada motivo uma ou duas vezes, **não** a variedade da fala real.
