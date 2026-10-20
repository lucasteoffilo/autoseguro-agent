# Plano de implementação

> **Estado (2026-10-20):** Etapas 0 e 1 concluídas e commitadas (6 commits, cada um passando `make test` sozinho; sem push).
> **Aguardando aprovação deste plano para começar a Etapa 2a.** A Etapa 2a para no fim e só segue com nova aprovação.
> **O que existe de código de produto hoje:** só o contrato do destino do handoff (`src/autoseguro/handoff.py`). O inventário completo está na seção 11.

## 1. Escopo e tempo (~5 horas)

**Mínimo que precisa funcionar:** o agente conduz a conversa, cota com retry e passa ao humano nos casos deste plano, tudo rastreável e **sem preço inventado**.
Isso é: 2a, 2b, 3, 4b, 7 e 8. **Bônus, só se sobrar tempo:** webhook e concorrência (Etapa 5) e evals completos (Etapa 6).

**Limites de tempo (decididos pelo dono do produto):** 2a em até **1h30**, 2b em até **1h30**. Orçamento total:

| Etapa | Limite |
|---|---|
| 2a (cliente de cotação + guardrail + `smoke-llm`) | 90 min |
| 2b (fatia vertical) | 90 min |
| 3 (cobertura de handoff e experiência) | 50 min |
| 4b (endurecimento do LLM) | 15 min |
| 7 (log com LLM real, feito pelo autor) | 15 min |
| 8 (README e `ai-logs/`) | 30 min |
| **Total** | **290 min (4h50), com ~10 min de folga** |

**Corte pré-autorizado, sem discussão:** se a **2b** passar de 1h30, sai o **circuit breaker** e o `quote_attempts` vira coluna JSON em `quotes`. Se mesmo assim estourar, o próximo corte é a seção 13.

## 2. Princípios (cada um vira um teste)

1. **Preço só sai da API.** O LLM redige conversa, mas **nunca número, prazo nem promessa**. Mensagens de cotação, recusa e handoff são template preenchido com a resposta da API. O texto livre do LLM passa por um guardrail; reprovado, cai para o template do passo.
2. **Na dúvida, atrasar ou passar ao humano.** Preço errado é pior que preço atrasado. Nunca estimar, arredondar ou "chutar" cotação, nem com a API fora do ar.
3. **A API é a palavra final.** A pré-checagem de elegibilidade só melhora a experiência; nenhuma recusa é comunicada ao lead sem confirmação da API.
4. **Tudo rastreável.** Toda mensagem, cotação e tentativa tem id e status, ligados por um `trace_id`.
5. **PII mínima.** Identificadores diretos (CPF, e-mail, telefone, placa, nome) nunca são persistidos nem enviados ao LLM. Os insumos da cotação (idade, ano do veículo, CEP, plano, data) ficam como slots. **Nada sai da máquina sem passar pelo detector de PII**, e até a 2b (que traz o mascarador) só mensagens escritas à mão e sem PII podem ser enviadas.
6. **Não prometer o que o canal não garante.** Nada de prazo, horário ou canal de continuidade no texto de handoff nem no `reply` do LLM.
7. **Nunca silêncio.** Toda mensagem do lead recebe uma resposta visível em até 20s: resposta, cotação, recusa ou handoff.

## 3. Decisões fechadas

