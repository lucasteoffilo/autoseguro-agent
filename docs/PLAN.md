# Plano de implementação

> **Estado (2026-10-20):** Etapa 0 (fundação) e Etapa 1 (decisões de desenho) concluídas, **sem commit ainda**.
> Próxima: **Etapa 2a** (cliente de cotação); o trabalho **para no fim da 2a** até aprovação.
> Não existe código de agente ainda: só o contrato do destino do handoff (`src/autoseguro/handoff.py`).

## 1. Escopo para ~5 horas

**Mínimo que precisa funcionar:** o agente conduz a conversa, cota com retry e passa ao humano nos casos deste plano, tudo
rastreável e **sem preço inventado**. Isso é: Etapas 2a, 2b, 3, 4 (a/b), 7 e 8.
**Bônus, só se sobrar tempo:** webhook FastAPI e concorrência (Etapa 5) e evals completos (Etapa 6).

Orçamento estimado (trabalho de implementação, sem folga para imprevistos): 2a 50 min · 2b 80 min · 4a 25 min · 3 60 min ·
4b 20 min · 7 15 min (autor) · 8 30 min = **~4h40**. Não há folga de verdade: o primeiro lugar a cortar está na seção 11.

## 2. Princípios (cada um vira um teste)

1. **Preço só sai da API.** O LLM nunca escreve um valor. Números das mensagens vêm de template preenchido com a resposta da API, e um guardrail de saída rejeita qualquer "R$" que não exista na resposta daquele `trace_id`.
2. **Na dúvida, atrasar ou passar ao humano.** Preço errado é pior que preço atrasado. Nunca estimar, arredondar ou "chutar" cotação, nem com a API fora do ar.
3. **A API é a palavra final.** A pré-checagem de elegibilidade só melhora a experiência; nenhuma recusa é comunicada ao lead sem confirmação da API.
4. **Tudo rastreável.** Toda mensagem, cotação e tentativa tem id e status, ligados por um `trace_id`.
5. **PII mínima.** Identificadores diretos (CPF, e-mail, telefone, placa, nome) nunca são persistidos nem enviados ao LLM. Os insumos da cotação (idade, ano do veículo, CEP, plano, data) ficam como slots.
6. **Não prometer o que o canal não garante.** Nada de prazo, horário ou canal de continuidade no texto de handoff.

## 3. Decisões fechadas

| Tema | Decisão | Por quê |
|---|---|---|
| Cliente de cotação | **Política B**: timeout 10s, retry só em 5xx/conexão, no máximo 4 chamadas, **no máximo uma em voo**, backoff exponencial com jitter, orçamento de 15s (e nunca além do prazo restante do turno) | Menor carga e menor taxa de falha entre as opções simples (seção 4) |
| Hedging | **Descartado.** Não existe parâmetro de hedging no código | Corta o p95 de 8s para 2,5s, mas custa +14% de chamadas (+35% degradado); a mensagem de espera cobre a cauda |
| Handoff | Pacote com **código fixo de motivo**, resumo da qualificação, última cotação com id e `trace_id`. O agente diz ao lead, com honestidade, o que acontece depois | Humano assume sem refazer perguntas; lead não fica no escuro |
| Destino do handoff | **Interface `HandoffSink`**; padrão SQLite. CRM ou fila entram **além** do SQLite, sem mexer no agente | Contrato e suíte de teste já existem (seção 6) |
| Texto do handoff | **Genérico**: não promete prazo, horário nem canal. O SLA real é configuração de negócio (`HANDOFF_NEXT_STEP_TEXT`, opcional, vazio por padrão) | Só é verdade o que o canal garante |
| Recusa por regra | Explica e encerra. Registrada como **recusa**, separada de handoff | A recusa é decisão de negócio da API, não falha |
| Objeção de preço | Oferece **uma** alternativa real via API; se hesitar de novo, handoff `PRICE_OBJECTION`. Nunca promete desconto | Perder lead por preço é o desfecho mais comum no dataset; o humano pode negociar |
| Plano | Pergunta a **necessidade em linguagem simples** e o agente mapeia para um plano. Cota **um** plano e oferece comparar | O lead não conhece "Essencial/Completo/Premium" |
| Pré-checagem | Mantida **por experiência** (lead de 80 anos não responde CEP, plano e data para ouvir "recusado" no fim). Lê as faixas do `/planos`. Contrato contra a API real: **bordas + amostra aleatória**, sem varredura | A API manda; divergência é detectada, não presumida |
| Interface | Terminal + webhook fino em FastAPI (bônus). Sem WhatsApp real | Escopo |
| LLM | Claude pela API da Anthropic por variável de ambiente; **mock offline determinístico** para testes e demo. O log do entregável sai com o LLM real | O avaliador provavelmente não tem chave |
| Modelo por passo | **Provisório** até a medição real (seção 5) | Depende de números que ainda não existem |
| Fixtures de eval | Turnos do lead **mascarados**, derivados do **texto**. Colunas que vazam gabarito só na checagem de sanidade, marcada como tal | Evita contaminar a avaliação |
| Casos de handoff | Sintéticos, escritos à mão (o dataset não tem nenhum) | Cobertura que os dados não dão |

