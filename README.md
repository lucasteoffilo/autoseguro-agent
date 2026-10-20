# AutoSeguro Agent

Agente de vendas de seguro auto para o desafio técnico FDE / AI Engineer da Namastex: conversa com o lead,
qualifica, cota um plano pela API de cotação e decide entre resolver sozinho e passar para um humano.

> **Estado: Etapas 0 e 1 concluídas e a 2a escrita; o roteiro vai até a Etapa 8 (entrega).** Existem o cliente da `/quote`, a normalização de slots, o guardrail com base de fatos, o contrato do destino do handoff, a camada de LLM agnóstica de provedor (D4) e o `smoke-llm`.
> **O `smoke-llm` com o modelo real ainda não rodou**, então latência, formato e acerto do LLM são hipótese. A Etapa 2b (terminal, mock, orquestrador, persistência) só começa depois dele.
> **O agente ainda não conversa.**
> Esta página cresce a cada etapa. O que está marcado _(planejado)_ descreve o que vem, não o que já roda.
> Roteiro e critérios de corte em [`docs/PLAN.md`](docs/PLAN.md); achados que motivam o desenho em [`docs/FINDINGS.md`](docs/FINDINGS.md).

## O que roda hoje

Requer Python ≥ 3.12 (verificado em 3.12 e 3.14) e Docker.

```bash
make setup
```

```bash
make test
```

```bash
make test-integration
```

`make smoke-llm-dry` roda o `smoke-llm` com um LLM de mentira (sem chave, sem rede).
Com o modelo de verdade pelo OpenRouter: copie `.env.example` para `.env` e preencha `LLM_API_KEY` (ou `OPENROUTER_API_KEY`). **Primeiro `make llm-ping`**: uma única requisição real que confere a autenticação, se o OpenRouter aceita o pedido como montado (`json_schema` + `require_parameters`), se o modelo devolve saída válida e a latência dessa amostra; confirma que a chave está setada sem mostrar valor, prefixo nem tamanho.
Depois `make smoke-llm`: gasta **31 das 50 requisições diárias** do free tier (1 aquecimento + 15 mensagens × 2 repetições), respeita 20 por minuto, conta cada chamada em `var/smoke/quota.jsonl` e aborta antes de gastar se a cota não cobrir. **Falha rápido:** o primeiro erro de protocolo (qualquer 4xx fora 408 e 429: 400, 401, 402, 403, 404…) aborta na hora e custa uma requisição, não 31; só o 429 por minuto e as falhas do serviço (408, 5xx) entram em backoff, e três chamadas seguidas que ainda falham depois dele abortam também. `make smoke-llm-anthropic` é o mesmo smoke pela API direta da Anthropic (opcional).
`make test` roda os testes unitários e de higiene do repositório. `make test-integration` sobe a API de cotação
determinística (porta 8100, sem falhas) e roda os testes que dependem dela. `make api-up` sobe a API com a instabilidade
padrão do desafio na porta 8000. As análises estão em [`analysis/`](analysis/README.md).

## Decisões

### D1. Cliente de cotação: timeout de 10s, retry só em 5xx, hedging descartado

A `/quote` simula um legado: ~20% das chamadas falham na hora (500/502/503) e ~10% demoram exatamente 8s, mas **respondem
200 válido**. O lead de WhatsApp esfria em minutos, e preço errado é pior que preço atrasado. Comparei três políticas
simples por simulação (200 mil cotações cada, orçamento de 15s, no máximo 4 chamadas; script e semente em
[`analysis/latency_sim.py`](analysis/latency_sim.py)):

**Cenário nominal (5xx 20% / lenta 10%)**

| Política | p50 | p95 | p99 | Sem cotação em 15s | Chamadas por cotação |
|---|---|---|---|---|---|
| A) timeout 2s + retry | 0,19s | 2,5s | 4,8s | 0,78% | 1,42 |
| **B) timeout 10s, retry só em 5xx (adotada)** | 0,19s | 8,0s | 8,4s | **0,15%** | **1,25** |
| C) hedge aos 2s (**descartada**) | 0,19s | 2,5s | 6,1s | 0,15% | 1,42 |

