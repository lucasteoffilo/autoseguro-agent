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

## Export

5. **Seção do export com os textos do modelo trocados por desenho.**
   Hoje a tabela de barrados lista só o que o modelo poderia ter conduzido; os textos que o guardrail marcou em turnos que o produto troca por desenho (pergunta de necessidade, confirmação, eco) só existem no banco (`meta.blocked_reply`). Na 2ª rodada do DEMO foram 7 textos, e para julgá-los foi preciso consultar o banco. Uma seção "Texto do modelo trocado por desenho, marcado pelo guardrail" no export os traria.
   Vale também para o texto que o modelo escreveu na abertura e a regra da única pergunta trocou (`template_question`): ele não é gravado, e na 3ª rodada as 3 aberturas foram trocadas sem que se possa ler o que o modelo havia escrito.
   *Por que ficou de fora:* o número já respondeu o que ele existia para responder: o texto do modelo que chega ao lead é só a abertura. *Vale fazer se:* o texto do modelo voltar a conduzir turnos além da abertura, ou se alguém precisar auditar o que o modelo escreve nas aberturas.

6. **Gravar `blocked_reply` também no caminho de risco.**
   Nas intenções de risco o texto do modelo é sempre substituído por template, e quando o guardrail o marca (por exemplo `R1_dinheiro` na oferta de plano mais barato do cenário 4) o texto barrado não é gravado, só a regra. Não dá para julgar se foi falso positivo.
   *Por que ficou de fora:* nesses turnos o texto do modelo nunca chega ao lead, então o falso positivo não tem custo. *Vale fazer se:* o guardrail passar a decidir algo nesses turnos.

## Conversa

7. **Variantes de template.**
   O repertório do lead é fixo: o "Anotado:" abre quase todo turno com dado novo, a pergunta de necessidade é sempre a mesma frase com três opções, a recusa de escopo repete a mesma frase duas vezes seguidas e a resposta a desconto é seca (D11). Duas ou três variantes por template, escolhidas de forma determinística (pelo `trace_id` e pelo turno, para o teste continuar reproduzível), quebrariam a repetição sem dar a caneta ao modelo; cada variante passa no `check_reply` por construção, como as de hoje.
   *Por que ficou de fora:* é melhoria de naturalidade, não de segurança nem de correção, e cada variante multiplica os textos que os testes e o guardrail precisam cobrir. *Vale fazer se:* um avaliador ou um lead real apontar a repetição como problema.

8. **Reescrever o 7b e o desfecho esperado.**
   Na 3ª rodada o modelo real rotulou dois dos quatro pedidos do 7b como `out_of_scope` e a 2ª recusa seguida virou handoff, de modo que o (d) nunca chegou ao modelo. A regra de preço antes de dados (D8) tirou (b) e (c) desse caminho e a execução final o exerce de novo, mas o DEMO ainda descreve o 7b como "volta à pergunta do produto" para as quatro. Se a execução final mostrar outro desfecho seguro (por exemplo, handoff `OUT_OF_SCOPE` por recusas de escopo seguidas), o texto do DEMO deve acompanhá-lo, e o (d) pode virar um 7c separado.
   *Por que ficou de fora:* não bloqueia o envio; a defesa já foi medida (nada vazou nas duas rodadas).

9. **A abertura do modelo deve ter a pergunta do produto como a única pergunta.**
   A regra "uma única pergunta, a do produto" confere que o texto tem um `?` e que cita o ano do modelo em algum lugar, não que o `?` seja da pergunta do produto. Na execução final, a abertura do cenário 6 passou: "Tudo bem? Para te dar uma cotação, preciso do ano do modelo do seu carro." (o único `?` é o do "Tudo bem?", e o pedido do ano é uma afirmação). Conferir o tópico só dentro da frase que termina em `?` fecha isso. Outro defeito pequeno da mesma execução: "Olá! Sou a assistente virtual da AutoSeguro. Bem-vindo à AutoSeguro." (a abertura do cenário 1) repete a casa.
   *Por que ficou de fora:* é naturalidade, não segurança (nada de preço, desconto ou promessa passa por aí), e a execução final já estava rodada. *Vale fazer se:* a repetição incomodar na leitura do log.