| Tema | Decisão | Por quê |
|---|---|---|
| Cliente de cotação | **Política B**: timeout 10s, retry só em 5xx/conexão, no máximo 4 chamadas, **no máximo uma em voo**, backoff exponencial com jitter, orçamento de 15s (e nunca além do prazo restante do turno) | Menor carga e menor taxa de falha entre as opções simples (seção 4) |
| Hedging | **Descartado.** Não existe parâmetro de hedging no código | Corta o p95 de 8s para 2,5s, mas custa +14% de chamadas (+35% degradado); a mensagem de espera cobre a cauda |
| Texto ao lead | **O LLM redige os turnos de conversa** (saudação, próxima pergunta, explicação de carência, dúvida, objeção) **na mesma chamada que extrai os slots**: saída estruturada `{slots, intent, reply}`, sem chamada extra. **Template fixo só nas mensagens de cotação e de handoff**, que carregam número e promessa | O desafio pede conversa, não bot de formulário. Custo da decisão na seção 5.3 |
| Guardrail do `reply` | Sem dinheiro, sem número fora do permitido, sem prazo, sem promessa de desconto, sem garantia de cobertura (seção 6). Reprovou: usa o template do passo e registra a violação | O texto livre não pode carregar o que só a API e o template podem |
| Fast-path por regex | **Nasce desligado.** Só valeria quando o turno é resposta direta ao slot perguntado e o valor é inequívoco; no resto, LLM. O `smoke-llm` mede a divergência regex vs LLM nas mesmas mensagens; divergiu, **sai**. Sem divergência, só entra se o ganho medido justificar | O risco é extrair o slot errado em silêncio e chegar a um preço errado. O ganho é pequeno (seção 5.1) |
| Handoff | Pacote com **código fixo de motivo**, resumo da qualificação, última cotação com id e `trace_id`. O agente diz ao lead, com honestidade, o que acontece depois | Humano assume sem refazer perguntas; lead não fica no escuro |
| Destino do handoff | **Interface `HandoffSink`**; padrão SQLite. CRM ou fila entram **além** do SQLite, sem mexer no agente | Contrato e suíte de teste já existem (seção 7) |
| Texto do handoff | **Genérico**: não promete prazo, horário nem canal. O SLA real é configuração de negócio (`HANDOFF_NEXT_STEP_TEXT`, opcional, vazio por padrão) | Só é verdade o que o canal garante |
| Teto de 20s por turno | Mensagem honesta + handoff `QUOTE_UNAVAILABLE`, **nunca silêncio** (seção 5.2) | Critério aprovado |
| Recusa por regra | Explica e encerra. Registrada como **recusa**, separada de handoff | A recusa é decisão de negócio da API, não falha |
| Objeção de preço | Oferece **uma** alternativa real via API; se hesitar de novo, handoff `PRICE_OBJECTION`. Nunca promete desconto | Perder lead por preço é o desfecho mais comum no dataset; o humano pode negociar |
| Plano | Pergunta a **necessidade em linguagem simples** e o agente mapeia para um plano. Cota **um** plano e oferece comparar | O lead não conhece "Essencial/Completo/Premium" |
| Pré-checagem | Mantida **por experiência**. Lê as faixas do `/planos`. Contrato contra a API real: **bordas + amostra aleatória**, sem varredura | A API manda; divergência é detectada, não presumida |
| `smoke-llm` | **Antecipado para a 2a.** Só mensagens **escritas à mão, realistas e bagunçadas, sem PII**. O autor roda com a chave no `.env` durante a pausa | É o maior risco do plano; medir antes de construir em cima |
| Python | **`>= 3.12`**, verificado em 3.12 (container) e 3.14 (host) | Não se declara o que não se verificou |
| Interface | Terminal + webhook fino em FastAPI (bônus). Sem WhatsApp real | Escopo |
| LLM | Claude pela API da Anthropic por variável de ambiente; **mock offline determinístico** para testes e demo. O log do entregável sai com o LLM real | O avaliador provavelmente não tem chave |
| Modelo por passo | **Provisório** até o `smoke-llm` (seção 5.2) | Depende de números que ainda não existem |
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
**Propriedade testada em comportamento:** em nenhuma cotação há mais de uma chamada em voo. Hoje o teste roda no simulador (a política C é o controle negativo); na 2a roda no **cliente real**, com transporte falso e relógio virtual.
**Limite do modelo:** o "8s fixo e independente da carga" é do mock; num legado real as falhas se correlacionam.

## 5. Latência fim a fim, modelo por passo e custo

### 5.1 Latência por mensagem (LLM + `/quote` + overhead), com o LLM redigindo a resposta

Script: `analysis/e2e_latency_sim.py` (`analysis/results/e2e_latency_sim.md`). **A latência do LLM é hipótese, não medição.** Cada perfil é paramétrico:
p50 de uma chamada = TTFT + tokens de saída ÷ velocidade, com p95 = 2,5×p50. Saída de `{slots, intent}` = 110 tokens; de `{slots, intent, reply}` = 190 tokens.

**Nominal (LLM com `reply`, 190 tokens de saída)**