## 4. Política de cotação

Modelo e script: `analysis/latency_sim.py` (200 mil cotações por política; `analysis/results/latency_sim.md`). Orçamento de 15s, no máximo 4 chamadas.

**Nominal (5xx 20% / lenta 10%)**

| Política | p50 | p95 | p99 | Sem cotação em 15s | Chamadas por cotação |
|---|---|---|---|---|---|
| A) timeout 2s + retry | 0,19s | 2,5s | 4,8s | 0,78% | 1,42 |
| **B) timeout 10s, retry só em 5xx** | 0,19s | 8,0s | 8,4s | **0,15%** | **1,25** |
| C) hedge aos 2s (descartada) | 0,19s | 2,5s | 6,1s | 0,15% | 1,42 |

**Degradado (5xx 50% / lenta 20%)**

| Política | p50 | p95 | Sem cotação em 15s | Chamadas por cotação |
|---|---|---|---|---|
| A | 0,50s | 4,2s | 23,9% | 2,53 |
| **B** | 0,97s | 9,0s | **6,2%** | **1,87** |
| C | 0,97s | 8,9s | 6,2% | 2,53 |

Parâmetros do cliente (configuráveis): `timeout_s=10`, `max_calls=4`, `budget_s=15` (recebe o prazo restante do turno), backoff base 0,3s com jitter.
**Propriedade testada em comportamento, não em texto:** em nenhuma cotação há mais de uma chamada em voo. Hoje o teste roda no simulador
(com a política C como controle negativo); na 2a roda no **cliente real** com transporte falso e relógio virtual.
**Limite do modelo:** o "8s fixo e independente da carga" é do mock; num legado real as falhas se correlacionam.

## 5. Latência fim a fim, modelo por passo e custo (Etapa 1)

### 5.1 Latência por mensagem (LLM + `/quote` + overhead)

Script: `analysis/e2e_latency_sim.py` (`analysis/results/e2e_latency_sim.md`). **A latência do LLM é hipótese, não medição**: três perfis
paramétricos (p50/p95 de uma chamada de extração estruturada). A `/quote` usa o modelo medido (política B).

**Nominal, turno com cotação (LLM no caminho crítico)**

| Perfil LLM (hipótese) | Turno sem cotação p95 | Com cotação p50 | p95 | p99 | "Um instante" | Handoff |
|---|---|---|---|---|---|---|
| rápido (0,8s / 2,0s) | 2,1s | 1,2s | **9,1s** | 10,0s | 16,7% | 0,15% |
| médio (1,8s / 4,5s) | 4,6s | 2,4s | **10,3s** | 12,1s | 45,8% | 0,17% |
| lento (3,5s / 9,0s) | 11,3s | 4,2s | **12,4s** | 17,4s | 82,2% | 3,3% |

