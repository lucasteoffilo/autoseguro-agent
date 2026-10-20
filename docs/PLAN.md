# Plano de implementação

> **Estado (2026-10-20):** Etapas 0 e 1 commitadas. **Etapa 2a escrita, aguardando revisão e o smoke** (código na árvore de trabalho, sem commit).
> **Mudança de escopo (D4):** a camada de LLM é agnóstica de provedor e o default é o OpenRouter, porque não há acesso à API direta da Anthropic (seções 5.3 a 5.5).
> A **2b só começa depois do `smoke-llm`** rodado pelo autor com o modelo real (seção 5.4): ele é o maior risco do plano e ainda não foi rodado.

## 1. Escopo e tempo (~5 horas)

**Mínimo que precisa funcionar:** o agente conduz a conversa, cota com retry e passa ao humano nos casos deste plano, tudo rastreável e **sem preço inventado**,
**e a entrega fechada** (Etapa 8). Isso é: 2a ✅, 2b, 3, 4, 7 e 8. **Bônus, só se sobrar tempo:** webhook e concorrência (Etapa 5) e evals completos (Etapa 6).

| Etapa | Limite | Estado |
|---|---|---|
| 2a (cliente de cotação, guardrail, camada de LLM, `smoke-llm`) | 90 min (+ a troca de provedor, fora do limite original) | escrita; falta o smoke real |
| 2b (fatia vertical) | 90 min | — |
| 3 (cobertura de handoff e experiência) | 50 min | — |
| 4 (endurecimento do LLM) | 15 min | — |
| 7 (log com LLM real, feito pelo autor) | 15 min | — |
| 8 (**entrega**, com critérios de aceite) | 40 min | — |
| **Total** | **300 min (5h00), sem folga** | |

**A entrega é a última a ser cortada.** Se qualquer etapa estourar, o que encolhe primeiro é a Etapa 3 (seção 13). **Corte pré-autorizado, sem discussão:** se a 2b passar de 90 min, sai o **circuit breaker** e o `quote_attempts` vira coluna JSON em `quotes`.

## 2. Princípios (cada um vira um teste)

1. **Preço só sai da API.** O LLM redige a conversa, mas **nunca número, prazo nem promessa**. Mensagens de cotação, recusa e handoff são template preenchido com a resposta da API. O texto livre do LLM só pode afirmar o que está numa **base de fatos injetada a partir do `/planos`**, passa por um guardrail e, reprovado, cai para o template do passo.
2. **Na dúvida, atrasar ou passar ao humano.** Preço errado é pior que preço atrasado. Nunca estimar, arredondar ou "chutar" cotação, nem com a API fora do ar.
3. **A API é a palavra final.** A pré-checagem de elegibilidade só melhora a experiência; nenhuma recusa é comunicada ao lead sem confirmação da API.
4. **Tudo rastreável.** Toda mensagem, cotação e tentativa tem id e status, ligados por um `trace_id`.
5. **PII mínima.** Identificadores diretos nunca são persistidos nem enviados ao LLM. Os insumos da cotação (idade, ano, CEP, plano, data) ficam como slots. **Nada sai da máquina sem passar pelo detector de PII**; até a 2b (que traz o mascarador) só mensagens escritas à mão e sem PII podem ser enviadas.
6. **Não prometer o que o canal não garante.** Nada de prazo, horário ou canal de continuidade no texto de handoff nem no `reply` do LLM.
7. **Nunca silêncio.** Toda mensagem do lead recebe uma resposta visível em até 20s: resposta, cotação, recusa ou handoff.
8. **A causa raiz decide o código, e se registra onde falhou.** Todo handoff por falha leva o **motivo** e o **componente que falhou**; os dois vão no log e no pacote.

## 3. Decisões fechadas