| Perfil (p50 / p95 de uma chamada) | Turno sem cotação p95 | Turno com cotação p50 / p95 / p99 | "Um instante" (turno com cotação) | Handoff | Mensagem qualquer p95 |
|---|---|---|---|---|---|
| rápido (1,11s / 2,77s) | **2,9s** | 1,6s / **9,5s** / 10,7s | 23,7% | 0,15% | 3,2s |
| médio (2,71s / 6,78s) | **8,6s** | 3,4s / **11,7s** / 14,1s | 70,1% | 0,75% | 9,2s |
| lento (5,32s / 13,3s) | **12,4s** | 6,3s / **13,0s** / 19,1s | 95,1% | 17,7% | 12,4s |

Degradado: rápido 10,8s no turno com cotação (handoff 6,3%); médio 13,5s (7,0%); lento 18,5s (24,0%). Só a `/quote`, sem LLM: p95 8,1s (nominal) e 9,0s (degradado).

**Impacto de o LLM redigir a resposta na mesma chamada (110 → 190 tokens), nominal**

| Perfil | LLM p50 | Turno sem cotação p95 | Turno com cotação p95 | Mensagem qualquer p95 |
|---|---|---|---|---|
| rápido | 0,79s → 1,11s | 2,1s → **2,9s** | 9,1s → 9,5s | 2,4s → 3,2s |
| médio | 1,82s → 2,71s | 4,7s → **8,5s** | 10,3s → 11,7s | 5,2s → 9,2s |
| lento | 3,5s → 5,3s | 11,1s → 12,4s | 12,4s → 13,0s | 11,2s → 12,4s |

**Leitura:** a decisão custa ~0,3s a 0,8s por turno no perfil rápido e é **o que tira o perfil médio do critério C2** (4,7s → 8,5s). Na prática, ela **obriga um modelo pequeno** na chamada única.
O p95 do turno com cotação continua dominado pela `/quote` (8,1s sozinha); o LLM soma ~1,4s (rápido) a ~3,5s (médio).

**Critérios de aceitação (aprovados):** C1 silêncio máximo de 3s (a mensagem "um instante" sai aos 2,5s **desde a chegada da mensagem**); C2 turno sem cotação com p95 ≤ 5s; C3 turno com cotação com p95 ≤ 12s;
C4 teto duro de 20s por turno. Varrendo o p50 do LLM (p95 = 2,5×p50): **C2 quebra entre p50 = 1,5s e 2,0s** (p95 da chamada ≈ 4 a 5s); C3 aguenta até p50 = 2,0s e quebra a partir de 3,0s.
Com 190 tokens de saída e TTFT de 0,35s, o modelo precisa gerar **≥ ~125 tokens/s** para ficar dentro de C2. Isso é medível no `smoke-llm`.

**Fast-path estrito (cobertura de 0% / 30% / 40% dos turnos):** p95 de uma mensagem qualquer, perfil rápido: 3,5s / 3,2s / 3,1s. **Vale ~0,2 a 0,4s**, e o custo em dólares é de centavos. Por isso nasce desligado (seção 3).

### 5.2 O que acontece ao bater o teto de 20s

1. **Teto estourado com a `/quote` em andamento, ou sem prazo restante para ela** → mensagem honesta ("não consegui gerar sua cotação agora por uma instabilidade no nosso sistema; não vou te passar valor sem a confirmação dele") **e** handoff `QUOTE_UNAVAILABLE`. **Nunca silêncio.**
2. **Teto estourado antes de a cotação ser pedida, porque o LLM falhou** (6s de timeout, 1 retry) → mesma honestidade na mensagem, mas o motivo é `SAFETY_GUARD`, porque a causa não foi a `/quote`. *(Pequena divergência da regra enunciada; confirmar.)*
3. **"Um instante"** aos 2,5s desde a chegada da mensagem (aos 4s em turnos que não chamam a `/quote`, se o `smoke-llm` mostrar que o p95 do LLM passa de 2,5s). Em turno de cotação, o próprio `reply` do LLM pode servir de confirmação ("vou calcular agora") assim que chegar, desde que passe pelo guardrail.
4. **Teste (relógio virtual):** em todas as sequências da matriz de falhas, exatamente uma mensagem terminal visível sai em até 20s, e a de espera sai em até 2,5s quando o turno ultrapassa isso.

### 5.3 Modelo por passo (provisório) e custo