**Cenário degradado (5xx 50% / lenta 20%)**

| Política | p50 | p95 | Sem cotação em 15s | Chamadas por cotação |
|---|---|---|---|---|
| A) timeout 2s + retry | 0,50s | 4,2s | 23,9% | 2,53 |
| **B) adotada** | 0,97s | 9,0s | **6,2%** | **1,87** |
| C) hedge aos 2s (descartada) | 0,97s | 8,9s | 6,2% | 2,53 |

**Por que B e por que não hedging:**

- O timeout curto (A) parece o mais simples, mas cancela chamadas que o servidor **continua processando por 8s**: tem a
  mesma carga do hedging e a pior taxa de falha.
- O hedging (C) corta o p95 de 8s para 2,5s, mas custa +14% de chamadas no cenário nominal e +35% no degradado, que é
  quando o legado menos aguenta. No cenário degradado ele nem ajuda: os 5xx dominam e o p95 fica igual ao de B.
- A cauda de ~8s de B é coberta pela mensagem de "um instante" ao lead (enviada aos 2,5s, em ~12,6% das cotações), dentro do
  orçamento de 15s.
- Retry só em 5xx e erro de conexão; nunca em 400 ou 422.

O cliente ([`quote_client.py`](src/autoseguro/quote_client.py)) não tem parâmetro de hedging, e isso é garantido por **comportamento**, não por texto: um teste mede que nunca há mais de uma chamada em voo, com um cliente defeituoso que faz hedging como controle negativo. Limite do modelo: o
"8s fixo" e a independência entre chamadas são do mock; um legado real tem falhas correlacionadas.

### D2. O texto de handoff não promete prazo nem canal; o SLA real é configuração de negócio _(planejado)_

Quando o agente passa a conversa para um humano, ele diz ao lead, com honestidade, o que acontece: que um consultor dará
continuidade e que o que foi contado ficou registrado. Ele **não** promete prazo, horário, nem que a conversa continuará "neste
mesmo chat", nem desconto. Só é verdade o que o canal garante, e este projeto não tem fila humana real. O prazo de
atendimento e o canal de continuidade são **configuração de negócio** de quem opera o agente: podem ser acrescentados ao texto
com `HANDOFF_NEXT_STEP_TEXT` (vazio por padrão).

**Para onde o pacote vai é uma interface**, `HandoffSink` ([`src/autoseguro/handoff.py`](src/autoseguro/handoff.py)): SQLite por padrão. Um CRM ou uma
fila entram **além** do SQLite, sem mexer no agente, e qualquer destino novo tem que passar na suíte de contrato
[`tests/sink_contract.py`](tests/sink_contract.py) (idempotência por `trace_id`, falha transitória distinta de permanente, pacote imutável). Nenhuma integração está implementada.

### D3. O LLM redige a conversa; modelo, latência e custo _(provisórios até o `smoke-llm` rodar com o modelo real)_

Resumo; as tabelas, a derivação e as premissas estão em [`docs/PLAN.md`](docs/PLAN.md), seções 5 e 6.

- **O LLM redige os turnos de conversa** (saudação, próxima pergunta, explicação de carência, dúvida, objeção) **na mesma chamada que extrai os slots**: saída estruturada
  `{slots, intent, facts_used, reply}`, sem chamada extra, com `reply` de no máximo ~40 palavras. **Cotação, recusa e handoff são template fixo**, porque carregam número e promessa.
- **O `reply` só pode afirmar o que está numa base de fatos derivada do `/planos`**, e todo número dele tem que estar nesses fatos ou ecoar um dado que o lead escreveu. O guardrail confere isso de forma
  mecânica e, se reprovar, o agente usa o template. **Limite assumido:** usando só termos autorizados, uma frase *falsa* ainda passa; regex não lê sentido. O `smoke-llm` tem mensagens feitas para isso, para uma pessoa ler.
- **Um critério de latência só:** p95 do turno ≤ 5s sem cotação e ≤ 12s com cotação. O "um instante" aos 2,5s e o teto de 20s (mensagem honesta + handoff, nunca silêncio) são mecanismos.
  O limite por chamada de LLM é **derivado** do critério (p95 ≤ ~4,9s), não escolhido.