p95 de **uma mensagem qualquer** de uma conversa típica (3 respostas por fast-path, 3 só-LLM, 1,5 com cotação): rápido **2,3s**, médio **4,9s**, lento **11,0s**
(degradado: 9,0s / 9,9s / 12,4s).

**Achado:** o p95 de um turno com cotação é dominado pelo modo lento de 8s da `/quote` (8,1s sozinha), não pelo LLM, que soma só 1 a 2s com perfil rápido ou médio.
O LLM decide sozinho a latência dos turnos **sem** cotação.

**Critérios de aceitação (proposta; confirmar):** C1 silêncio máximo de 3s (garantido pela mensagem "um instante" aos 2,5s **desde a chegada da mensagem**);
C2 turno sem cotação com p95 ≤ 5s; C3 turno com cotação com p95 ≤ 12s; C4 pior caso duro de 20s por turno, depois disso vira handoff.
Varrendo o p50 do LLM (p95 = 2,5×p50): **C2 quebra entre p50 = 1,5s e 2,0s** (LLM p95 ≈ 4–5s); **C3 aguenta até p50 = 2,0s** e quebra a partir de 3,0s.
Ou seja, C2 é a restrição que decide o modelo.

**O corte, em ordem de efeito:**

1. **Fast-path por regex** para o slot esperado quando a resposta é simples (ano, idade, CEP, data), com queda para o LLM se não casar. Tira o LLM de ~40% dos turnos
   e, no último slot (data), **tira o LLM do caminho crítico da cotação**: o p95 do turno com cotação volta a 8,1s, qualquer que seja o modelo.
2. **Modelo pequeno na extração** (seção 5.2). Troca ~1 a 2s de p95 nos turnos sem cotação.
3. **"Um instante" aos 2,5s só em turno que vai chamar a `/quote`**; nos demais, aos 4s. Com perfil médio, 30% dos turnos só-LLM disparariam a mensagem aos 2,5s, e isso é ruído.
4. **Teto duro por chamada de LLM**: timeout de 6s com 1 retry; estourou, resposta determinística ou handoff `SAFETY_GUARD`. Prazo de 20s por turno.

### 5.2 Modelo por passo (provisório)

| Passo | Modelo | Configuração |
|---|---|---|
| Extração de slots e intenção (toda mensagem que o fast-path não resolve) | `claude-haiku-5-5` | `effort: low`, saída estruturada (`output_config.format`), **sem `temperature`** (valor fora do padrão dá 400 neste modelo), `max_tokens` com folga para o raciocínio |
| Escalonamento (saída inválida, ambígua ou de baixa confiança) | `claude-sonnet-5-5` | Uma tentativa; orçamento de até 10% das chamadas |
| Redação das mensagens | nenhum | Template (números vêm da API) |
| Resumo do handoff | nenhum | Determinístico a partir dos slots |
| Opus | não usar | Sem ganho justificável para extração estruturada |

Consequência: **sem `temperature=0`, o modo real não é determinístico**. Só o mock é. Os testes que dependem de reprodutibilidade rodam no mock.
Cache do prefixo estático (`cache_control`) só liga com tráfego contínuo (ver abaixo); no demo fica desligado (`LLM_PROMPT_CACHE=off`).

### 5.3 Custo por conversa

Script: `analysis/cost_model.py` (`analysis/results/cost_model.md`). **Tokens são estimativa (±35%)**; preços da tabela da skill `claude-api` (2026-10-06), a conferir.
Por chamada: ~1.500 tokens de prefixo estático (cacheável, mínimo de 512), ~440 dinâmicos, ~110 de saída.

| Conversa | Entrada total | Dela, do cache (hit 95%) | Saída |
|---|---|---|---|
| com fast-path (5 chamadas) | 9.700 | 7.125 | 550 |
| sem fast-path (8 chamadas) | 15.520 | 11.400 | 880 |
| difícil (12 chamadas) | 23.280 | 17.100 | 1.320 |