| Passo | Modelo | Configuração |
|---|---|---|
| Extração de slots + intenção + resposta de conversa (uma chamada por mensagem) | `claude-haiku-5-5` | `effort: low`, saída estruturada (`output_config.format`), **sem `temperature`** (valor fora do padrão dá 400), `max_tokens` com folga para o raciocínio |
| Escalonamento (saída inválida, ambígua ou de baixa confiança) | `claude-sonnet-5-5` | Uma tentativa; orçamento de até 10% das chamadas. **Com `reply`, o Sonnet puro fica fora de C2** (seção 5.1) |
| Mensagens de cotação, recusa e handoff | nenhum | Template (números e promessas) |
| Resumo do handoff | nenhum | Determinístico a partir dos slots |
| Opus | não usar | Sem ganho justificável para esta tarefa |

Consequência: **sem `temperature=0`, o modo real não é determinístico**; só o mock reproduz. O cache do prefixo só liga com tráfego contínuo (acerto > 21,7%); no demo fica desligado.

Script: `analysis/cost_model.py`. **Tokens são estimativa (±35%)**; preços da tabela da skill `claude-api` (2026-10-06), a conferir. Por chamada: ~2.000 tokens de prefixo estático (persona e tom, fatos do `/planos`, regras do guardrail, exemplos com resposta), ~440 dinâmicos, ~190 de saída.

| Conversa | Entrada total | Dela, do cache (hit 95%) | Saída (antes → depois) |
|---|---|---|---|
| 5 chamadas | 12.200 | 9.500 | 550 → 950 |
| 8 chamadas | 19.520 | 15.200 | 880 → 1.520 |
| difícil, 12 chamadas | 29.280 | 22.800 | 1.320 → 2.280 |

| Estratégia (8 chamadas) | Antes → depois, sem cache | Antes → depois, hit 95% | Por 1.000 conversas (hit 95%) |
|---|---|---|---|
| **Haiku 5.5** | $0,0020 → $0,0027 (+36%) | $0,0010 → $0,0014 (+39%) | $1,36 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | $0,0060 → $0,0081 (+36%) | $0,0050 → $0,0068 (+37%) | $6,79 |
| Sonnet 5.5 | $0,0398 → $0,0542 (+36%) | $0,0196 → $0,0273 (+39%) | $27,28 |
| Opus 5.5 | — → $0,1085 | — → $0,0515 | $51,52 |

**Impacto:** redigir a resposta no LLM acrescenta **~36 a 39% ao custo** (mais prefixo e mais saída), o que ainda é centavos (Haiku: US$ 1,36 por mil conversas). **Custo continua não sendo a restrição; latência e precisão de extração são.**
Raciocínio residual de 250 tokens por chamada levaria o Haiku de $0,0027 para $0,0037.

### 5.4 O que o `smoke-llm` mede (Etapa 2a, rodado pelo autor)

Entrada: ~15 mensagens **escritas à mão**, realistas e bagunçadas, **sem PII** (seção 12, Etapa 2a), 3 repetições, nos dois modelos candidatos. Registra:

1. latência por chamada (p50/p95/p99) e tokens de saída por segundo;
2. `usage` de cada resposta: entrada, saída, cache e raciocínio a `effort: low`;
3. taxa de saída estruturada válida sem retry, `max_tokens` atingido, recusas, 429/5xx/timeouts;
4. precisão de extração contra o gabarito escrito à mão, **separando erro silencioso (valor presente e errado) de omissão**;
5. taxa de aprovação do `reply` no guardrail e o tipo das violações;
6. **divergência regex vs LLM** nas mensagens que respondem a um slot perguntado (decide o fast-path);
7. aderência do `reply` aos fatos do plano (carência, coberturas) lida por uma pessoa, porque regex não verifica sentido.

**Critério de passagem (honesto sobre o tamanho da amostra):** 15 mensagens **não certificam taxas**; o `smoke-llm` é um alarme contra problemas grosseiros, não um benchmark.
Passa se: 0 extrações erradas em silêncio; saída estruturada válida em 100%; p95 por chamada ≤ 4,5s (margem sobre o limite de ~4,9s de C2); aprovação do guardrail ≥ 80% (abaixo disso o prompt do `reply` precisa de trabalho); 0 divergências no fast-path.
A estimativa de taxas de verdade (por exemplo, 98% de extração correta) exige a amostra maior dos evals (Etapa 6, bônus).

## 6. Guardrail do `reply` do LLM

