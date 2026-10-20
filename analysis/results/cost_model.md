> Tokens = ESTIMATIVA (+-35%); precos = tabela da skill claude-api (2026-10-06). Valores em USD; converter pelo cambio do dia.

Cache do prefixo estatico so compensa com taxa de acerto > **21.7%** (abaixo disso o premio de escrita de 1,25x custa mais que poupa).

**Tokens por conversa (hit de cache 95%)**

| Conversa | Entrada total | Dela, lida do cache | Saida |
|---|---|---|---|
| com fast-path (5 chamadas) | 9,700 | 7,125 | 550 |
| sem fast-path (8 chamadas) | 15,520 | 11,400 | 880 |
| conversa dificil (12 chamadas) | 23,280 | 17,100 | 1,320 |

**USD por conversa (sem thinking residual)**

| Estrategia | Conversa | Sem cache | Cache hit 95% | Cache hit 0% | Por 1.000 conversas (hit 95%) |
|---|---|---|---|---|---|
| Haiku 5.5 | com fast-path (5 chamadas) | $0.0013 | $0.0006 | $0.0014 | $0.61 |
| Haiku 5.5 | sem fast-path (8 chamadas) | $0.0020 | $0.0010 | $0.0023 | $0.98 |
| Haiku 5.5 | conversa dificil (12 chamadas) | $0.0030 | $0.0015 | $0.0034 | $1.47 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | com fast-path (5 chamadas) | $0.0037 | $0.0031 | $0.0039 | $3.10 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | sem fast-path (8 chamadas) | $0.0060 | $0.0050 | $0.0063 | $4.97 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | conversa dificil (12 chamadas) | $0.0090 | $0.0075 | $0.0094 | $7.45 |
| Sonnet 5.5 | com fast-path (5 chamadas) | $0.0249 | $0.0123 | $0.0286 | $12.26 |
| Sonnet 5.5 | sem fast-path (8 chamadas) | $0.0398 | $0.0196 | $0.0458 | $19.62 |
| Sonnet 5.5 | conversa dificil (12 chamadas) | $0.0598 | $0.0294 | $0.0688 | $29.43 |
| Opus 5.5 | com fast-path (5 chamadas) | $0.0498 | $0.0231 | $0.0573 | $23.10 |
| Opus 5.5 | sem fast-path (8 chamadas) | $0.0797 | $0.0370 | $0.0917 | $36.96 |
| Opus 5.5 | conversa dificil (12 chamadas) | $0.1195 | $0.0554 | $0.1375 | $55.44 |

Sensibilidade (conversa de 8 chamadas, sem cache): thinking residual de 250 tokens/chamada leva o Haiku 5.5 de $0.0020 para $0.0030 e o Sonnet 5.5 de $0.0398 para $0.0598.
