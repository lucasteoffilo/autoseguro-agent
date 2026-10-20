> Latencia do LLM = HIPOTESE (TTFT + 190 tokens de saida / velocidade), nao medicao. /quote = modelo medido (politica B). Fast-path estrito cobre 30% dos turnos.

**Nominal (5xx 20% / lenta 10%)** (so a /quote, sem LLM: p50 0.29s, p95 8.14s, p99 8.51s)

| Perfil LLM (p50/p95 de uma chamada) | Turno sem cotacao p95 | Turno com cotacao p50 | p95 | p99 | 'um instante' | Handoff | Mensagem qualquer: p95 | Cotacao com LLM fora do caminho critico: p95 |
|---|---|---|---|---|---|---|---|---|
| rapido (1.11s/2.77s) | 2.87s | 1.58s | 9.5s | 10.68s | 23.7% | 0.15% | 3.22s | 8.14s |
| medio (2.71s/6.78s) | 8.58s | 3.35s | 11.69s | 14.09s | 70.1% | 0.75% | 9.15s | 8.14s |
| lento (5.32s/13.3s) | 12.4s | 6.31s | 13.04s | 19.08s | 95.1% | 17.71% | 12.4s | 8.14s |

**Degradado (5xx 50% / lenta 20%)** (so a /quote, sem LLM: p50 1.22s, p95 9.03s, p99 10.12s)

| Perfil LLM (p50/p95 de uma chamada) | Turno sem cotacao p95 | Turno com cotacao p50 | p95 | p99 | 'um instante' | Handoff | Mensagem qualquer: p95 | Cotacao com LLM fora do caminho critico: p95 |
|---|---|---|---|---|---|---|---|---|
| rapido (1.11s/2.77s) | 2.87s | 2.9s | 10.79s | 12.0s | 55.4% | 6.29% | 9.27s | 9.03s |
| medio (2.71s/6.78s) | 8.58s | 5.24s | 13.53s | 17.8s | 84.3% | 7.03% | 11.06s | 9.03s |
| lento (5.32s/13.3s) | 12.4s | 11.21s | 18.47s | 20.0s | 97.7% | 24.0% | 12.4s | 9.03s |

**Impacto de o LLM redigir a resposta na mesma chamada (110 -> 190 tokens de saida), cenario nominal**

| Perfil | LLM p50 (antes -> depois) | Turno sem cotacao p95 | Turno com cotacao p95 | Mensagem qualquer p95 | 'Um instante' (mensagem qualquer) |
|---|---|---|---|---|---|
| rapido | 0.79s -> 1.11s | 2.08s -> 2.87s | 9.13s -> 9.49s | 2.4s -> 3.24s | 4.6% -> 9.1% |
| medio | 1.82s -> 2.71s | 4.66s -> 8.54s | 10.34s -> 11.67s | 5.15s -> 9.21s | 24.9% -> 43.3% |
| lento | 3.5s -> 5.32s | 11.09s -> 12.4s | 12.4s -> 13.03s | 11.2s -> 12.4s | 54.1% -> 65.0% |

**Sensibilidade a cobertura do fast-path (p95 de uma mensagem qualquer, nominal, 190 tokens)**

| Perfil | 0% | 30% | 40% |
|---|---|---|---|
| rapido | 3.46s | 3.24s | 3.1s |
| medio | 9.68s | 9.21s | 8.94s |
| lento | 12.4s | 12.4s | 12.4s |

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
