# Análises

Scripts que sustentam `docs/FINDINGS.md` e `docs/PLAN.md`. Regras do projeto:

- A saída é **só agregado** (números e rótulos de enum). Nenhum texto de mensagem do dataset é impresso ou gravado.
- O parquet é dado externo: não está no repo. O caminho vem de `DATASET_PATH` (padrão do Makefile: o clone do desafio ao lado deste repo).
- Rode com `python -I` (modo isolado) e passe caminhos como argumento.

## Scripts

| Script | O que faz | Como rodar |
|---|---|---|
| `dataset_profile.py` | Perfil agregado do dataset (estrutura, timestamps, vazamento de colunas, elegibilidade, PII, preço do vendedor vs API, sinal do desfecho) | `make analysis-dataset` |
| `latency_sim.py` | Monte Carlo das políticas de cliente A, B e C | `make analysis-latency` |
| `e2e_latency_sim.py` | Latência por mensagem somando LLM e `/quote`. **A latência do LLM é hipótese**, e o script varre o p50 para mostrar onde cada critério quebra | `make analysis-e2e` |
| `cost_model.py` | Tokens e dólares por conversa, por modelo e por política de cache. **Tokens são estimativa; preços são da tabela da skill `claude-api`** | `make analysis-cost` |
| `api_probe.py` | Sondagem do comportamento do `/quote` (precisa da API no ar) | ver abaixo |

As regras de elegibilidade e preço são lidas de `vendor/quote-service/data/plans.json`, não copiadas para os scripts.

## `api_probe.py`: qual instância usar

Cada modo precisa de uma configuração diferente da API. As saídas que estão em `results/` foram geradas assim:

| Modo | Instância | Saída |
|---|---|---|
| `rules --port 8100` | `make api-test-up` (sem falha e sem lentidão) | `results/api_probe_rules.txt` |
| `outage --port N` | container com `QUOTE_FAILURE_RATE=1` | `results/api_probe_outage.txt` |
| `seq --port N` | container com `QUOTE_SEED=42`, `QUOTE_FAILURE_RATE=0.5`, `QUOTE_SLOW_RATE=0` (rodado duas vezes, com restart) | `results/api_probe_seed.txt` |
| `stats --port N` | container com a instabilidade padrão (0,20 / 0,10 / 8s), 400 chamadas, 30 em paralelo | `results/api_probe_stats.txt` |

Os containers descartáveis usam a imagem `autoseguro-quote-api:local` (criada por `make api-test-up`):

```bash
docker run -d --rm --name qprobe-down -p 8101:8000 -e QUOTE_FAILURE_RATE=1 -e QUOTE_SLOW_RATE=0 autoseguro-quote-api:local
```

Datas e anos de veículo da sondagem são relativos a hoje, então o script continua válido quando virar o ano.
Os arquivos de `results/` registram a data em que foram gerados.