- **O `reply` curto não resolve sozinho o perfil de modelo médio** (turno sem cotação: 8,5s → 8,3s com o teto de 40 palavras). A lista compacta de slots leva a 5,2s, a 3% do critério e sem margem.
  Na prática a chamada única exige um modelo pequeno.
- **O p95 de um turno com cotação continua dominado pelo modo lento de 8s da `/quote`** (8,1s sozinha; 9,2s somando um LLM rápido).
- **Modelo: ainda não escolhido.** O smoke decide, pelo mesmo critério de antes (D4): 0 extrações erradas em silêncio, 100% de saída válida e p95 projetado do turno dentro do critério acima.
  **Custo (estimativa, não medição):** feito com a tabela de preços da Anthropic para o Haiku 5.5, o caso de referência: centavos por conversa (US$ 1,14 por mil conversas com cache; US$ 6,39 com 10% de escalonamento para o Sonnet 5.5). Redigir a resposta no LLM acrescenta +16% a +32%. No OpenRouter o preço varia por modelo e deve ser refeito com o modelo escolhido. Latência decide, não preço.
- **Fast-path por regex nasce desligado.** Só valeria para resposta direta ao slot perguntado com valor inequívoco, e rende ~0,2 a 0,3s de p95 com o LLM rápido. O `smoke-llm` mede a divergência regex vs LLM; se divergir, sai.
- **O que ainda é hipótese:** a latência do LLM e a contagem de tokens. O `make smoke-llm` (Etapa 2a) as mede com chamadas reais, usando só mensagens escritas à mão e sem PII. Provedor e modelo: D4.

### D4. A camada de LLM não depende de um provedor; o default é o OpenRouter

**Motivo:** o projeto não tem acesso à API direta da Anthropic, só ao OpenRouter.

- **Uma interface (`LLMClient`), dois adaptadores:** `OpenAICompatLLM` (chat completions, só stdlib como o cliente da `/quote`; OpenRouter e qualquer servidor compatível) e `ClaudeLLM` (API da Anthropic, continua como opção, SDK só no extra `llm`).
  Escolha por env: `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` (ver [`.env.example`](.env.example)). O mock segue como default dos testes.
- **O gate de PII e o guardrail ficam acima do adaptador**, em `GuardedLLM` ([`llm/guarded.py`](src/autoseguro/llm/guarded.py)), e a fábrica (`make_llm`) só devolve LLM embrulhado nele. O gate roda antes de qualquer requisição e o guardrail depois da resposta, então trocar de provedor não contorna nenhum dos dois.
  [`tests/test_llm_layers.py`](tests/test_llm_layers.py) prova isso para os dois adaptadores, com controle negativo (o adaptador cru, sem a camada, enviaria a PII) e uma checagem estrutural de que nenhum adaptador é construído fora da fábrica.
- **A chave do OpenRouter nunca passa pelo `ClaudeLLM`:** ele usa parâmetros da Anthropic (`output_config`, `effort`) que o OpenRouter não garante. A configuração recusa a combinação, e a chave da Anthropic também não vai a outro provedor.
- **Saída estruturada:** `response_format` `json_schema` (estrito) junto de `provider.require_parameters`, que só roteia para quem o suporta. Conferido na documentação do OpenRouter em 2026-10-20 e ligado por padrão, desligável com `LLM_STRUCTURED_OUTPUT=none`.
  O provedor não é confiado para o formato: toda saída é validada com o schema local, e saída inválida cai no template ou escala para humano, como em D3. Modelos de raciocínio gastam `max_tokens` pensando; `finish_reason=length` com texto vazio conta como falha, e o esforço de raciocínio padrão é `none`.
