# Backlog

O que ficou de fora **de propósito**. Não são promessas: cada item diz por que não foi feito agora e o que o faria valer a pena.

## LLM e diagnóstico

1. **O `llm-ping` consultar `GET /models/{id}/endpoints` quando o 404 vier genérico.**
   Em 2026-10-20 o 404 `Provider returned error` do primeiro alvo era o provedor de origem fora do ar (uptime de 0% em 30 min), e o ping só dizia "modelo inexistente ou parâmetro recusado". A consulta é um GET público de metadados, não é completion e não conta na cota. O ping poderia imprimir o estado e o uptime dos provedores do modelo e separar as duas hipóteses sem gastar requisição.
   (O texto do 404 já foi corrigido: lista as duas hipóteses e nomeia o provedor quando o detalhe o trouxer, commit `e5d8f2e`.)
   *Por que ficou de fora:* o pedido foi manter o ping simples (exatamente uma requisição, nenhuma consulta extra). Agora o detalhe do erro já traz `provider_name` e o retorno bruto, o que cobre boa parte do caso. *Vale fazer se:* o 404 genérico voltar a custar tempo de diagnóstico. Antes, conferir na documentação o significado dos códigos de `status` dos endpoints (o `-5` visto não foi conferido).

2. **Separar `json_schema` de `provider.require_parameters` no adaptador.**
   Hoje o adaptador os envia juntos (e `require_parameters` também quando há `reasoning`). Por isso o passo "acrescenta só o `json_schema`" do diagnóstico de 2026-10-20 não seria possível por configuração: o mais próximo era `json_schema + require_parameters`. Um `LLM_REQUIRE_PARAMETERS=on|off` permitiria descascar um parâmetro de cada vez.
   *Por que ficou de fora:* não foi necessário, o diagnóstico fechou no primeiro passo.

## Guardrail

3. **Lista de permissão para o texto do LLM nas intenções neutras (ack curto + a pergunta do produto).**
   O guardrail de palavras (README D10) deixa passar ~1 em 5 paráfrases hostis inéditas. Uma lista de permissão fecharia de vez: o modelo só escreve um *ack* de até ~8 palavras de um conjunto fechado ("Anotado!", "Entendi.", "Perfeito, obrigada!") e a pergunta é sempre a do produto. Um protótipo sobre as 39 respostas neutras gravadas do modelo real manteve 14 das 30 que o guardrail aprova hoje: metade do que o LLM escreve passaria a vir de template.
   *Por que ficou de fora:* muda a decisão D3 ("o LLM redige a conversa") e o custo em naturalidade só se mede com o log real. *Decisão do autor, depois do log da conversa real* (o guardrail de palavras está fechado: sem mais famílias de vocabulário), com dois números que o `make export-logs` traz: a fração dos textos que chegaram ao lead vindos do LLM contra template, e quantos o guardrail barrou (o export traz o texto barrado, mascarado, para julgar cada um à mão). *Vale fazer se:* o log mostrar uma paráfrase de promessa que o guardrail deixou passar, ou se o autor preferir garantia estrutural a naturalidade.
   *Só se reavalia depois de a defesa contra injeção rodar com o modelo real* (cenário 7 do DEMO com o modelo de verdade, sem o 400 do provedor no caminho): enquanto não houver essa rodada, não há número de naturalidade nem de paráfrase hostil medido com o modelo que vai para o ar, e decidir a lista antes disso seria decidir no escuro. Os números da lista (39 respostas, 14 de 30 mantidas) vêm da primeira rodada e ficam como estimativa.

## Desempenho

4. **Limitador de taxa configurável por modelo.**
   Hoje o limitador é fixo em 20 requisições por minuto (`FREE_RPM`, espaçamento mínimo de 3,15 s), o teto dos modelos `:free` do OpenRouter, e vale para qualquer modelo. Com um modelo pago ou um provedor de limite maior, esse espaçamento vira latência artificial. A espera já é medida por turno (`limiter_wait_s` no meta e no export), então a latência do sistema se separa do espaçamento; o que falta é poder configurar o rpm (e a janela) por modelo, na `LLMConfig`, em vez de uma constante.
   *Por que ficou de fora:* o modelo em uso é `:free`, o limite de 20 por minuto é o real, e a latência reportada já desconta a espera. *Vale fazer se:* o projeto passar a usar um modelo com limite maior.
