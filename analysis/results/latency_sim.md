Orcamento 15s por cotacao; mensagem de espera aos 2.5s.

**Nominal (5xx 20% / lenta 10%)**

| Politica | p50 | p95 | p99 | Sem cotacao em 15s | Chamadas por cotacao | Msg 'um instante' |
|---|---|---|---|---|---|---|
| A) timeout 2s + retry | 0.19s | 2.52s | 4.75s | 0.78% | 1.42 | 5.8% |
| B) timeout 10s, retry so em 5xx (adotada) | 0.19s | 8.04s | 8.42s | 0.15% | 1.25 | 12.6% |
| C) hedge aos 2s (descartada) | 0.19s | 2.47s | 6.12s | 0.15% | 1.42 | 4.8% |

**Degradado (5xx 50% / lenta 20%)**

| Politica | p50 | p95 | p99 | Sem cotacao em 15s | Chamadas por cotacao | Msg 'um instante' |
|---|---|---|---|---|---|---|
| A) timeout 2s + retry | 0.5s | 4.21s | 5.96s | 23.89% | 2.53 | 31.8% |
| B) timeout 10s, retry so em 5xx (adotada) | 0.97s | 8.96s | 10.04s | 6.23% | 1.87 | 37.7% |
| C) hedge aos 2s (descartada) | 0.97s | 8.9s | 10.04s | 6.19% | 2.53 | 30.0% |

**Politica B, nominal: efeito do maximo de chamadas**

| max_calls | Sem cotacao em 15s | Chamadas por cotacao |
|---|---|---|
| 2 | 4.01% | 1.2 |
| 3 | 0.79% | 1.24 |
| 4 | 0.15% | 1.25 |
| 5 | 0.03% | 1.25 |