- **Smoke dentro do free tier** (20 requisições/min, 50/dia sem crédito): 1 modelo, 2 repetições, 31 requisições; limite por minuto respeitado com margem; 429 por minuto espera e repete, 429 diário encerra e marca o dia; toda requisição, inclusive as que falham, é contada em `var/smoke/quota.jsonl`; a cota restante é conferida em `GET /key` antes de gastar. **Falha rápido** (não sabemos se requisição que falha conta na cota): erro de protocolo aborta na hora com a causa provável, e `make llm-ping` antes do smoke gasta uma requisição para descobrir isso.
  A documentação não diz se requisição que falha conta na cota diária, então o smoke assume que conta.
- **A chave nunca aparece em log, erro, relatório nem saída:** tudo que sai passa por `redact`, e [`tests/test_key_safety.py`](tests/test_key_safety.py) faz o servidor falso devolver a chave em cada modo de falha e varre tudo que o processo escreveu. Verificado removendo o `redact`: os testes reprovam (8 dos 25 na ocasião).
- **Critério de escolha do modelo, o mesmo de antes:** 0 extrações erradas em silêncio, 100% de saída válida e p95 projetado do turno. O candidato do smoke é `nvidia/nemotron-3-super-120b-a12b:free` (suporta saída estruturada e raciocínio opcional); é candidato, não escolha.
- **Não verificado:** que o OpenRouter aceita de fato a requisição como montada (os testes usam um servidor local falso), a latência real e a taxa de acerto. Modelos free podem reter o prompt; o gate de PII continua ligado e o smoke só usa mensagens escritas à mão, sem PII.
- **O log final da execução cita o provedor e o modelo usados.**

### Demais decisões

Pré-checagem de elegibilidade, recusa, objeção de preço, necessidade → plano, modo mock do LLM, persistência: ver
[`docs/PLAN.md`](docs/PLAN.md), seção 2.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `src/autoseguro/` | Código do produto: `quote_client`, `slots`, `facts`, `guardrail`, `handoff`, `budgets`, `pii`, `llm/` (interface, adaptadores, `GuardedLLM`, cota, fábrica) |
| `tools/` | `smoke_llm.py` e as 15 mensagens escritas à mão |
| `analysis/` | Scripts de análise (só agregados) e `results/` |
| `tests/` | Higiene do repo, análises, integração com a API |
| `docs/` | `PLAN.md`, `FINDINGS.md` |
| `vendor/` | **Tudo que veio do desafio**, sem modificação: `vendor/quote-service/` (ver [`NOTICE.md`](NOTICE.md)). O resto do repo é autoral |

## Dados sensíveis

O dataset do desafio é sintético, mas é tratado como sensível. Ele não é copiado para este repositório (o caminho vem de
`DATASET_PATH`). Há testes que reprovam o repo se aparecer PII, segredo ou qualquer trecho de mensagem do dataset
(`tests/test_repo_hygiene.py`). Nenhum documento aqui cita linhas do dataset, só números agregados.

**A chave do provedor de LLM fica no `.env` (ignorado pelo git) e a sessão do Claude Code que desenvolve este repo não deve lê-lo.**
[`.claude/settings.json`](.claude/settings.json) nega `Read` e `Edit` do `.env` e das variantes (menos o `.env.example`) e, como camada de melhor esforço, os comandos de shell que citam o arquivo.
Limites, ditos sem rodeio: (1) a regra só vale em uma sessão aberta **depois** que o arquivo existe, e foi **escrita mas não confirmada** na sessão em que nasceu (a leitura de uma isca passou); (2) a regra de `Bash` casa texto, então um comando que lê o `.env` sem escrever o nome dele (um `grep -r .`, um script) não é pego. **Ela é um freio, não é uma barreira.** A barreira de verdade é o sandbox do Claude Code com `sandbox.filesystem.denyRead`, que aplica o bloqueio ao sistema de arquivos; ele não foi ligado aqui porque restringiria a rede e o acesso ao Docker, de que `make test-integration` e o `pip` dependem (não testei o efeito).
`make llm-ping` lê a chave por dentro do processo e só imprime `chave: configurada`, nunca o valor, o prefixo nem o tamanho.
Para verificar a regra numa sessão nova, peça a ela que leia `var/decoy/.env` (um arquivo isca, com conteúdo falso, ignorado pelo git): se ler, a regra não carregou.
