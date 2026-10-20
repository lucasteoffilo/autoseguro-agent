# Achados: API de cotação e dataset

Data da análise: 2026-10-20. Tudo aqui é reproduzível com os scripts de `analysis/`; as saídas brutas estão em
`analysis/results/`. **Este documento não contém nenhuma linha do dataset**, só agregados e descrição de comportamento.

## Resumo

1. A `/quote` falha em ~20% das chamadas (5xx instantâneo) e é lenta em ~10% (exatamente 8s, mas **responde 200 válido**).
2. Há dois tipos de 422 com o mesmo status e formatos diferentes, e vários casos em que a API devolve **200 com preço errado em vez de erro**.
3. Os preços do vendedor no dataset são aleatórios: não servem de referência para nada.
4. 30% das conversas do dataset são de leads que a API recusaria.
5. O dataset não tem nenhum caso de handoff, reclamação, sinistro, cancelamento ou falha técnica.

---

## 1. API de cotação

Código lido: `vendor/quote-service/app/main.py`, `quote_logic.py`, `data/plans.json`. Comportamento medido contra a imagem do Docker.

### 1.1 Falhas simuladas

| Medição | Resultado |
|---|---|
| 400 chamadas com a instabilidade padrão (30 em paralelo) | 323 × 200, 77 × 5xx (31 × 500, 21 × 502, 25 × 503) |
| Taxa de 5xx | **19,3%** (código: 20%) |
| Taxa de respostas lentas | **10,0%** (código: 10%), todas com 8,00s e corpo 200 válido |
| Latência dos 200 rápidos / dos 5xx | até 0,11s / até 0,11s |
| Corpo dos 5xx | sempre o mesmo `upstream_unavailable` com "tente novamente" |

Uma primeira amostra de 150 chamadas deu só 5% de lentas: era ruído de amostra, e as 400 chamadas confirmam o código.
A resposta lenta **não é falha**: um timeout menor que 8s transforma sucesso em falha e ainda deixa o servidor trabalhando.

### 1.2 O sorteio de falha vem antes da lógica de negócio

Com a API 100% fora do ar (`QUOTE_FAILURE_RATE=1`, evidência em `api_probe_outage.txt`):

- Idade 80 (que seria recusa 422) e ano de veículo muito antigo (recusa 422) devolvem **5xx**.
- Uma `data_inicio` inválida (que seria 400) devolve **5xx**.
- Campo obrigatório ausente continua devolvendo 422, porque a validação do pydantic roda antes do sorteio.

Consequência: uma recusa só é visível em ~80% das tentativas. "Falhou" nunca significa "foi recusado".

### 1.3 Dois 422 diferentes

| Origem | Formato | Exemplo |
|---|---|---|
| Regra de negócio | `{"error": "cotacao_recusada", "motivo": "..."}` | idade > 75, veículo com mais de 20 anos, plano inexistente |
| Validação do pydantic | `{"detail": [{"loc": [...], "msg": "..."}]}` | idade fora de 0–200, CEP numérico, JSON malformado |

O status é o mesmo. Só o corpo distingue. Além disso, um **plano mal digitado** (`"completo "` com espaço) vem como `cotacao_recusada`, embora seja erro de entrada.

### 1.4 Regras confirmadas nas bordas (`api_probe_rules.txt`)

- Idade: 18–24 ×1,60 | 25–29 ×1,25 | 30–59 ×1,00 | 60–75 ×1,40 | 76+ recusa. Idades 0–17 também são recusadas, como "fora das faixas".
- Veículo (ano do servidor menos ano do veículo): 0–5 ×1,00 | 6–10 ×1,15 | 11–20 ×1,45 | 21+ recusa.
- CEP de alto risco (prefixos 07, 08, 21, 26, 59): ×1,30.
- **Ano-modelo futuro é recusado**: um veículo de ano seguinte ao atual vem como "fora das faixas aceitas", mensagem enganosa para algo que já existe à venda.
- O relógio do servidor define a idade do veículo, então os limites se movem a cada 1º de janeiro.

### 1.5 "200 silenciosamente errado" (o risco mais perigoso)

A API aceita e devolve preço, sem aviso, nestes casos:

| Entrada | O que acontece |
|---|---|
| CEP ausente, vazio, `null`, `abc`, `00000-000` | Sem agravo regional |
| CEP de alto risco **sem o zero à esquerda** (7 dígitos) | Sem agravo: preço ~23% menor que o correto |
| `plano_id` vazio ou omitido | Cota **Essencial** (o mais barato) em silêncio |
| `data_inicio` ausente, vazia ou `null` | Sem pro-rata |
| `data_inicio` 90 dias **no passado** ou 3 anos no futuro | Aceita e calcula pro-rata como se fosse válida |
| `data_inicio` em `aaaammdd` | Aceita |
| Campo extra desconhecido | Ignorado |

Efeito sobre o desenho: o agente valida e normaliza **antes** de chamar e confere o `plano_id` da resposta. A API não valida nada disso por ele.

### 1.6 Outras propriedades

- A resposta 200 **não traz id, validade nem timestamp**: a rastreabilidade é nossa.
- A mensalidade (`premio_mensal`) **não é o primeiro pagamento** quando a vigência começa fora do dia 1.
- Roubo e furto têm carência de 30 dias a partir do início da vigência.
- `QUOTE_SEED` torna a sequência de falhas reproduzível: a mesma sequência de 40 chamadas se repetiu idêntica após reiniciar o container (`api_probe_seed.txt`). Só vale se a ordem das chamadas for a mesma.
- `/health` e `/planos` não têm falha injetada. `/planos` publica todas as regras, o que permite uma pré-checagem orientada a dados.

