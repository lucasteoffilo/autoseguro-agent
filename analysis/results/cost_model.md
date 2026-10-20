> Tokens = ESTIMATIVA (+-35%); precos = tabela da skill claude-api (2026-10-06). Valores em USD; converter pelo cambio do dia.

Cache do prefixo estatico so compensa com taxa de acerto > **21.7%** (abaixo disso o premio de escrita de 1,25x custa mais que poupa).

**Tokens por conversa (LLM redige a resposta; hit de cache 95%)**

| Conversa | Entrada total | Dela, lida do cache | Saida | Saida antes (so slots) |
|---|---|---|---|---|
| com fast-path (5 chamadas) | 12,200 | 9,500 | 950 | 550 |
| sem fast-path (8 chamadas) | 19,520 | 15,200 | 1,520 | 880 |
| conversa dificil (12 chamadas) | 29,280 | 22,800 | 2,280 | 1,320 |

**USD por conversa (sem thinking residual)**

| Estrategia | Conversa | Sem cache | Cache hit 95% | Cache hit 0% | Por 1.000 conversas (hit 95%) |
|---|---|---|---|---|---|
| Haiku 5.5 | com fast-path (5 chamadas) | $0.0017 | $0.0008 | $0.0019 | $0.85 |
| Haiku 5.5 | sem fast-path (8 chamadas) | $0.0027 | $0.0014 | $0.0031 | $1.36 |
| Haiku 5.5 | conversa dificil (12 chamadas) | $0.0041 | $0.0021 | $0.0047 | $2.05 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | com fast-path (5 chamadas) | $0.0051 | $0.0042 | $0.0053 | $4.24 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | sem fast-path (8 chamadas) | $0.0081 | $0.0068 | $0.0085 | $6.79 |
| Haiku 5.5 + 10% escalonado p/ Sonnet 5.5 | conversa dificil (12 chamadas) | $0.0122 | $0.0102 | $0.0128 | $10.18 |
| Sonnet 5.5 | com fast-path (5 chamadas) | $0.0339 | $0.0170 | $0.0389 | $17.05 |
| Sonnet 5.5 | sem fast-path (8 chamadas) | $0.0542 | $0.0273 | $0.0622 | $27.28 |
| Sonnet 5.5 | conversa dificil (12 chamadas) | $0.0814 | $0.0409 | $0.0934 | $40.92 |
| Opus 5.5 | com fast-path (5 chamadas) | $0.0678 | $0.0322 | $0.0778 | $32.20 |
| Opus 5.5 | sem fast-path (8 chamadas) | $0.1085 | $0.0515 | $0.1245 | $51.52 |
| Opus 5.5 | conversa dificil (12 chamadas) | $0.1627 | $0.0773 | $0.1867 | $77.28 |

**Impacto de o LLM redigir a resposta na mesma chamada (conversa de 8 chamadas)**

| Estrategia / cache | Antes (so slots) | Depois (com reply) | Variacao |
|---|---|---|---|
| haiku | sem cache | $0.0020 | $0.0027 | +36.1% |
| haiku | cache, hit 95% (trafego continuo) | $0.0010 | $0.0014 | +39.0% |
| haiku+sonnet | sem cache | $0.0060 | $0.0081 | +36.1% |
| haiku+sonnet | cache, hit 95% (trafego continuo) | $0.0050 | $0.0068 | +36.7% |
| sonnet | sem cache | $0.0398 | $0.0542 | +36.1% |
| sonnet | cache, hit 95% (trafego continuo) | $0.0196 | $0.0273 | +39.0% |

Sensibilidade (conversa de 8 chamadas, sem cache): thinking residual de 250 tokens/chamada leva o Haiku 5.5 de $0.0027 para $0.0037 e o Sonnet 5.5 de $0.0542 para $0.0742.