| Estratégia (USD por conversa) | 5 chamadas, sem cache / hit 95% | 8 chamadas, sem cache / hit 95% | Por 1.000 conversas (8 chamadas, hit 95%) |
|---|---|---|---|
| **Haiku 5.5** | $0,0013 / $0,0006 | $0,0020 / $0,0010 | $0,98 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | $0,0037 / $0,0031 | $0,0060 / $0,0050 | $4,97 |
| Sonnet 5.5 | $0,0249 / $0,0123 | $0,0398 / $0,0196 | $19,62 |
| Opus 5.5 | $0,0498 / $0,0231 | $0,0797 / $0,0370 | $36,96 |

Leituras: **custo não é a restrição** (centavos por conversa); latência e precisão de extração decidem o modelo. O escalonamento de 10% é o que mais pesa
no custo (triplica o do Haiku puro), mas ainda custa menos de US$ 5 por mil conversas. Raciocínio residual de 250 tokens por chamada leva o Haiku de $0,0020 para $0,0030 (8 chamadas).
O cache do prefixo só compensa com taxa de acerto > **21,7%** (abaixo, o prêmio de escrita de 1,25× custa mais do que poupa); como o prefixo é igual em todas as conversas,
o acerto depende do **tráfego total**, não da pressa de cada lead.

### 5.4 O que medir com o modelo real (Etapa 4a, executada pelo autor)

Um `make smoke-llm` com ~15 mensagens de lead mascaradas e reais em estilo, rodando por modelo candidato, registrando:

1. latência por chamada (p50/p95/p99), com os prompts reais e o schema real, ao longo de mais de uma hora do dia;
2. `usage` de cada resposta: entrada, saída, leitura e escrita de cache, e tokens de raciocínio a `effort: low`;
3. taxa de saída estruturada válida sem retry, `max_tokens` atingido, recusas, 429/5xx/timeouts;
4. precisão de extração contra o gabarito dos fixtures (slots corretos, ambiguidade sinalizada) por modelo;
5. taxa de acerto de cache com as pausas reais entre mensagens.

**Regra de decisão:** o menor modelo com extração ≥ 98% correta no fixture e p95 por chamada ≤ 3s; senão escala. Os números das seções 5.1 e 5.3 são recalibrados com essa medição.

## 6. Handoff

Motivos (enum fixo e versionado em `HandoffReason`; um teste garante que esta tabela e o enum não divergem):

| Código | Quando |
|---|---|
| `QUOTE_UNAVAILABLE` | Orçamento esgotado ou breaker aberto. O pacote leva o veredito da pré-checagem, se houver |
| `HUMAN_REQUESTED` | O lead pede uma pessoa |
| `COMPLAINT` | Reclamação |
| `CLAIM_SINISTRO` | Sinistro/acidente |
| `CANCELLATION` | Cancelamento |
| `DATA_AMBIGUOUS` | Ano-modelo futuro; CEP inválido após 2 tentativas; necessidade de cobertura ambígua após 2 tentativas; 400 inesperado da API |
| `MEDIA_UNREADABLE` | Áudio/imagem/documento sem texto utilizável após pedir que escreva |
| `READY_TO_CLOSE` | Lead quer fechar; emissão e pagamento não são do agente |
| `CONVERSATION_STALLED` | Perguntas repetidas sem avanço |
| `PRICE_OBJECTION` | Hesitou depois da alternativa (ou não há alternativa mais barata) |
| `OUT_OF_SCOPE` | Fora de cotação de seguro auto |
| `SAFETY_GUARD` | Guardrail ou LLM falhou; tentativa de injeção detectada |

**Pacote** (`HandoffPackage`, imutável, sem identificadores diretos): `reason`, `trace_id`, `created_at` (UTC), `qualification` (só idade, ano do veículo, CEP, plano, data de início),
`missing`, `last_quote` (`quote_id`, plano, status, valor), `precheck`, até 10 mensagens recentes **já mascaradas** e `told_to_lead`, o texto exato dito ao lead.
O pacote não existe sem `told_to_lead`, sem fuso horário, nem com campo de qualificação fora da lista.

