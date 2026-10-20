> Latencia do LLM = HIPOTESE (TTFT + 128 tokens de saida / velocidade; cenario 'reply_40_slots_compactos'), nao medicao. /quote = modelo medido (politica B). Fast-path cobre 0% dos turnos (desligado por padrao).

**Nominal (5xx 20% / lenta 10%)** (so a /quote, sem LLM: p50 0.29s, p95 8.14s, p99 8.51s)

| Perfil LLM (p50/p95 de uma chamada) | Turno sem cotacao p95 | Turno com cotacao p50 | p95 | p99 | 'um instante' | Handoff | Mensagem qualquer: p95 |
|---|---|---|---|---|---|---|---|
| rapido (0.86s/2.15s) | 2.25s | 1.3s | 9.21s | 10.17s | 17.8% | 0.15% | 2.76s |
| medio (2.02s/5.06s) | 5.15s | 2.6s | 10.61s | 12.59s | 52.6% | 0.2% | 7.15s |
| lento (3.91s/9.77s) | 12.37s | 4.67s | 12.55s | 18.07s | 87.1% | 5.25% | 12.4s |

**Degradado (5xx 50% / lenta 20%)** (so a /quote, sem LLM: p50 1.22s, p95 9.03s, p99 10.12s)

| Perfil LLM (p50/p95 de uma chamada) | Turno sem cotacao p95 | Turno com cotacao p50 | p95 | p99 | 'um instante' | Handoff | Mensagem qualquer: p95 |
|---|---|---|---|---|---|---|---|
| rapido (0.86s/2.15s) | 2.25s | 2.56s | 10.38s | 11.4s | 50.7% | 6.29% | 9.02s |
| medio (2.02s/5.06s) | 5.15s | 4.2s | 12.38s | 15.03s | 74.0% | 6.36% | 10.16s |
| lento (3.91s/9.77s) | 12.37s | 8.66s | 16.92s | 19.69s | 93.5% | 11.57% | 12.4s |

**O reply curto resolve o perfil medio? p95 do turno, nominal (criterio: 5s sem cotacao, 12s com)**

| Cenario de saida | Tokens | rapido: sem / com cotacao | medio: sem / com cotacao | lento: sem / com cotacao |
|---|---|---|---|---|
| so_slots_verboso | 110 | 2.08s ok / 9.13s ok | 4.66s ok / 10.34s ok | 11.09s FALHA / 12.4s FALHA |
| reply_sem_teto | 190 | 2.87s ok / 9.49s ok | 8.54s FALHA / 11.67s ok | 12.4s FALHA / 13.03s FALHA |
| reply_40_palavras | 183 | 2.8s ok / 9.46s ok | 8.27s FALHA / 11.53s ok | 12.4s FALHA / 13.02s FALHA |
| reply_40_slots_compactos | 128 | 2.25s ok / 9.21s ok | 5.16s FALHA / 10.61s ok | 12.33s FALHA / 12.56s FALHA |

**Limite por chamada DERIVADO do criterio do turno** (p95 da chamada = 2.5 x p50; cenario nominal da /quote)

- turno sem cotacao (p95 <= 5s): chamada com p50 <= 1.96s, p95 <= 4.91s
- turno com cotacao (p95 <= 12s): chamada com p50 <= 2.9s, p95 <= 7.24s
- **restricao ativa: no_quote_turn; p95 por chamada <= 4.91s**

**Sensibilidade a cobertura do fast-path (p95 de uma mensagem qualquer, nominal)**

| Perfil | 0% | 30% | 40% |
|---|---|---|---|
| rapido | 2.74s | 2.58s | 2.47s |
| medio | 7.08s | 5.7s | 5.45s |
| lento | 12.4s | 12.17s | 11.83s |

**Varredura do p50 do LLM (p95 = 2,5x p50), cenario nominal**

| LLM p50 | LLM p95 | Turno sem cotacao p95 | <= 5s | Turno com cotacao p95 | <= 12s |
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
