# AutoSeguro Agent

Agente de vendas de seguro auto para o desafio técnico FDE / AI Engineer da Namastex: conversa com o lead,
qualifica, cota um plano pela API de cotação e decide entre resolver sozinho e passar para um humano.

> **Estado: Etapas 0 e 1 concluídas (fundação, análise e decisões de desenho); o roteiro vai até a Etapa 8.** O agente ainda não existe:
> só o contrato do destino do handoff (`src/autoseguro/handoff.py`).
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

O cliente (Etapa 1) não terá parâmetro de hedging; já existe um teste que impede que ele apareça em `src/`. Limite do modelo: o
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

### D3. Modelo por passo, latência fim a fim e custo _(provisório até a medição com o modelo real)_

Resumo; as tabelas e as premissas estão em [`docs/PLAN.md`](docs/PLAN.md), seção 5.

- **O gargalo do p95 de um turno com cotação é o modo lento de 8s da `/quote`, não o LLM** (8,1s sozinha; 9 a 10s somando um LLM rápido ou médio). O LLM decide a latência dos turnos **sem** cotação.
- **Cortes:** fast-path por regex para respostas simples (tira o LLM de ~40% dos turnos e do caminho crítico da cotação); modelo pequeno na extração;
  "um instante" aos 2,5s só em turno que chama a `/quote`; timeout de 6s por chamada de LLM e prazo de 20s por turno.
- **Modelo:** `claude-haiku-5-5` na extração (esforço baixo, saída estruturada), escalonando uma vez para `claude-sonnet-5-5` quando a saída vier inválida ou ambígua.
  Texto ao lead e resumo de handoff não usam LLM. **Custo:** centavos por conversa (de ~US$ 0,001 a ~US$ 0,006), então latência e precisão decidem, não preço.
- **O que ainda é hipótese:** a latência do LLM e a contagem de tokens. A Etapa 4a mede as duas com chamadas reais.

### Demais decisões

Pré-checagem de elegibilidade, recusa, objeção de preço, necessidade → plano, modo mock do LLM, persistência: ver
[`docs/PLAN.md`](docs/PLAN.md), seção 2.

## Estrutura

| Caminho | Conteúdo |
|---|---|
| `src/autoseguro/` | Código do produto (hoje: o contrato do destino do handoff) |
| `analysis/` | Scripts de análise (só agregados) e `results/` |
| `tests/` | Higiene do repo, análises, integração com a API |
| `docs/` | `PLAN.md`, `FINDINGS.md` |
| `vendor/` | **Tudo que veio do desafio**, sem modificação: `vendor/quote-service/` (ver [`NOTICE.md`](NOTICE.md)). O resto do repo é autoral |

## Dados sensíveis

O dataset do desafio é sintético, mas é tratado como sensível. Ele não é copiado para este repositório (o caminho vem de
`DATASET_PATH`). Há testes que reprovam o repo se aparecer PII, segredo ou qualquer trecho de mensagem do dataset
(`tests/test_repo_hygiene.py`). Nenhum documento aqui cita linhas do dataset, só números agregados.