**Destino** (`HandoffSink`, sincrono): `deliver(package) -> DeliveryReceipt`. Contrato: idempotente por `trace_id`; não altera o pacote; falha transitória é
`SinkUnavailable` e falha permanente é `SinkRejected`; nunca perde o pacote em silêncio. O SQLite é o registro de rastreabilidade e **sempre** existe; um CRM ou fila entra
**além** dele. Ordem no orquestrador: grava no SQLite, responde ao lead, entrega ao sink; se o sink falhar, o handoff fica `pending` e o que foi dito ao lead continua verdadeiro.
A suíte `tests/sink_contract.py` é o critério de aceitação de qualquer destino; ela já tem controle negativo (sink que duplica, sink que vaza a exceção errada).

**Texto ao lead (princípios, testados por motivo):** diz que um consultor dará continuidade; diz que o que ele contou ficou registrado; **não** promete prazo, horário, canal nem desconto;
só cita valor se houver cotação verificada; em `QUOTE_UNAVAILABLE` diz que não passará valor sem confirmação do sistema.

## 7. Fluxo de qualificação

Ordem: **ano do veículo → idade → (pré-checagem) → CEP → necessidade → data de início → cotar → apresentar**.

- **Necessidade → plano.** Três opções em linguagem simples, derivadas das coberturas do `/planos`: só roubo, furto e colisão (Essencial); com danos a terceiros e vidros (Completo); com carro reserva e assistência 24h (Premium). Mapeia o menor plano que cobre o pedido. Ambíguo: pergunta de novo uma vez; depois `DATA_AMBIGUOUS`.
- **Pré-checagem.** Só quando prevê recusa o agente faz uma chamada de confirmação (idade e ano apenas). Se a API disser 200, a divergência é registrada, esse preço parcial **nunca** é exibido, e o fluxo segue. Se a API estiver fora, handoff `QUOTE_UNAVAILABLE` com o veredito no pacote. Nunca diz "recusado" sem a API.
- **Apresentação.** Sempre: recap dos dados usados, mensalidade, primeiro pagamento (pro-rata, quando houver), franquia e carência de 30 dias para roubo/furto. Confirmação antes de cotar só quando a extração veio ambígua ou implausível.
- **Higiene de entrada (não é regra de negócio):** CEP como string de 8 dígitos, obrigatório; `plano_id` sempre explícito e conferido na resposta; `data_inicio` hoje ou futura; ano-modelo futuro vai ao humano.

## 8. Persistência (SQLite, 4 tabelas)

| Tabela | Pergunta de rastreabilidade |
|---|---|
| `conversations` | Como terminou (`quoted`, `refused`, `handoff` + motivo, `open`)? Qual era o estado (slots) e qual pacote foi entregue ao humano? |
| `messages` | O que foi dito, por quem, em que ordem? Esta mensagem já foi processada (dedupe por id do canal)? Que cotação ela exibe (`quote_id`)? O que o LLM e o guardrail fizeram (`meta`, com `usage`)? |
| `quotes` | Que cotação o lead recebeu, para qual entrada normalizada, com que status e valor? Foi cotação, alternativa ou confirmação da pré-checagem? |
| `quote_attempts` | Como a `/quote` chegou a esse resultado: quantas tentativas, que status HTTP, quanto tempo, por que parou? (A pergunta central do desafio.) |

**Cortadas, com motivo:** `refusals` (uma recusa é uma linha de `quotes` com `status='refused'`; a conversa termina com `outcome='refused'`), `llm_calls` (vai em `messages.meta`),
`handoffs` (é 1:1 com a conversa, então é estado dela). A invariante do princípio 1 é uma consulta: todo "R$" em `messages` do agente existe em `quotes.response` do mesmo `trace_id`.
Um espelho JSONL (uma linha por evento, sempre com `trace_id`) alimenta o log exportável. **Nunca persistido:** texto cru, CPF, e-mail, telefone, nome, placa, prompts.
Se faltar tempo, `quote_attempts` vira coluna JSON em `quotes`.

