> Latencia do LLM = HIPOTESE (perfis parametricos), nao medicao. /quote = modelo medido (politica B).

**Nominal (5xx 20% / lenta 10%)** (so a /quote, sem LLM: p50 0.29s, p95 8.14s, p99 8.51s)

| Perfil LLM (p50/p95) | Turno sem cotacao p95 | Turno com cotacao p50 | p95 | p99 | 'um instante' | Handoff | Cotacao com LLM fora do caminho critico: p95 |
|---|---|---|---|---|---|---|---|
| rapido (0.8s/2.0s) | 2.1s | 1.24s | 9.14s | 10.04s | 16.7% | 0.15% | 8.14s |
| medio (1.8s/4.5s) | 4.59s | 2.35s | 10.32s | 12.13s | 45.8% | 0.17% | 8.14s |
| lento (3.5s/9.0s) | 11.26s | 4.24s | 12.4s | 17.43s | 82.2% | 3.31% | 8.14s |

**Degradado (5xx 50% / lenta 20%)** (so a /quote, sem LLM: p50 1.22s, p95 9.03s, p99 10.12s)

| Perfil LLM (p50/p95) | Turno sem cotacao p95 | Turno com cotacao p50 | p95 | p99 | 'um instante' | Handoff | Cotacao com LLM fora do caminho critico: p95 |
|---|---|---|---|---|---|---|---|
| rapido (0.8s/2.0s) | 2.1s | 2.48s | 10.27s | 11.28s | 49.8% | 6.29% | 9.03s |
| medio (1.8s/4.5s) | 4.59s | 3.87s | 11.98s | 13.89s | 70.0% | 6.31% | 9.03s |
| lento (3.5s/9.0s) | 11.26s | 6.72s | 15.82s | 19.29s | 90.9% | 9.63% | 9.03s |

**Varredura do p50 do LLM (p95 = 2,5x p50), cenario nominal**

| LLM p50 | LLM p95 | Turno sem cotacao p95 | C2 (<= 5s) | Turno com cotacao p95 | C3 (<= 12s) |
|---|---|---|---|---|---|
| 0.5s | 1.25s | 1.35s | ok | 8.79s | ok |
| 1.0s | 2.5s | 2.6s | ok | 9.37s | ok |
| 1.5s | 3.75s | 3.85s | ok | 9.95s | ok |
| 2.0s | 5.0s | 5.1s | FALHA | 10.59s | ok |
| 3.0s | 7.5s | 9.55s | FALHA | 12.21s | FALHA |
| 4.0s | 10.0s | 12.4s | FALHA | 12.59s | FALHA |
| 5.0s | 12.5s | 12.4s | FALHA | 13.01s | FALHA |
| 6.0s | 15.0s | 12.4s | FALHA | 13.11s | FALHA |
| 8.0s | 20.0s | 12.4s | FALHA | 12.64s | FALHA |
