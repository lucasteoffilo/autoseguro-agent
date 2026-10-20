> Tokens = ESTIMATIVA (+-35%); precos = tabela da skill claude-api (2026-10-06). Valores em USD; converter pelo cambio do dia.

Cache do prefixo estatico so compensa com taxa de acerto > **21.7%** (abaixo disso o premio de escrita de 1,25x custa mais que poupa).

**Tokens por conversa (LLM redige a resposta; hit de cache 95%)**

| Conversa | Entrada total | Dela, lida do cache | Saida | Saida antes (so slots) |
|---|---|---|---|---|
| com fast-path (5 chamadas) | 13,200 | 10,450 | 640 | 550 |
| sem fast-path (8 chamadas) | 21,120 | 16,720 | 1,024 | 880 |
| conversa dificil (12 chamadas) | 31,680 | 25,080 | 1,536 | 1,320 |

**USD por conversa (sem thinking residual)**

| Estrategia | Conversa | Sem cache | Cache hit 95% | Cache hit 0% | Por 1.000 conversas (hit 95%) |
|---|---|---|---|---|---|
| Haiku 5.5 | com fast-path (5 chamadas) | $0.0016 | $0.0007 | $0.0019 | $0.71 |
| Haiku 5.5 | sem fast-path (8 chamadas) | $0.0026 | $0.0011 | $0.0031 | $1.14 |
| Haiku 5.5 | conversa dificil (12 chamadas) | $0.0039 | $0.0017 | $0.0046 | $1.71 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | com fast-path (5 chamadas) | $0.0049 | $0.0040 | $0.0052 | $3.99 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | sem fast-path (8 chamadas) | $0.0079 | $0.0064 | $0.0083 | $6.39 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | conversa dificil (12 chamadas) | $0.0118 | $0.0096 | $0.0125 | $9.58 |
| Sonnet 5.5 | com fast-path (5 chamadas) | $0.0328 | $0.0143 | $0.0383 | $14.26 |
| Sonnet 5.5 | sem fast-path (8 chamadas) | $0.0525 | $0.0228 | $0.0613 | $22.82 |
| Sonnet 5.5 | conversa dificil (12 chamadas) | $0.0787 | $0.0342 | $0.0919 | $34.24 |
| Opus 5.5 | com fast-path (5 chamadas) | $0.0656 | $0.0264 | $0.0766 | $26.44 |
| Opus 5.5 | sem fast-path (8 chamadas) | $0.1050 | $0.0423 | $0.1226 | $42.30 |
| Opus 5.5 | conversa dificil (12 chamadas) | $0.1574 | $0.0635 | $0.1838 | $63.46 |

**Impacto de o LLM redigir a resposta na mesma chamada (conversa de 8 chamadas)**

| Estrategia / cache | Antes (so slots) | Depois (com reply) | Variacao |
|---|---|---|---|
| haiku | sem cache | $0.0020 | $0.0026 | +31.7% |
| haiku | cache, hit 95% (trafego continuo) | $0.0010 | $0.0011 | +16.3% |
| haiku+sonnet | sem cache | $0.0060 | $0.0079 | +31.7% |
| haiku+sonnet | cache, hit 95% (trafego continuo) | $0.0050 | $0.0064 | +28.7% |
| sonnet | sem cache | $0.0398 | $0.0525 | +31.7% |
| sonnet | cache, hit 95% (trafego continuo) | $0.0196 | $0.0228 | +16.3% |

Sensibilidade a saida verbosa (183 tokens em vez de 128; Haiku, 8 chamadas, sem cache): $0.0026 -> $0.0028.

Sensibilidade (conversa de 8 chamadas, sem cache): thinking residual de 250 tokens/chamada leva o Haiku 5.5 de $0.0026 para $0.0036 e o Sonnet 5.5 de $0.0525 para $0.0725.