## 9. Estrutura do repositório

```
src/autoseguro/      produto (hoje: handoff.py; depois domínio, cliente de cotação, LLM, orquestrador, persistência)
analysis/            scripts de análise (agregados apenas) e analysis/results/
tests/               unitários, higiene, contrato de destino, integration/
docs/                PLAN.md, FINDINGS.md
vendor/              TUDO que veio do desafio, sem modificação (NOTICE.md, vendor/quote-service.sha256)
ai-logs/             conversas com IA, limpas (Etapa 8)
```

## 10. Etapas

Tamanho: P (pequena), M (média), G (grande). **Marco:** a fatia de ponta a ponta fica pronta ao fim da 2b.

### Etapa 0 — Fundação · P · ✅
Repo, `vendor/` com checksum, composes, `analysis/` sanitizado, FINDINGS, plano, higiene.
**Testes:** sem PII/segredo (com teste do scanner); sem linha crua do dataset (controle negativo feito); `vendor/quote-service/` idêntico ao original;
tabela de latência reproduzida pelo script; saída da análise sem texto de mensagem; API de teste sobe e responde. Validado em Python 3.14 (host) e 3.12 (container); `make api-up` real.

### Etapa 1 — Decisões de desenho · P · ✅
Latência fim a fim, modelo por passo, custo, interface do destino do handoff (seções 5 e 6).
**Testes:** os números das seções 4 e 5 são reproduzidos pelos scripts (janelas robustas ao ruído); contrato de destino com controle negativo; enum e tabela de motivos sincronizados.

### Etapa 2a — Cliente de cotação · M · **próxima; para aqui**
Normalização de slots; resultado tipado (`Quote`, `Refused`, `InvalidInput`, `Transient`, `Unavailable`); política B; classificação pelo **corpo** (os dois 422); `plano_id` da resposta conferido;
recebe o prazo restante do turno; callback de "um instante". Sem circuit breaker (ver seção 11).
**Testes (relógio virtual, sem `sleep`):** 5xx×3 e depois 200; 5xx×4 → `Unavailable` antes de 15s; resposta lenta de 8s dispara o callback uma vez; 422 de negócio e de pydantic sem retry; 400 sem retry;
502 com HTML; 200 com plano trocado descartado; prazo restante menor que 15s respeitado. **Nunca mais de uma chamada em voo** (cliente real, todas as sequências acima).
Reprodução da simulação de latência com o cliente real (p50/p95 dentro de tolerância). Normalizadores nas bordas (CEP sem zero à esquerda, plano com espaço, data passada).

### Etapa 2b — Fatia vertical · G
Terminal, `MockLLM` determinístico com fast-path, orquestrador (máquina de estados), mascarador de PII, SQLite (4 tabelas), `SqliteSink`, pacote de handoff.
Cobre: caminho feliz, recusa da API, `QUOTE_UNAVAILABLE`, `HUMAN_REQUESTED`.
**Testes:** conversa completa por plano contra a API de teste; recusa registrada fora de handoff; queda total (transporte falso) → handoff com pacote completo e texto honesto; invariante "todo R$ existe em `quotes`";
toda mensagem/cotação/tentativa com id e status; reconstrução pelo `trace_id`; dedupe de reentrega; `SqliteSink` passa em `SinkContract`; varredura de PII no banco e nos logs,
com formatos **além** dos do dataset (CPF sem pontuação, telefone com parênteses, e-mail com `+`, placa antiga, colisão telefone vs CEP); fast-path e LLM dão a mesma extração nas mesmas entradas.

### Etapa 4a — ClaudeLLM mínimo e medição real · M · feita pelo autor na parte de chamada
`ClaudeLLM` (extração e intenção por saída estruturada) e `make smoke-llm` (seção 5.4). **Vem logo após a 2b** para a medição real chegar cedo, e não só no fim.
Antes de escrever, consulto a documentação atual do SDK.
**Testes:** mesmo conjunto de cenários no mock e (opt-in, `-m llm_real`) no Claude; falha/timeout do LLM; `usage` registrado em `messages.meta`.