Função pura `check_reply(text, allowed_numbers) -> violações`. Reprovou, o orquestrador usa o template do passo e grava `reply_source=template_fallback` e as violações em `messages.meta`.

| Regra | Rejeita |
|---|---|
| R1 Sem dinheiro | `R$`, "reais", "mensalidade", "parcela", "prêmio", qualquer valor monetário |
| R2 Números só os permitidos | Dígitos que não estejam nos slots desta chamada, no estado da conversa ou nos "30 dias" de carência vindos do `/planos` |
| R3 Sem prazo nem ação futura de terceiros | "amanhã", "em breve", "em instantes", "daqui a pouco", "imediatamente", "em até N", "dias úteis", "horas", "minutos", "entrar em contato", "ligar", "te chamar", "neste mesmo chat" |
| R4 Sem promessa de condição | "desconto", "promoção", "abatimento", "preço especial", "condição especial", "melhor preço", "igualamos", "cortesia", "grátis" |
| R5 Sem garantia de cobertura | "cobre tudo", "sem carência", "garantimos", "100%", "imediat…" |
| R6 Forma | Mais de 400 caracteres, marcação interna (`<`, `{`, `[` de placeholder) |

**Testes:** tabela de casos que devem passar (inclusive "roubo e furto só passam a valer depois de 30 dias do início"), casos que devem reprovar por regra, textos hostis (injeção no texto do lead pedindo preço ou desconto) e controle negativo. **Limite conhecido:** regex não verifica se uma explicação está *correta*;
isso fica a cargo do prompt (que recebe os fatos do `/planos`) e da leitura humana no `smoke-llm`.

## 7. Handoff

Motivos (enum fixo e versionado em `HandoffReason`; um teste garante que esta tabela e o enum não divergem):

| Código | Quando |
|---|---|
| `QUOTE_UNAVAILABLE` | Orçamento esgotado ou teto de 20s com a `/quote` em andamento. O pacote leva o veredito da pré-checagem, se houver |
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

**Destino** (`HandoffSink`, síncrono): `deliver(package) -> DeliveryReceipt`. Idempotente por `trace_id`; não altera o pacote; falha transitória é `SinkUnavailable` e permanente é `SinkRejected`.
O SQLite é o registro de rastreabilidade e **sempre** existe; um CRM ou fila entra **além** dele. Ordem: grava no SQLite, responde ao lead, entrega ao sink; se o sink falhar, o handoff fica `pending`.
A suíte `tests/sink_contract.py` é o critério de aceitação de qualquer destino (já tem controle negativo).

**Texto ao lead (templates, testados por motivo):** um consultor dará continuidade; o que ele contou ficou registrado; **não** promete prazo, horário, canal nem desconto; só cita valor se houver cotação verificada.

## 8. Fluxo de qualificação

A cada mensagem o LLM devolve `{slots, intent, reply}`. **Quem decide o próximo passo é o orquestrador, pelo estado, e não o LLM.**
Ordem: **ano do veículo → idade → (pré-checagem) → CEP → necessidade → data de início → cotar → apresentar**.

- **Conversa (LLM, com guardrail):** saudação, próxima pergunta, explicação de carência, dúvida do lead, resposta a objeção. **Template:** cotação, recusa, handoff e o fallback de cada pergunta.
- **Necessidade → plano.** Três opções em linguagem simples, derivadas das coberturas do `/planos`: só roubo, furto e colisão (Essencial); com danos a terceiros e vidros (Completo); com carro reserva e assistência 24h (Premium). Mapeia o menor plano que cobre o pedido. Ambíguo: pergunta de novo uma vez; depois `DATA_AMBIGUOUS`.
- **Pré-checagem.** Só quando prevê recusa o agente faz uma chamada de confirmação (idade e ano apenas). Se a API disser 200, a divergência é registrada, esse preço parcial **nunca** é exibido, e o fluxo segue. Se a API estiver fora, handoff `QUOTE_UNAVAILABLE` com o veredito no pacote. Nunca diz "recusado" sem a API.
- **Apresentação.** Sempre: recap dos dados usados, mensalidade, primeiro pagamento (pro-rata, quando houver), franquia e carência de 30 dias para roubo/furto. Confirmação antes de cotar só quando a extração veio ambígua ou implausível.
- **Higiene de entrada (não é regra de negócio):** CEP como string de 8 dígitos, obrigatório; `plano_id` sempre explícito e conferido na resposta; `data_inicio` hoje ou futura; ano-modelo futuro vai ao humano.