---

## 2. Dataset de conversas

2.500 conversas, 26.470 mensagens, sem nulos nem duplicatas. Perfil completo em `analysis/results/dataset_profile.json`.

### 2.1 O que presta

- Estrutura e tom de uma conversa de WhatsApp: 8 a 14 mensagens por conversa (mediana 11).
- Objeções recorrentes (preço, franquia, concorrente mais barato, adiamento da decisão, consulta a terceiros).
- Massa de teste: 751 conversas (30,0%) são de leads que a API recusaria, 283 delas na borda das regras.
- Formatos de PII para testar o mascaramento.
- Mídia (57% das conversas têm documento, imagem ou áudio **sem transcrição**): serve para testar o tratamento de mídia ilegível.

### 2.2 Armadilhas e problemas

| Achado | Número |
|---|---|
| Preço do vendedor vs preço real da API | Bate em ±5% em **3,7%** dos casos; razão entre 0,13× e 3,25×; correlação de postos **0,00** |
| Cobertura citada pelo vendedor | **Uma única** frase para os três planos; nunca menciona carência |
| Preço por plano | Médias praticamente iguais entre Essencial, Completo e Premium (R$ 255, 249 e 253) |
| Desfecho vs qualquer variável | "Ganho" em 27–30% em todos os cortes (plano, preço, idade, CEP). **Sem sinal** para aprender o que converte |
| Leads que a API recusaria | 11,2% por idade, 21,2% por veículo; **203 deles aparecem como "ganho"** |
| Timestamps | **99,8%** das conversas têm timestamp voltando no tempo (7.904 mensagens). Ordenar por `message_index`, nunca por timestamp |
| Colunas de nível-conversa repetidas em toda linha | Idade, veículo e desfecho já estão na mensagem 0: **vazamento de gabarito** em qualquer replay |
| `veiculo_texto` | O dicionário diz "texto livre"; na prática é **100% limpo** (`Marca Modelo Ano`) |
| Formatos de PII | O dicionário diz "variados"; na prática são fixos (CPF sempre pontuado, telefone sempre com +55). Um mascarador calibrado aqui pode falhar fora |
| Regex de CEP sem rótulo | Casa com o final de **1.379 telefones**; o CEP precisa de rótulo ou de ordem de aplicação |
| Rótulo "CPF" | Aparece como `cpf` (1.682) ou `Cpf` (818): o regex tem que ignorar maiúsculas |
| Diversidade | 2.277 textos distintos entre 16.470 mensagens de lead (dígitos normalizados); os 10 mais comuns são 40,7% do total |

### 2.3 PII

| Dado | Presença |
|---|---|
| CPF | 100% das conversas |
| E-mail e telefone | 55,2% |
| Placa | 33,6% |
| Nome do lead (em `sender_name`) | 336 nomes distintos |
| Nome na saudação do vendedor | 100% das conversas |

Nome não é pego por regex de CPF/e-mail/telefone. O vendedor pede o CPF para cotar, mas a API **não usa** CPF: o agente não pede (minimização).

### 2.4 O que o dataset não cobre

Zero ocorrências de pedido de humano, sinistro, reclamação, cancelamento, carência ou erro técnico. O critério de handoff e os cenários de falha são
desenho nosso, com casos sintéticos escritos à mão.

---

## 3. Latência: decisão do cliente

Tabela completa e justificativa em `docs/PLAN.md` (seção 3) e `analysis/results/latency_sim.md`.
Resumo: política **B** (timeout 10s, retry só em 5xx, 4 chamadas, orçamento de 15s) tem a menor carga (1,25 chamada/cotação) e 0,15% de cotações sem resposta no orçamento; o hedging foi descartado.

## 4. Riscos e como atacar

| Risco | Ataque | Etapa |
|---|---|---|
| Instabilidade (5xx e lentidão) | Política B, "um instante" aos 2,5s | 1 |
| API fora do ar | Nunca estimar preço; handoff `QUOTE_UNAVAILABLE` honesto | 2 |
| Dois 422 e erro disfarçado de recusa | Resultado tipado, classificado pelo corpo | 1 |
| 5xx mascara recusa | Recusa só é dita após confirmação da API | 3 |
| 200 silenciosamente errado | Normalização e validação antes de chamar; conferir `plano_id` | 1 |
| LLM errar número | Números só por template; guardrail de saída | 1, 4 |
| Sem id na API | `trace_id`, `quote_id` e tentativas próprios | 2 |
| PII | Mascarar antes de LLM, banco e log; não pedir CPF | 2 |
| Dataset não ensina preço nem conversão | Usar só tom, objeções e cenários; oráculo é a API | 6 |
| Idade do veículo depende do relógio | Datas relativas, semente fixa | 1, 3 |

## 5. Limites desta análise

- O modelo de latência segue o mock; um legado real tem falhas correlacionadas.
- O dataset é sintético e gerado por `scripts/generate_dataset.py` do desafio: várias das armadilhas acima são do gerador, e confirmá-las nos dados foi o objetivo.
- Os testes de borda cobrem o que foi sondado; a pré-checagem terá teste de contrato próprio (Etapa 3).