### Etapa 3 — Cobertura de handoff e experiência · G
Todos os motivos de handoff; pré-checagem e chamada de confirmação; necessidade → plano; objeção de preço; correções; CEP inválido; ano-modelo futuro; mídia.
**Testes:** **contrato da pré-checagem contra a API real**: bordas derivadas do próprio `/planos` (cada limite ±1, extremos, ano futuro) mais amostra aleatória com semente registrada. Divergência "pré-checagem recusa e a API aceita" falha o teste.
Um cenário escrito à mão por motivo de handoff. Mapa necessidade → plano. Objeção: alternativa real uma vez, segunda hesitação → `PRICE_OBJECTION`, sem texto de desconto. Nenhuma recusa dita sem confirmação da API.

### Etapa 4b — Endurecimento do LLM · P
**Testes:** **mock hostil** que tenta emitir preço, plano inexistente, prazo ou desconto (o guardrail barra todos); injeção de prompt no texto do lead.

### Etapa 5 — Webhook FastAPI · M · **bônus**
`POST /webhook/inbound` (202, segundo plano), `GET /conversations/{trace_id}/messages`, `GET /handoffs`; lock por conversa.
**Testes:** dedupe, ordem, concorrência na mesma conversa, "um instante" antes da resposta final.

### Etapa 6 — Evals completos · M · **bônus**
Fixtures derivados do texto (mascarado) com simulador de lead; conjunto sintético de handoff; runner e relatório. O oráculo é a API de teste.
**Gates:** 0 preço inventado; 100% dos motivos corretos no sintético; 100% das recusas iguais às da API.
(Os cenários de handoff escritos à mão da Etapa 3 já funcionam como conjunto sintético mínimo.)

### Etapa 7 — Execução com LLM real e log · P · feita pelo autor
Chave no `.env` (ignorado pelo git), no shell de quem roda. Semente escolhida para o log mostrar uma falha seguida de retry. Exporto o log do banco.

### Etapa 8 — Documentação e entrega · M
README final (a partir de `FINDINGS.md`), decisões, curadoria de `ai-logs/` (só as sessões deste desafio; limpeza de e-mail, caminho de home e PII sintética, com scanner como teste). Publicar no GitHub é ação do autor.

## 11. Se o tempo apertar

Cortar nesta ordem (o primeiro é o mais barato de perder):

1. Circuit breaker e teto de retry (o orçamento e `max_calls` já limitam; documentar o limite). **Já fora da 2a.**
2. Amostra aleatória do teste de contrato da pré-checagem (as bordas ficam). Se mesmo assim estourar, a pré-checagem inteira sai e o resto do plano não muda.
3. `quote_attempts` como coluna JSON em `quotes`.
4. LLM só extrai e classifica; todo texto ao lead vira template (já é o desenho; é o piso).
5. Etapas 5 e 6 já são bônus.

**Não cortar:** cliente resiliente (B), invariante de preço, pacote de handoff e motivos, rastreabilidade, mascaramento, modo mock, README, `ai-logs/` e o log com LLM real.

## 12. Limites conhecidos

- A simulação de latência segue o mock (8s fixo, falhas independentes). A latência do LLM é **hipótese** até a Etapa 4a.
- Os tokens por chamada são estimativas (±35%); o prompt real ainda não existe.
- O mascaramento por regex mais nomes conhecidos é um piso, não uma garantia; vale também para formatos que o dataset não tem.
- A pré-checagem duplica semântica (ano atual menos ano do veículo, buraco abaixo de 18 anos). O teste de contrato a mantém honesta; se deixar de compensar, ela sai sem afetar o resto.
- O relógio do servidor define a idade do veículo (UTC no container); perto de 31/12 o Brasil e o servidor discordam por algumas horas.
- O modo real não é determinístico (sem `temperature` neste modelo): só o mock reproduz.