## 9. Persistência (SQLite, 4 tabelas)

| Tabela | Pergunta de rastreabilidade |
|---|---|
| `conversations` | Como terminou (`quoted`, `refused`, `handoff` + motivo, `open`)? Qual era o estado (slots) e qual pacote foi entregue ao humano? |
| `messages` | O que foi dito, por quem, em que ordem? Já foi processada (dedupe)? Que cotação exibe? O que o LLM e o guardrail fizeram (`meta`: `usage`, `reply_source`, violações)? |
| `quotes` | Que cotação o lead recebeu, para qual entrada normalizada, com que status e valor? Foi cotação, alternativa ou confirmação da pré-checagem? |
| `quote_attempts` | Como a `/quote` chegou a esse resultado: tentativas, status HTTP, tempo, por que parou? (A pergunta central do desafio.) |

**Cortadas, com motivo:** `refusals` (uma recusa é uma linha de `quotes` com `status='refused'`), `llm_calls` (vai em `messages.meta`), `handoffs` (é 1:1 com a conversa).
A invariante do princípio 1 é uma consulta: todo "R$" em `messages` do agente existe em `quotes.response` do mesmo `trace_id`. **Nunca persistido:** texto cru, CPF, e-mail, telefone, nome, placa, prompts.
Se a 2b estourar o limite, `quote_attempts` vira coluna JSON em `quotes` (corte pré-autorizado).

## 10. Estrutura do repositório

```
src/autoseguro/      produto: handoff.py (existe); slots, quote_client, guardrail, fastpath (candidato), llm/ (schema, prompt, claude, mock),
                     orquestrador, templates, mascarador, persistência (a partir da 2a)
tools/               smoke_llm.py e as mensagens escritas à mão (2a)
analysis/            scripts de análise (agregados apenas) e analysis/results/
tests/               unitários, higiene, contrato de destino, integration/
docs/                PLAN.md, FINDINGS.md
vendor/              TUDO que veio do desafio, sem modificação (NOTICE.md, vendor/quote-service.sha256)
ai-logs/             conversas com IA, limpas (Etapa 8)
```

## 11. Inventário: o que existe e quando entra

O recap "Etapas 0 e 1 prontas" foi impreciso: a Etapa 1 entregou **decisões e um contrato de código** (`handoff.py`), não o domínio. A tabela abaixo é a verdade, e o guardrail e os renderizadores eram uma **lacuna do plano anterior** (não estavam em nenhuma etapa):

| Componente | Existe hoje? | Entra em |
|---|---|---|
| Pacote de handoff, motivos, `HandoffSink` e suíte de contrato | ✅ `src/autoseguro/handoff.py` | — |
| Scripts de análise, simuladores, detector de PII dos testes, higiene do repo | ✅ | — |
| Normalização de slots (CEP de 8 dígitos, plano, data, ano) | ❌ | **2a** |
| Resultados tipados e cliente da `/quote` (política B) | ❌ | **2a** |
| Guardrail do `reply` (seção 6) | ❌ **lacuna do plano anterior** | **2a** (o `smoke-llm` precisa dele) |
| Esquema `{slots, intent, reply}`, prompt, `ClaudeLLM` mínimo, `make smoke-llm` | ❌ | **2a** |
| Fast-path estrito (candidato, desligado) | ❌ | **2a**, só para medir |
| Renderizadores/templates de cotação, recusa e handoff; fallback por passo | ❌ **lacuna do plano anterior** | **2b** |
| `MockLLM`, orquestrador, mascarador de PII, SQLite, `SqliteSink` | ❌ | **2b** |
| Pré-checagem de elegibilidade e teste de contrato | ❌ | **3** |
| Necessidade → plano, objeção, demais motivos de handoff | ❌ | **3** |

## 12. Etapas

Tamanho: P (pequena), M (média), G (grande). **Marco:** a fatia de ponta a ponta fica pronta ao fim da 2b.

### Etapa 0 — Fundação · ✅ concluída
Repo, `vendor/` com checksum, composes, `analysis/`, FINDINGS, plano, higiene. Validada em Python 3.12 e 3.14; `make api-up` real; cada um dos 6 commits passa `make test` isolado.