| Tema | Decisão | Por quê |
|---|---|---|
| Critério de latência | **Um só: p95 do turno ≤ 5s sem cotação e ≤ 12s com cotação.** O "um instante" aos 2,5s e o teto de 20s são mecanismos, não critérios. O limite por chamada de LLM é **derivado** do critério (seção 5.1) | Um número solto vira discussão; um derivado vira consequência |
| Cliente de cotação | **Política B**: timeout 10s, retry só em 5xx/429/conexão/corpo inválido, no máximo 4 chamadas, **no máximo uma em voo**, backoff com jitter, orçamento de 15s (e nunca além do prazo restante do turno) | Menor carga e menor taxa de falha entre as opções simples (seção 4) |
| Hedging | **Descartado.** Não existe parâmetro de hedging no código; o teste que o impede é de comportamento (uma chamada em voo), com controle negativo no cliente | Corta o p95 de 8s para 2,5s, mas custa +14% de chamadas (+35% degradado) |
| Texto ao lead | **O LLM redige os turnos de conversa** (saudação, próxima pergunta, explicação de carência, dúvida, objeção) **na mesma chamada que extrai os slots**: `{slots, intent, facts_used, reply}`, sem chamada extra. **`reply` de no máximo ~40 palavras** (WhatsApp). **Template fixo só em cotação e handoff**, que carregam número e promessa | O desafio pede conversa, não bot de formulário |
| Base de fatos | O `reply` **só pode afirmar o que está numa base de fatos derivada do `/planos`**. O LLM declara em `facts_used` em quais se apoiou; **todo número do `reply` tem que estar nesses fatos ou ecoar um dado que o lead escreveu**. Reprovou: template | Regex não pega fato errado; restringir o material pega a classe de erro que importa (seção 6) |
| Fast-path por regex | **Nasce desligado.** Só valeria para resposta direta ao slot perguntado com valor inequívoco; o `smoke-llm` mede a divergência regex vs LLM e, se divergir, **sai** | Risco de extrair o slot errado em silêncio; ganho pequeno (seção 5.1) |
| Falha do LLM antes da cotação | `SAFETY_GUARD` com componente `llm`; falha da `/quote` ou teto estourado na cotação: `QUOTE_UNAVAILABLE` com componente `quote_api`. **Motivo e componente sempre logados** | A causa raiz decide o código |
| Handoff | Pacote com **código fixo de motivo**, resumo da qualificação, última cotação com id, `trace_id` e componente que falhou. O agente diz ao lead, com honestidade, o que acontece depois | Humano assume sem refazer perguntas |
| Destino do handoff | **Interface `HandoffSink`**; padrão SQLite. CRM ou fila entram **além** do SQLite | Contrato e suíte de teste já existem (seção 7) |
| Texto do handoff | **Genérico**: não promete prazo, horário nem canal. O SLA real é configuração de negócio (`HANDOFF_NEXT_STEP_TEXT`, opcional) | Só é verdade o que o canal garante |
| Teto de 20s por turno | Mensagem honesta + handoff, **nunca silêncio** (seção 5.2) | Critério aprovado |
| Recusa por regra | Explica e encerra. Registrada como **recusa**, separada de handoff | A recusa é decisão de negócio da API |
| Objeção de preço | Uma alternativa real via API; se hesitar de novo, handoff `PRICE_OBJECTION`. Nunca promete desconto | O humano pode negociar |
| Plano | Pergunta a **necessidade em linguagem simples**; o agente mapeia para um plano, cota **um** e oferece comparar | O lead não conhece "Essencial/Completo/Premium" |
| Pré-checagem | Mantida **por experiência**. Lê as faixas do `/planos`. Contrato contra a API real: **bordas + amostra aleatória** | A API manda; divergência é detectada, não presumida |
| `smoke-llm` | **Escrito na 2a.** Só mensagens **escritas à mão, realistas e bagunçadas, sem PII**. **Cabe no free tier do OpenRouter: 1 modelo, 2 repetições, 31 requisições.** O autor roda com a chave no `.env` durante a pausa | É o maior risco do plano; medir antes de construir em cima |
| Python | **`>= 3.12`**, verificado em 3.12 (container) e 3.14 (host); a 3.13 não foi testada | Não se declara o que não se verificou |
| Interface | Terminal + webhook fino em FastAPI (bônus). Sem WhatsApp real | Escopo |
| LLM | **Agnóstico de provedor (D4).** Interface `LLMClient`; adaptadores `OpenAICompatLLM` (stdlib; **OpenRouter é o default**) e `ClaudeLLM` (opção, API direta da Anthropic). Escolha por env (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`). **Mock offline determinístico** para testes e demo. O log do entregável sai com o LLM real e **cita provedor e modelo** | Só há acesso ao OpenRouter; o avaliador provavelmente não tem chave |
| Proteções | **O gate de PII e o guardrail ficam em `GuardedLLM`, acima de qualquer adaptador**; a fábrica só devolve LLM embrulhado nele. Teste parametrizado nos dois adaptadores, com controle negativo | Trocar de provedor não pode contornar nenhum dos dois |
| Chave | A chave do OpenRouter **nunca** passa pelo `ClaudeLLM` (parâmetros da Anthropic que o OpenRouter não garante), a da Anthropic não vai a outro provedor, e nenhuma aparece em log, erro, relatório nem saída (`redact` + teste) | Vazamento de chave |
| Saída estruturada | `response_format` `json_schema` só se o modelo suportar (conferido na documentação, seção 5.5), com `require_parameters`. **O provedor não é confiado:** valida-se com o schema local, e saída inválida cai no template ou escala | Provedor e modelo mudam; o contrato é nosso |
| Modelo por passo | **A escolher no `smoke-llm`**, pelo critério de sempre: 0 extrações erradas em silêncio, 100% de saída válida, p95 projetado do turno (seção 5.3) | Depende de números que ainda não existem |
| Entrega | **Etapa 8 com critérios de aceite verificáveis**; sem ela fechada, o trabalho não está pronto (seção 12) | A avaliação inclui README, `ai-logs/` e o log da execução |

## 4. Política de cotação

Modelo e script: `analysis/latency_sim.py`. Orçamento de 15s, no máximo 4 chamadas.

**Nominal (5xx 20% / lenta 10%)**

| Política | p50 | p95 | p99 | Sem cotação em 15s | Chamadas por cotação |
|---|---|---|---|---|---|
| A) timeout 2s + retry | 0,19s | 2,5s | 4,8s | 0,78% | 1,42 |
| **B) timeout 10s, retry só em 5xx** | 0,19s | 8,0s | 8,4s | **0,15%** | **1,25** |
| C) hedge aos 2s (descartada) | 0,19s | 2,5s | 6,1s | 0,15% | 1,42 |

**Degradado (5xx 50% / lenta 20%)**: B tem 6,2% sem cotação e 1,87 chamada por cotação; A, 23,9% e 2,53; C, 6,2% e 2,53.

**Verificação com o cliente real (2a):** (a) com relógio virtual e a distribuição do simulador, 12.000 cotações: p50 0,19s, p95 8,04s, 1,24 chamada por cotação e 0,07% sem cotação (simulador: 0,19s, 8,04s, 1,25 e 0,13%);
(b) **HTTP e tempo reais contra a API instável de verdade**, 60 cotações em paralelo: 60 `Quote`, 1,28 chamada por cotação, p95 8,03s, o "um instante" disparou nas 8 cotações acima de 2,5s e em nenhuma outra, 0 preço incoerente.

## 5. Latência fim a fim, modelo por passo e custo

### 5.1 Latência por mensagem e o limite por chamada (derivado)

Script: `analysis/e2e_latency_sim.py` (`analysis/results/e2e_latency_sim.md`). **A latência do LLM é hipótese, não medição**: perfis paramétricos, p50 = TTFT + tokens de saída ÷ velocidade, p95 = 2,5×p50.

**O `reply` curto resolve o perfil médio? p95 do turno, nominal (critério: 5s sem cotação, 12s com)**

| Saída da chamada | Tokens | rápido (sem / com cotação) | médio (sem / com cotação) | lento (sem / com cotação) |
|---|---|---|---|---|
| só slots verbosos (antes de o LLM redigir) | 110 | 2,1s ✅ / 9,1s ✅ | 4,7s ✅ / 10,3s ✅ | 11,1s ❌ / 12,4s ❌ |
| `reply` sem teto (~50 palavras) | 190 | 2,9s ✅ / 9,5s ✅ | 8,5s ❌ / 11,7s ✅ | 12,4s ❌ / 13,0s ❌ |
| `reply` ≤ 40 palavras | 183 | 2,8s ✅ / 9,5s ✅ | 8,3s ❌ / 11,5s ✅ | 12,4s ❌ / 13,0s ❌ |
| **≤ 40 palavras + slots em lista compacta (desenho atual)** | **128** | **2,3s ✅ / 9,2s ✅** | **5,2s ❌ / 10,6s ✅** | 12,3s ❌ / 12,6s ❌ |

**Conclusão (ajuste 1):** o teto de 40 palavras **sozinho não resolve** o perfil médio (8,5s → 8,3s): a maior parte dos tokens é estrutura e slots, não o texto. O que aproxima é a **lista compacta de slots** (5,2s), e mesmo assim o médio fica **a 3% do critério, sem margem**.
O perfil rápido tem folga em todos os cenários. Logo: o modelo da chamada única tem que ser pequeno, e a margem do médio é o que o `smoke-llm` precisa confirmar ou desmentir.

**Limite por chamada, DERIVADO do critério do turno** (bissecção; p95 = 2,5×p50; `derive_llm_call_limit`):
turno sem cotação (p95 ≤ 5s) → chamada com **p50 ≤ 1,96s, p95 ≤ 4,91s**; turno com cotação (p95 ≤ 12s) → p50 ≤ 2,9s, p95 ≤ 7,24s. **A restrição ativa é o turno sem cotação: p95 por chamada ≤ ~4,9s.**
O `smoke-llm` não compara a latência medida com esse número: ele **projeta o p95 do turno** a partir das latências medidas (`project_turn_p95`) e compara com o critério. O número derivado só aparece no relatório como referência.

**Nominal, perfil e `/quote` (desenho atual, 128 tokens):** só a `/quote` (sem LLM) tem p95 de 8,1s. Turno com cotação: rápido 9,2s (p99 10,2s, handoff 0,15%), médio 10,6s (p99 12,6s), lento 12,6s (handoff 5,3%).
Degradado: rápido 10,4s (handoff 6,3%), médio 12,4s, lento 16,9s. **O p95 de um turno com cotação continua dominado pelo modo lento de 8s da `/quote`.**

**Fast-path estrito (cobertura de 0% / 30% / 40%), p95 de uma mensagem qualquer:** rápido 2,7 / 2,6 / 2,5s; médio 7,1 / 5,7 / 5,5s. Rende pouco com o LLM rápido, e é por isso que nasce desligado.

### 5.2 O teto de 20s e o "um instante"

1. **Teto estourado com a `/quote` em andamento, ou sem prazo restante para ela** → mensagem honesta ("não consegui gerar sua cotação agora por uma instabilidade no nosso sistema; não vou te passar valor sem a confirmação dele") **e** handoff `QUOTE_UNAVAILABLE`, componente `quote_api`. **Nunca silêncio.**
2. **Falha do LLM antes de a cotação ser pedida** (6s de timeout, 1 retry) → mesma honestidade na mensagem, mas o motivo é **`SAFETY_GUARD`, componente `llm`** (decisão: a causa raiz decide o código; **os dois são logados**).
3. **"Um instante"** aos 2,5s desde a chegada da mensagem (mecanismo que garante silêncio ≤ 3s). Em turno de cotação, o `reply` do LLM pode servir de confirmação ("vou calcular agora"), se passar pelo guardrail.
4. **Cobertura por teste:** o cliente da `/quote` devolve **sempre** um resultado terminal dentro do prazo recebido (1.500 roteiros aleatórios + matriz roteirizada); o orquestrador (2b) repete a propriedade no nível do turno: exatamente uma mensagem terminal visível em até 20s.

### 5.3 Modelo por passo (a escolher no smoke) e custo

**Com o OpenRouter (D4) o modelo não está escolhido.** A linha de Haiku/Sonnet abaixo é a configuração de referência para a API da Anthropic (`ClaudeLLM`) e a base da tabela de custo; o modelo do OpenRouter sai do `smoke-llm` pelo critério da seção 5.4. Só o preço muda de modelo para modelo, o formato `{slots, intent, facts_used, reply}` e o que o guardrail confere são os mesmos.

| Passo | Modelo | Configuração |
|---|---|---|
| Extração + intenção + resposta de conversa (uma chamada por mensagem) | **a escolher no smoke** (referência Anthropic: `claude-haiku-5-5`; alvo free do smoke: `dots-studio/dots-3-note-preview:free`) | Anthropic: `effort: low`, saída estruturada (`output_config.format`), **sem `temperature`** (400 em valor fora do padrão), `max_tokens` com folga para o raciocínio, **`max_retries=0`** (o retry é nosso). OpenRouter: `response_format` `json_schema`, `reasoning.effort=none`, `max_tokens=800` (raciocínio consome `max_tokens`, seção 5.5), sem retry do lado do adaptador |
| Escalonamento (saída inválida, ambígua ou de baixa confiança) | referência Anthropic: `claude-sonnet-5-5`; no OpenRouter, um modelo maior a definir depois do smoke | Uma tentativa; até 10% das chamadas. **O Sonnet puro fica na fronteira de C2** (seção 5.1) |
| Cotação, recusa e handoff | nenhum | Template |
| Resumo do handoff | nenhum | Determinístico a partir dos slots |
| Opus | não usar | Sem ganho justificável |

Sem `temperature=0`, **o modo real não é determinístico**; só o mock reproduz. O cache do prefixo só liga com tráfego contínuo (acerto > 21,7%); no demo fica desligado.

Script: `analysis/cost_model.py`. **Tokens são estimativa (±35%)**; preços da tabela da skill `claude-api` (2026-10-06), a conferir. **Os preços são os da Anthropic**; o do modelo escolhido no OpenRouter precisa refazer a tabela. Por chamada: ~2.200 de prefixo estático (persona, base de fatos, regras do guardrail, exemplos), ~440 dinâmicos, ~128 de saída.

| Estratégia (8 chamadas) | Sem cache | Cache, hit 95% | Por 1.000 conversas (hit 95%) |
|---|---|---|---|
| **Haiku 5.5** | $0,0026 | $0,0011 | $1,14 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | $0,0079 | $0,0064 | $6,39 |
| Sonnet 5.5 | $0,0525 | $0,0228 | $22,82 |
| Opus 5.5 | $0,1050 | $0,0423 | $42,30 |

**Impacto de o LLM redigir a resposta (8 chamadas):** +32% sem cache e +16% com cache (Haiku). O custo do prefixo maior pesa mais que o do `reply`; saída verbosa (183 tokens) acrescentaria só +7%. **Custo não é a restrição; a latência é.**
Tokens por conversa (hit 95%): 5 chamadas = 13,2K de entrada (10,5K do cache) + 640 de saída; 8 chamadas = 21,1K (16,7K) + 1.024; 12 chamadas = 31,7K (25,1K) + 1.536. Raciocínio residual de 250 tokens/chamada levaria o Haiku de $0,0026 a $0,0036.

### 5.4 `smoke-llm` (escrito na 2a; falta rodar com o modelo real)

`make smoke-llm` roda 15 mensagens **escritas à mão, sem PII** × **2 repetições** × **1 modelo**, com uma chamada de aquecimento fora das estatísticas (a 1ª com um esquema novo paga compilação). Total planejado: **31 requisições** (1 + 15 × 2), dentro dos 50 por dia do free tier.
**Como rodar:** copiar `.env.example` para `.env`, preencher `LLM_API_KEY` (ou `OPENROUTER_API_KEY`), rodar **`make llm-ping`** (preflight, abaixo) e só então `make smoke-llm`. Sem chave, `make smoke-llm-dry` roda o encanamento com um LLM de mentira (números sem valor). A API direta da Anthropic é `make smoke-llm-anthropic`.
**Cota (OpenRouter free):** 20 requisições por minuto e 50 por dia, sem crédito comprado. O smoke (a) espaça as chamadas com 5% de margem sobre o limite por minuto; (b) conta **toda** requisição enviada, inclusive as que falham, em `var/smoke/quota.jsonl` (dia UTC); (c) **aborta antes de gastar** se a contagem local, ou `GET /key` quando responde, mostrar menos de 31 restantes; (d) trata 429 por minuto com espera (`Retry-After` ou recuo exponencial, limitado) e nova tentativa, e 429 diário encerrando a execução e marcando o dia como esgotado. Cada nova tentativa também conta, e o relatório informa quantas requisições foram enviadas e quantas foram retentativas.
**Preflight `make llm-ping` (1 requisição):** confere (1) a autenticação, (2) que o OpenRouter **aceita o pedido como montado** (`json_schema` + `require_parameters` + `reasoning`), (3) que o modelo devolve saída válida no schema local e (4) a latência **dessa amostra** (uma amostra, não p95; a 1ª chamada pode incluir partida a frio). Sem retentativa e sem `GET /key`: é exatamente uma requisição, contada na mesma cota. Imprime `chave: configurada` e nunca o valor, o prefixo nem o tamanho. Códigos de saída: 0 ok, 1 saída inválida, 2 configuração, 3 payload inseguro, 4 cota, 5 inesperado, 6 erro de protocolo, 7 serviço instável ou sem resposta. Se o 404 do `json_schema` + `require_parameters` aparecer, ele diz, e a saída é `LLM_STRUCTURED_OUTPUT=none` ou outro modelo.
**Falha rápido (smoke):** como não sabemos se requisição que falha conta na cota, **o primeiro erro de protocolo custa uma requisição, não 31**: qualquer 4xx exceto 408 e 429 (400, 401, 402, 403, 404…) levanta `ProtocolError` na hora, sem repetir, e o smoke sai com código 6 dizendo a causa provável e quantas requisições gastou. Só o 429 por minuto e as falhas do serviço (408, 5xx) entram em backoff; se `--max-consecutive-failures` (3) chamadas seguidas ainda falham de serviço ou transporte depois do backoff, sai com código 7, para um serviço fora do ar não consumir os 50 do dia em retentativas. Saída inválida do modelo não aborta: é dado do smoke.
**Garantias:** cada mensagem é `hand-written`; o detector de PII roda em **todo** payload (sistema e usuário) e **aborta antes da chamada**; o script não acessa o dataset; **a chave nunca é impressa, gravada nem repetida em erro** (`redact` em toda saída, coberto por `tests/test_key_safety.py`); o relatório, que cita provedor, modelo e modelo servido, vai para `var/smoke/` (ignorado pelo git).

**Mede:** latência por chamada e o **p95 do turno projetado a partir dela** (contra 5s e 12s); tokens/s e `usage`; saída estruturada válida; extração separando **erro silencioso** de omissão; aprovação do guardrail e as violações; **tamanho do `reply` (alvo 40 palavras)**; **divergência regex vs LLM** (decide o fast-path); custo por chamada.
**Passa se:** 0 extrações erradas em silêncio; saída válida em 100%; p95 projetado do turno dentro do critério; guardrail aprova ≥ 80%; ≥ 90% dos replies com ≤ 40 palavras e nenhum acima de 50; nenhum termo proibido.
**O que ele não faz:** 15 mensagens **não certificam taxas** (é um alarme contra problema grosseiro, não um benchmark), e **regex não lê sentido**: a explicação de carência (`m10`), a objeção (`m11`) e a injeção (`m14`) precisam ser lidas a olho no relatório.

### 5.5 OpenRouter: o que foi conferido na documentação (2026-10-20) e o que não foi

Conferido na documentação e no catálogo de modelos **antes de codar**. Em 2026-10-20 o `make llm-ping` exercitou o pedido completo **uma vez, com um modelo** (fim desta seção); os testes automatizados continuam usando um servidor local que imita o formato. O que não foi exercitado pode ter mudado ou estar mal lido.

| Tema | O que a documentação diz | O que fizemos |
|---|---|---|
| Endpoint | `POST /api/v1/chat/completions`, formato OpenAI | `OpenAICompatLLM`, só stdlib |
| Saída estruturada | `response_format: {type: json_schema, json_schema: {strict: true, ...}}`, suportada **por modelo/endpoint** | Ligada por padrão no OpenRouter, com `provider.require_parameters: true` (só roteia para quem suporta todos os parâmetros do pedido). `LLM_STRUCTURED_OUTPUT=none` desliga. **A saída é sempre validada com o schema local**, sem reparo de cerca de código |
| Raciocínio | `reasoning.effort`; os tokens de raciocínio **consomem `max_tokens`** | Padrão `none`. `finish_reason=length` com texto vazio é falha explícita (`max_tokens`), não saída vazia. Se o modelo exigir raciocínio, `LLM_REASONING_EFFORT=low` |
| Erros | Podem vir **dentro de um HTTP 200** (campo `error` no corpo). `error.metadata` traz `provider_name` e `raw`, o retorno bruto do provedor de origem | Tratados como erro; `choices` ausente e `content` nulo também. **O detalhe guarda `provider_name` e `raw`, depois do `redact`** (com `Provider returned error` sozinho não se separa modelo fora do ar de parâmetro recusado). Cabeçalhos do `metadata` não são copiados |
| Free tier | Modelos `:free`: **20 req/min** e **50/dia** abaixo de 10 créditos comprados; o dia é UTC | Seção 5.4 |
| Cota restante | `GET /api/v1/key` informa o uso diário dos modelos free | Consulta antes de gastar; se falhar ou vier em outro formato, segue pela contagem local |
| Raciocínio obrigatório | `GET /api/v1/models` traz `reasoning.mandatory` por modelo (e, em alguns, `supported_efforts`) | Usado para excluir `liquid/lfm-2.5-2.6b:free` (`mandatory: true`) |
| Estado dos endpoints | `GET /api/v1/models/{id}/endpoints` (público) lista os provedores do modelo com `status` e uptime de 30 min e de 1 dia | Usado **uma vez, à mão**, para o 404. O significado dos códigos de `status` **não foi conferido** na documentação; o uptime de 0% bastou. Consultar isso no `llm-ping` está em `docs/BACKLOG.md` |
| **Não dito** | Se requisição que falha (429, 5xx) conta na cota diária | Contamos todas, o que é o lado seguro |

**O contrato:** qualquer modelo com saída estruturada validado pelo `make llm-ping` e pelo `make smoke-llm`. **O alvo do smoke hoje é `dots-studio/dots-3-note-preview:free`** (default da configuração): gratuito, declara `structured_outputs`, `reasoning.mandatory: false`, e passou no ping. É **alvo para medir, não escolha**: o smoke decide pelo critério de 5.4. Se reprovar por latência ou acerto, o próximo passo é outro modelo free (candidatos sem raciocínio obrigatório e com endpoint no ar em 2026-10-20: `xingchen-agi/xing4.0-29b-a4b:free`, `nvidia/nemotron-3.5-super-vl:free`) ou um pago barato, não afrouxar o critério. Ressalvas do alvo: é um preview com `expiration_date` de 2026-12-31 e tem um único provedor listado (AtlasCloud), sem alternativa se cair.
**Fato operacional: endpoints gratuitos oscilam.** O primeiro alvo, `nvidia/nemotron-3-super-120b-a12b:free`, devolveu 404 em 2026-10-20 porque o único provedor dele (Nvidia) estava fora do ar: uptime de 0% nos 30 minutos anteriores e 44% no dia. Diagnóstico com 2 requisições: o pedido pelado (sem `json_schema`, `require_parameters` nem `reasoning`) falhou igual, o que descarta os parâmetros; o `dots-3-note-preview` aceitou o pedido completo e devolveu saída válida (**1 amostra**: 2,15 s, 1328 tokens de entrada, 54 de saída, 0 de raciocínio, reply de 25 palavras aprovado pelo guardrail). Uma amostra não é p95 nem taxa de acerto. Consequência de desenho: o `llm-ping` antes do smoke, a falha rápida em erro de protocolo e **o mock determinístico como o caminho reproduzível** (2b).
A 1328 de entrada, medida por esse modelo, está abaixo dos ~2400 do modelo de custo; é o tokenizador de um modelo, não uma correção do modelo.
**Privacidade:** modelos free podem reter ou treinar com os prompts. Por isso o gate de PII fica ligado em todo caminho e o smoke só envia as 15 mensagens escritas à mão, sem PII. **Dado real do dataset, mesmo mascarado, não vai a modelo free.**

## 6. Guardrail do `reply` e base de fatos

Função pura `check_reply(reply, facts_used, base, lead_texts) -> violações`. Reprovou, o orquestrador usa o template do passo e grava `reply_source=template_fallback` e as violações em `messages.meta`.
A base de fatos (`FactBase.from_planos`) é derivada do `/planos` e **não contém valores em dinheiro** (franquia e mensalidade só existem nos templates de cotação):

| Fato | Autoriza falar de |
|---|---|
| `plano:<id>` (um por plano) | o plano e suas coberturas |
| `planos` | que existem os três planos |
| `carencia` | roubo e furto, e os "30 dias" |
| `pro_rata` | primeiro pagamento proporcional |
| `franquia` | que cada plano tem franquia (sem valor) |

| Regra | Rejeita |
|---|---|
| R1 Sem dinheiro | `R$`, "reais", "mensalidade", "mensais", "parcela", "prêmio", valor decimal, "por mês" |
| R2 Números | Dígitos que não estejam nos fatos citados **nem** no que o **lead escreveu** (mensagem e janela) |
| R3 Sem prazo nem contato | "amanhã", "em breve", "em até N", "horas", "minutos", "retornar", "ligar", "neste mesmo chat"… |
| R4 Sem promessa de condição | "desconto", "promoção", "condição especial", "melhor preço", "grátis"… |
| R5 Sem garantia | "cobre tudo", "sem carência", "garantimos", "100%", "qualquer dano"… |
| R6 Forma | Vazio, mais de 50 palavras, marcação (`<`, `{`, `[`) |
| R7 Fatos | id de fato inexistente; **termo** de cobertura, plano, carência ou franquia **sem fato citado**; **cobertura atribuída ao plano errado** (por sentença); **negação** sobre um desses termos |

**O que garante:** o texto não carrega dinheiro, prazo, desconto nem garantia; todo número tem origem; todo termo de cobertura vem de um fato que o LLM declarou usar; nenhuma cobertura vai para o plano errado.
**O que NÃO garante** (registrado em teste): usando só termos autorizados, uma frase **falsa** passa ("roubo e furto valem desde o primeiro dia", com o fato `carencia` citado). Esse resíduo fica com o prompt e com a leitura humana do `smoke-llm`. A regra de negação é conservadora de propósito: "na carência, roubo ainda não vale" é verdadeira, mas cai no template.

## 7. Handoff

Motivos (enum fixo e versionado em `HandoffReason`; um teste garante que esta tabela e o enum não divergem):

| Código | Quando |
|---|---|
| `QUOTE_UNAVAILABLE` | Orçamento esgotado ou teto de 20s com a `/quote` em andamento. **Exige o componente que falhou** (`quote_api`) |
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
| `SAFETY_GUARD` | LLM ou guardrail falhou; tentativa de injeção detectada. **Exige o componente que falhou** (`llm`, `guardrail`…) |

**Pacote** (`HandoffPackage`, imutável, sem identificadores diretos): `reason`, **`failed_component`** (obrigatório nos dois motivos de falha), `trace_id`, `created_at` (UTC), `qualification` (só idade, ano, CEP, plano, data), `missing`, `last_quote`, `precheck`, até 10 mensagens recentes **já mascaradas** e `told_to_lead`.
**Destino** (`HandoffSink`, síncrono): `deliver(package) -> DeliveryReceipt`; idempotente por `trace_id`; falha transitória é `SinkUnavailable` e permanente é `SinkRejected`. O SQLite é o registro de rastreabilidade e **sempre** existe; um CRM ou fila entra **além** dele. A suíte `tests/sink_contract.py` é o critério de aceitação de qualquer destino (tem controle negativo).
**Texto ao lead (templates):** um consultor dará continuidade; o que ele contou ficou registrado; **não** promete prazo, horário, canal nem desconto; só cita valor se houver cotação verificada.

## 8. Fluxo de qualificação

A cada mensagem o LLM devolve `{slots, intent, facts_used, reply}`. **Quem decide o próximo passo é o orquestrador, pelo estado, e não o LLM.** Ordem: **ano do veículo → idade → (pré-checagem) → CEP → necessidade → data de início → cotar → apresentar**.

- **Conversa (LLM, com guardrail):** saudação, próxima pergunta, explicação de carência, dúvida, objeção. **Template:** cotação, recusa, handoff e o fallback de cada pergunta.
- **Dado incerto:** slot marcado `uncertain` (ou com dois valores) **nunca vira valor**: o agente pergunta de novo. Ano de nascimento não vira idade.
- **Necessidade → plano.** Três opções em linguagem simples, derivadas das coberturas do `/planos`. Mapeia o menor plano que cobre o pedido. Ambíguo: pergunta de novo uma vez; depois `DATA_AMBIGUOUS`.
- **Pré-checagem.** Só quando prevê recusa o agente faz uma chamada de confirmação (idade e ano). Se a API disser 200, a divergência é registrada e o preço parcial **nunca** é exibido. Nunca diz "recusado" sem a API.
- **Apresentação.** Recap dos dados, mensalidade, primeiro pagamento (pro-rata, quando houver), franquia e carência de 30 dias. Confirmação antes de cotar só quando a extração veio ambígua.
- **Higiene de entrada** (`slots.py`): CEP como texto de 8 dígitos, **sem completar zero perdido**; `plano_id` explícito; `data_inicio` hoje ou futura; ano-modelo futuro vai ao humano.

## 9. Persistência (SQLite, 4 tabelas)

| Tabela | Pergunta de rastreabilidade |
|---|---|
| `conversations` | Como terminou (`quoted`, `refused`, `handoff` + motivo + componente, `open`)? Qual era o estado (slots) e qual pacote foi entregue ao humano? |
| `messages` | O que foi dito, por quem, em que ordem? Já foi processada (dedupe)? Que cotação exibe? O que o LLM e o guardrail fizeram (`meta`: `usage`, `facts_used`, `reply_source`, violações)? |
| `quotes` | Que cotação o lead recebeu, para qual entrada normalizada, com que status e valor? Foi cotação, alternativa ou confirmação da pré-checagem? |
| `quote_attempts` | Como a `/quote` chegou a esse resultado: tentativas, status HTTP, tempo, por que parou? (Já produzido pelo cliente: `Attempt`.) |

Cortadas, com motivo: `refusals` (uma recusa é uma linha de `quotes` com `status='refused'`), `llm_calls` (vai em `messages.meta`), `handoffs` (é 1:1 com a conversa, então é estado dela). A invariante do princípio 1 é uma consulta: todo "R$" em `messages` do agente existe em `quotes.response` do mesmo `trace_id`.
**Nunca persistido:** texto cru, CPF, e-mail, telefone, nome, placa, prompts. Se a 2b estourar o limite, `quote_attempts` vira coluna JSON em `quotes` (corte pré-autorizado).

## 10. Estrutura do repositório

```
src/autoseguro/      budgets, slots, facts, guardrail, quote_client, handoff, pii, fastpath (candidato),
                     llm/ (base, config, schema, prompt, openai_compat, claude, guarded, throttle, factory, redact)
                     (2b: mock, orquestrador, templates, mascarador, persistência)
tools/               smoke_llm.py e smoke_messages.py (15 mensagens escritas à mão)
analysis/            scripts de análise (agregados apenas) e analysis/results/
tests/               unitários, higiene, contrato de destino, integration/
docs/                PLAN.md, FINDINGS.md
vendor/              TUDO que veio do desafio, sem modificação (NOTICE.md, vendor/quote-service.sha256)
ai-logs/             conversas com IA, limpas (Etapa 8)
```

## 11. Inventário: o que existe e quando entra

| Componente | Existe? | Onde |
|---|---|---|
| Pacote de handoff (com `failed_component`), motivos, `HandoffSink` e suíte de contrato | ✅ | `handoff.py` |
| Fonte única dos orçamentos de tempo | ✅ | `budgets.py` |
| Normalização de slots | ✅ | `slots.py` |
| Base de fatos e guardrail do `reply` | ✅ | `facts.py`, `guardrail.py` |
| Cliente da `/quote` (política B), resultados tipados, `Attempt` | ✅ | `quote_client.py` |
| Esquema `{slots, intent, facts_used, reply}`, prompt | ✅ | `llm/schema.py`, `llm/prompt.py` |
| Interface `LLMClient`, `OpenAICompatLLM` (OpenRouter), `ClaudeLLM`, configuração por env | ✅ | `llm/base.py`, `openai_compat.py`, `claude.py`, `config.py` |
| `GuardedLLM` (gate de PII + guardrail acima do adaptador), fábrica, cota/rpm/429, `redact` | ✅ | `llm/guarded.py`, `factory.py`, `throttle.py`, `redact.py` |
| Fast-path estrito (candidato, desligado, nada no produto o chama) | ✅ | `fastpath.py` |
| `make llm-ping` (1 requisição), `make smoke-llm` (free tier, 31 requisições, falha rápido) e as 15 mensagens | ✅ (falta rodar com a chave) | `tools/` |
| Detector de PII compartilhado | ✅ | `pii.py` |
| Templates de cotação, recusa e handoff; fallback por passo | ❌ | **2b** |
| `MockLLM`, orquestrador, mascarador, SQLite, `SqliteSink` | ❌ | **2b** |
| Pré-checagem de elegibilidade e teste de contrato | ❌ | **3** |
| Necessidade → plano, objeção, demais motivos de handoff | ❌ | **3** |

## 12. Etapas

### Etapa 0 — Fundação · ✅  ·  Etapa 1 — Decisões de desenho · ✅
Commitadas (8 commits, cada um passando `make test` sozinho).

### Etapa 2a — Cliente de cotação, guardrail, camada de LLM e `smoke-llm` · escrita, falta o smoke real
Entregue: tudo marcado ✅ na seção 11. **Testes:** relógio virtual (sem `sleep`) para 5xx×3 e depois 200, 5xx×4, resposta lenta de 8s com o "um instante" disparando uma vez, 422 de negócio e de pydantic, 400, 502 com HTML, 429, conexão, 200 incoerente (plano trocado, preço inválido, pro-rata ausente), timeout de tentativa, prazo menor que 15s, prazo abaixo do mínimo;
**`test_never_more_than_one_call_in_flight`** (matriz roteirizada + 1.500 roteiros aleatórios) **com controle negativo no próprio cliente** (um cliente com hedging chega a 2 chamadas em voo); reprodução da simulação com o cliente real; integração com a API real (os dois 422, pro-rata, agravo de CEP); guardrail (passa/reprova, regra esperada, limite conhecido); esquema, prompt estático, fast-path (abstém-se na dúvida);
`ClaudeLLM` contra um servidor local com o **SDK real** (formato exato do pedido, sem `temperature`, `max_retries=0`, timeout, erros);
**camada de LLM agnóstica (D4), tudo contra servidor local falso, sem rede:** `OpenAICompatLLM` (corpo do pedido, `json_schema`, raciocínio, 401/402/429/5xx, erro dentro de 200, `length`, `content` nulo, saída inválida); configuração por env e as recusas de combinação de chave/provedor;
**gate de PII e guardrail acima dos dois adaptadores** (parametrizado, com controle negativo: o adaptador cru enviaria a PII; a fábrica só devolve LLM embrulhado; nenhum adaptador é construído fora dela); cota, limite por minuto e backoff de 429 e de 5xx (relógio virtual); **fail-fast** (todo 4xx de protocolo custa uma requisição, com controle negativo: sem a regra, 29 testes reprovam) e o disjuntor de falhas seguidas; `llm-ping` (uma requisição, causa provável por código, a chave nunca aparece);
**chave nunca vaza** (`tests/test_key_safety.py`: o servidor falso devolve a chave em cada modo de falha e se varre tudo que o processo escreve; removendo o `redact`, os testes reprovam);
`smoke-llm` (gate de PII aborta antes da chamada, erro silencioso, divergência do fast-path, aquecimento excluído, veredito, **31 requisições contadas, pré-checagem de cota, 429 por minuto e diário**).
**O que a 2a NÃO provou:** que o OpenRouter aceita o pedido como montado, a latência e a qualidade de extração do modelo real, e se requisição que falha conta na cota diária. Isso é o `smoke-llm` rodado pelo autor, e a 2b só começa depois dele.

### Etapa 2b — Fatia vertical · limite de 90 min
Terminal, `MockLLM` determinístico (mesma interface, com caminho de fallback para template), orquestrador (máquina de estados), templates, mascarador de PII, SQLite (4 tabelas), `SqliteSink`. Cobre: caminho feliz, recusa da API, `QUOTE_UNAVAILABLE`, `HUMAN_REQUESTED`.
*Testes:* conversa completa por plano contra a API de teste; recusa registrada fora de handoff; queda total → handoff com pacote completo, motivo **e componente**; teto de 20s: uma mensagem terminal visível, nunca silêncio; invariante "todo R$ existe em `quotes`"; toda mensagem/cotação/tentativa com id e status; reconstrução pelo `trace_id`; dedupe; `SqliteSink` passa em `SinkContract`; `reply` reprovado → template com violação registrada; varredura de PII no banco e nos logs, com formatos além dos do dataset.
**Estourou 90 min:** sai o circuit breaker e `quote_attempts` vira JSON, sem discussão.

### Etapa 3 — Cobertura de handoff e experiência · limite de 50 min
Todos os motivos de handoff; pré-checagem e chamada de confirmação; necessidade → plano; objeção; correções; CEP inválido; ano-modelo futuro; mídia.
*Testes:* **contrato da pré-checagem contra a API real** (bordas derivadas do `/planos` + amostra aleatória com semente registrada; "pré-checagem recusa e a API aceita" falha o teste); um cenário por motivo de handoff; objeção: uma alternativa, segunda hesitação → `PRICE_OBJECTION`, sem desconto; nenhuma recusa dita sem a API.

### Etapa 4 — Endurecimento do LLM · limite de 15 min
*Testes:* **mock hostil** que tenta emitir preço, plano inexistente, prazo ou desconto no `reply` (o guardrail barra e cai no template); injeção de prompt no texto do lead; falha/timeout do LLM → `SAFETY_GUARD` com componente `llm`.

### Etapa 5 — Webhook FastAPI · **bônus**  ·  Etapa 6 — Evals completos · **bônus**
Como antes (dedupe, ordem, concorrência; fixtures derivados do texto mascarado, simulador de lead, relatório com gates: 0 preço inventado, 100% dos motivos corretos, 100% das recusas iguais às da API).

### Etapa 7 — Execução com LLM real e log · feita pelo autor
Chave no `.env` (ignorado pelo git), no shell de quem roda. Semente escolhida para o log mostrar uma falha seguida de retry. Exporto o log do banco.

### Etapa 8 — Entrega · limite de 40 min · **sem ela fechada, o trabalho não está pronto**
Critérios de aceite, **todos verificáveis**; `make delivery-check` roda os quatro primeiros mais `make test`:

| # | Critério de aceite | Como se verifica |
|---|---|---|
| E1 | **README final** com como rodar (mock e LLM real), **as decisões e o porquê**, e **o que ficou de fora** (lista explícita: bônus não feitos, limites conhecidos, o que não foi verificado). Sem marcadores `_(planejado)_`, `TODO` ou `FIXME` | Teste de entrega: seções obrigatórias presentes; os marcadores não aparecem; todo link relativo resolve |
| E2 | **`ai-logs/` curados**: só as sessões deste desafio, com um manifesto (ids e o que foi excluído e por quê); **varridos por PII e segredos** (e-mail, caminho de home, chaves, CPF) | `tools/export_ai_logs.py` + teste que roda o detector de PII e os padrões de segredo sobre `ai-logs/**`: **zero achados** |
| E3 | **Log da execução completa com LLM real**: uma conversa do início ao fim **com a cotação saindo** (`status=ok`), `trace_id` e `quote_id`, **pelo menos uma falha seguida de retry visível** | Teste sobre o log exportado: modo `llm=real` registrado; existe cotação `ok`; existe tentativa com `retry`; **todo "R$" de mensagem do agente existe na resposta da cotação do mesmo trace**; sem PII |
| E4 | **Repositório pronto para ser público**: `make test` verde em clone limpo (3.12), árvore limpa, nenhum `.env`/banco/dado cru, NOTICE, histórico de commits legível | `make delivery-check` |
| E5 | **Publicação** (push e link) | Ação do autor. A etapa só fecha com o link |

## 13. Se o tempo apertar

Cortar nesta ordem (o primeiro é o mais barato de perder):

1. **Circuit breaker** e **`quote_attempts` como JSON**: pré-autorizados quando a 2b passar de 90 min.
2. Amostra aleatória do teste de contrato da pré-checagem (as bordas ficam). Se ainda estourar, a pré-checagem inteira sai.
3. **Encolher a Etapa 3** (motivos de handoff menos prováveis viram caso único). **A entrega não encolhe.**
4. Etapas 5 e 6 já são bônus.

**Não cortar:** **a Etapa 8 inteira**, cliente resiliente (B), uma chamada em voo, teto de 20s sem silêncio, invariante de preço, base de fatos e guardrail do `reply`, pacote de handoff com motivo e componente, rastreabilidade, mascaramento, modo mock, gate de PII, o log com LLM real.

## 14. Limites conhecidos

- A latência do LLM é **hipótese** até o `smoke-llm` rodar com o modelo real; os tokens são estimativas (±35%), e o custo usa preços da Anthropic, não do modelo escolhido no OpenRouter.
- O formato do OpenRouter foi conferido na documentação, não na API (seção 5.5). Modelos free podem reter prompts: nada do dataset vai a eles.
- O `smoke-llm` tem 15 mensagens: detecta problemas grosseiros, **não estima taxas**.
- O guardrail restringe o *material* do `reply`, mas **não verifica se uma frase montada com termos autorizados é verdadeira**.
- O mascaramento por regex mais nomes conhecidos é um piso, não uma garantia (o detector atual só vê os formatos de `pii.py`).
- A pré-checagem duplica semântica; o teste de contrato a mantém honesta, e se deixar de compensar ela sai sem afetar o resto.
- O relógio do servidor define a idade do veículo (UTC no container); perto de 31/12 o Brasil e o servidor discordam por algumas horas.
- O modo real não é determinístico: só o mock reproduz.
- Versões do Python verificadas: 3.12 e 3.14. A 3.13 está dentro da faixa declarada mas **não foi testada**.