### Etapa 1 — Decisões de desenho · ✅ concluída
Latência fim a fim, modelo por passo, custo, interface do destino do handoff, critérios de aceitação (seções 5 e 7).

### Etapa 2a — Cliente de cotação, guardrail e `smoke-llm` · limite de 90 min · **próxima; para no fim**
**Ordem de construção:** (1) normalização de slots e guardrail, que são pequenos e usados pelos dois lados; (2) cliente da `/quote` com a matriz de relógio virtual; (3) esquema, prompt, `ClaudeLLM` mínimo e `smoke-llm`.
Antes de escrever o `ClaudeLLM`, leio a documentação atual do SDK (saída estruturada, `usage`). Dependência `anthropic` como extra opcional `llm`; `.env.example` versionado, `.env` ignorado.

**Cliente da `/quote`.** Resultado tipado (`Quote`, `Refused`, `InvalidInput`, `Transient`, `Unavailable`); política B; classificação pelo **corpo** (os dois 422); `plano_id` da resposta conferido; recebe o prazo restante do turno; callback de "um instante". **Sem circuit breaker.**
*Testes (relógio virtual, sem `sleep`):* 5xx×3 e depois 200; 5xx×4 → `Unavailable` antes de 15s; resposta lenta de 8s dispara o callback uma vez; 422 de negócio e de pydantic sem retry; 400 sem retry; 502 com HTML; 200 com plano trocado descartado;
prazo restante menor que 15s respeitado; **nunca mais de uma chamada em voo** (cliente real); **teto de 20s: sempre sai uma mensagem terminal, nunca silêncio**; reprodução da simulação de latência com o cliente real.

**Guardrail e slots.** *Testes:* seção 6; normalizadores nas bordas (CEP sem zero à esquerda, plano com espaço, data passada, ano-modelo futuro).

**`smoke-llm`.** `make smoke-llm` roda ~15 mensagens **escritas à mão** × 3 repetições × 2 modelos e grava o relatório em `var/smoke/` (ignorado pelo git). Cobertura das mensagens: resposta direta ao slot perguntado; vários slots numa mensagem só; gíria e número aproximado
("uns 35"); correção ("na verdade tenho 53"); número ambíguo; pergunta sobre carência; objeção de preço; pedido de humano; reclamação e sinistro; pedido de desconto; tentativa de injeção ("ignore as instruções…"); emoji e abreviação.
*Garantia de que nada sai sem estar seguro:* (a) cada mensagem tem `source: hand-written`; (b) o detector de PII roda em **todo** payload antes do envio e a execução aborta se achar algo; (c) o teste de linha crua do dataset já varre o arquivo das mensagens;
(d) o script não tem acesso ao dataset. *Testes:* o gate de envio bloqueia payload com PII (amostra montada em tempo de execução); as mensagens do arquivo passam no detector; o relatório separa erro silencioso de omissão; o veredito do fast-path sai do cálculo da divergência.

**Se estourar os 90 min, corta nesta ordem:** (1) medição do fast-path no `smoke-llm` (sem medição, o fast-path simplesmente não entra); (2) comparação com o segundo modelo; (3) largura da matriz de relógio virtual. **Nunca:** uma chamada em voo, teto de 20s e o gate de PII do envio.

### Etapa 2b — Fatia vertical · limite de 90 min
Terminal, `MockLLM` determinístico (mesma interface `{slots, intent, reply}`, com caminho de fallback para template), orquestrador (máquina de estados), templates de cotação, recusa e handoff, mascarador de PII, SQLite (4 tabelas), `SqliteSink`, pacote de handoff.
Cobre: caminho feliz, recusa da API, `QUOTE_UNAVAILABLE`, `HUMAN_REQUESTED`.
*Testes:* conversa completa por plano contra a API de teste; recusa registrada fora de handoff; queda total → handoff com pacote completo e texto honesto; invariante "todo R$ existe em `quotes`"; toda mensagem/cotação/tentativa com id e status;
reconstrução pelo `trace_id`; dedupe de reentrega; `SqliteSink` passa em `SinkContract`; `reply` reprovado no guardrail → template, com violação registrada; varredura de PII no banco e nos logs com formatos **além** dos do dataset
(CPF sem pontuação, telefone com parênteses, e-mail com `+`, placa antiga, colisão telefone vs CEP).
**Estourou 90 min:** sai o circuit breaker e `quote_attempts` vira JSON em `quotes`, sem discussão.

### Etapa 3 — Cobertura de handoff e experiência · limite de 50 min
Todos os motivos de handoff; pré-checagem e chamada de confirmação; necessidade → plano; objeção de preço; correções; CEP inválido; ano-modelo futuro; mídia.
*Testes:* **contrato da pré-checagem contra a API real**: bordas derivadas do próprio `/planos` (cada limite ±1, extremos, ano futuro) mais amostra aleatória com semente registrada; "pré-checagem recusa e a API aceita" falha o teste.
Um cenário escrito à mão por motivo de handoff. Mapa necessidade → plano. Objeção: alternativa real uma vez, segunda hesitação → `PRICE_OBJECTION`, sem texto de desconto. Nenhuma recusa dita sem confirmação da API.

### Etapa 4b — Endurecimento do LLM · limite de 15 min
*Testes:* **mock hostil** que tenta emitir preço, plano inexistente, prazo ou desconto no `reply` (o guardrail barra todos e cai para o template); injeção de prompt no texto do lead; falha/timeout do LLM → `SAFETY_GUARD`.

### Etapa 5 — Webhook FastAPI · **bônus**
`POST /webhook/inbound` (202, segundo plano), `GET /conversations/{trace_id}/messages`, `GET /handoffs`; lock por conversa. *Testes:* dedupe, ordem, concorrência na mesma conversa, "um instante" antes da resposta final.

### Etapa 6 — Evals completos · **bônus**
Fixtures derivados do texto (mascarado) com simulador de lead; conjunto sintético de handoff; runner e relatório; é aqui que as taxas ganham amostra suficiente. O oráculo é a API de teste.
**Gates:** 0 preço inventado; 100% dos motivos corretos no sintético; 100% das recusas iguais às da API.

### Etapa 7 — Execução com LLM real e log · feita pelo autor
Chave no `.env` (ignorado pelo git), no shell de quem roda. Semente escolhida para o log mostrar uma falha seguida de retry. Exporto o log do banco.

### Etapa 8 — Documentação e entrega
README final (a partir de `FINDINGS.md`), decisões, curadoria de `ai-logs/` (só as sessões deste desafio; limpeza de e-mail, caminho de home e PII sintética, com scanner como teste). Publicar no GitHub é ação do autor.

## 13. Se o tempo apertar

Cortar nesta ordem (o primeiro é o mais barato de perder):

1. **Circuit breaker** e **`quote_attempts` como JSON**: pré-autorizados quando a 2b passar de 90 min.
2. Amostra aleatória do teste de contrato da pré-checagem (as bordas ficam). Se mesmo assim estourar, a pré-checagem inteira sai e o resto não muda.
3. Etapas 5 e 6 já são bônus.

**Não cortar:** cliente resiliente (B), uma chamada em voo, teto de 20s sem silêncio, invariante de preço, guardrail do `reply`, pacote de handoff e motivos, rastreabilidade, mascaramento, modo mock, gate de PII do envio, README, `ai-logs/` e o log com LLM real.

## 14. Limites conhecidos

- A latência do LLM é **hipótese** até o `smoke-llm`; os tokens por chamada são estimativas (±35%); o prompt real ainda não existe.
- O `smoke-llm` tem ~15 mensagens: detecta problemas grosseiros, **não estima taxas**.
- O guardrail é um conjunto de regex: não verifica se uma explicação (por exemplo, de carência) está *correta*, só que não carrega dinheiro, prazo, desconto nem garantia.
- O mascaramento por regex mais nomes conhecidos é um piso, não uma garantia; vale também para formatos que o dataset não tem.
- A pré-checagem duplica semântica (ano atual menos ano do veículo, buraco abaixo de 18 anos). O teste de contrato a mantém honesta; se deixar de compensar, ela sai sem afetar o resto.
- O relógio do servidor define a idade do veículo (UTC no container); perto de 31/12 o Brasil e o servidor discordam por algumas horas.
- O modo real não é determinístico (sem `temperature` neste modelo): só o mock reproduz.
- Versões do Python verificadas: 3.12 e 3.14. A 3.13 está dentro da faixa declarada mas **não foi testada**.
