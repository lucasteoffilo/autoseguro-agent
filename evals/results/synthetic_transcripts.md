# Transcrições dos cenários sintéticos

#### `cotacao-essencial` — quoted

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 137,88
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.

#### `cotacao-completo` — quoted

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › quero cobrir terceiros e vidros também
- **agente** [question] › Anotado: cobertura do plano Completo. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Completo:
  • Mensalidade: R$ 241,38
  • Franquia: R$ 3.000,00
  • Cobre: colisão, roubo, furto, danos a terceiros e vidros
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Completo.
  Se algum dado estiver errado, me avisa que eu refaço.

#### `cotacao-premium` — quoted

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › quero carro reserva e assistência 24h, a completa
- **agente** [question] › Anotado: cobertura do plano Premium. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Premium:
  • Mensalidade: R$ 390,88
  • Franquia: R$ 1.500,00
  • Cobre: colisão, roubo, furto, danos a terceiros, vidros, carro reserva e assistência 24h
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Premium.
  Se algum dado estiver errado, me avisa que eu refaço.

#### `cotacao-pro-rata` — quoted

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 15/11/2026
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 137,88
  • Primeiro pagamento: R$ 73,54 (proporcional: 16 de 30 dias do mês)
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 15/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.

#### `cotacao-quatro-dados-numa-mensagem` — quoted

- **lead** › oi, quero cotar: onix 2023, 29 anos, cep 01310-100, começando dia 01/11/2026
- **agente** [question] › Olá! Sou a assistente virtual da AutoSeguro. Anotado: modelo 2023, 29 anos, CEP 01310-100 e início em 01/11/2026 (domingo). O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 149,88
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2023, 29 anos, CEP 01310-100, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.

#### `cotacao-com-correcao-que-recusa` — refused

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 137,88
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.
- **lead** › errei, tenho 80 anos
- **agente** [refusal] › Não consigo cotar este perfil: a seguradora só aceita motoristas de até 75 anos.
  Dados usados: modelo 2019 e 80 anos.
  Por isso vou encerrar por aqui. Obrigado pelo interesse!

#### `cotacao-duvida-de-cobertura-no-meio` — quoted

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › e a carência, como funciona?
- **agente** [text] › Roubo e furto só passam a valer 30 dias depois do início da vigência (carência). Qual é o ano do modelo do seu carro? Se o documento mostra dois anos, como 2015/2016, vale o segundo.
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 137,88
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.

#### `cotacao-midia-no-meio` — quoted

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › [audio] mensagem de voz (9s)
- **agente** [question] › Por aqui eu só leio mensagens de texto, então não consegui abrir o seu áudio. Qual é o ano do modelo do seu carro? Se o documento mostra dois anos, como 2015/2016, vale o segundo.
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 137,88
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.

#### `recusa-carro-velho` — refused

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um fusca 1998, tenho 45 anos e moro no cep 01310-100
- **agente** [refusal] › Não consigo cotar este perfil: a seguradora não aceita veículos com mais de 20 anos.
  Dados usados: modelo 1998 e 45 anos.
  Por isso vou encerrar por aqui. Obrigado pelo interesse!

#### `recusa-idade-acima` — refused

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 80 anos e moro no cep 01310-100
- **agente** [refusal] › Não consigo cotar este perfil: a seguradora só aceita motoristas de até 75 anos.
  Dados usados: modelo 2019 e 80 anos.
  Por isso vou encerrar por aqui. Obrigado pelo interesse!

#### `recusa-menor-de-idade` — refused

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 17 anos e moro no cep 01310-100
- **agente** [refusal] › Não consigo cotar este perfil: a idade informada está fora da faixa que a seguradora aceita (de 18 a 75 anos).
  Dados usados: modelo 2019 e 17 anos.
  Por isso vou encerrar por aqui. Obrigado pelo interesse!

#### `borda-aceita-75-anos-e-carro-de-20` — quoted

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um gol 2006, tenho 75 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2006, 75 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 243,40
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2006, 75 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.

#### `borda-recusada-76-anos` — refused

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 76 anos e moro no cep 30130-010
- **agente** [refusal] › Não consigo cotar este perfil: a seguradora só aceita motoristas de até 75 anos.
  Dados usados: modelo 2019 e 76 anos.
  Por isso vou encerrar por aqui. Obrigado pelo interesse!

#### `borda-recusada-carro-de-21` — refused

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um gol 2005, tenho 40 anos e moro no cep 30130-010
- **agente** [refusal] › Não consigo cotar este perfil: a seguradora não aceita veículos com mais de 20 anos.
  Dados usados: modelo 2005 e 40 anos.
  Por isso vou encerrar por aqui. Obrigado pelo interesse!

#### `borda-aceita-18-anos` — quoted

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 18 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 18 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 220,62
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 18 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.

#### `handoff-quote-unavailable` — handoff:QUOTE_UNAVAILABLE (attempts_exhausted:connection)

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › pode começar dia 01/11/2026
- **agente** [hold] › Um instante, estou calculando a sua cotação.
- **agente** [handoff] › Não consegui gerar a sua cotação agora: o sistema que calcula os valores está instável. Como só passo valores que esse sistema confirma, prefiro não estimar nenhum preço. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-quote-unavailable-na-pre-checagem` — handoff:QUOTE_UNAVAILABLE (precheck:attempts_exhausted:connection)

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um fusca 1998, tenho 45 anos e moro no cep 01310-100
- **agente** [hold] › Um instante, estou calculando a sua cotação.
- **agente** [handoff] › Não consegui gerar a sua cotação agora: o sistema que calcula os valores está instável. Como só passo valores que esse sistema confirma, prefiro não estimar nenhum preço. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-human-requested` — handoff:HUMAN_REQUESTED

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › prefiro falar com uma pessoa
- **agente** [handoff] › Claro. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-human-requested-no-meio` — handoff:HUMAN_REQUESTED

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › quero falar com um atendente
- **agente** [handoff] › Claro. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-complaint` — handoff:COMPLAINT

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › isso é um absurdo, quero fazer uma reclamação
- **agente** [handoff] › Sinto muito pela experiência. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-claim-sinistro` — handoff:CLAIM_SINISTRO

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › bati o carro ontem e preciso acionar o seguro
- **agente** [handoff] › Sinto muito pelo que aconteceu. Acionar o seguro (sinistro) não é comigo: eu só faço cotação. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-cancellation` — handoff:CANCELLATION

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › quero cancelar o meu seguro
- **agente** [handoff] › Entendi que você quer cancelar. Cancelamento não é comigo: eu só faço cotação. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-data-ambiguous-ano-futuro` — handoff:DATA_AMBIGUOUS (entrada_invalida:veiculo_ano:ano_modelo_futuro)

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um carro 2027, tenho 34 anos e moro no cep 30130-010
- **agente** [handoff] › Não consegui confirmar os seus dados para montar a cotação. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-data-ambiguous-confirmacao-sem-resposta` — handoff:DATA_AMBIGUOUS (confirmacao_sem_resposta:veiculo_ano)

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › o carro é 2018 mas o modelo é 2019
- **agente** [confirmation] › Só pra confirmar: modelo 2019?
- **lead** › sei lá
- **agente** [confirmation] › Só pra confirmar: modelo 2019?
- **lead** › não sei
- **agente** [handoff] › Não consegui confirmar os seus dados para montar a cotação. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-media-unreadable` — handoff:MEDIA_UNREADABLE (midia_repetida:document)

- **lead** › [audio] mensagem de voz (9s)
- **agente** [question] › Olá! Sou a assistente virtual da AutoSeguro. Por aqui eu só leio mensagens de texto, então não consegui abrir o seu áudio. Qual é o ano do modelo do seu carro? Se o documento mostra dois anos, como 2015/2016, vale o segundo.
- **lead** › [documento] documento_do_carro.pdf
- **agente** [handoff] › Continuo sem conseguir abrir o que você enviou: por aqui eu só leio mensagens de texto. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-ready-to-close` — handoff:READY_TO_CLOSE

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 137,88
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.
- **lead** › gostei, quero fechar
- **agente** [handoff] › Que bom que você quer seguir! A emissão da apólice e a contratação não são comigo: eu só faço cotação. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-conversation-stalled` — handoff:CONVERSATION_STALLED (pergunta_repetida:veiculo_ano)

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › hmm
- **agente** [text] › Não entendi bem. Qual é o ano do modelo do seu carro?
- **lead** › não sei
- **agente** [text] › Não entendi bem. Qual é o ano do modelo do seu carro?
- **lead** › sei lá
- **agente** [handoff] › Parece que não estou conseguindo avançar com as suas respostas por aqui. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-price-objection-oferta-recusada` — handoff:PRICE_OBJECTION

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › quero cobrir terceiros e vidros também
- **agente** [question] › Anotado: cobertura do plano Completo. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Completo:
  • Mensalidade: R$ 241,38
  • Franquia: R$ 3.000,00
  • Cobre: colisão, roubo, furto, danos a terceiros e vidros
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Completo.
  Se algum dado estiver errado, me avisa que eu refaço.
- **lead** › achei caro
- **agente** [text] › Entendo que o valor pesou. Posso te mostrar outro plano para você comparar?
- **lead** › não, obrigado
- **agente** [handoff] › Entendo. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-price-objection-oferta-sem-resposta` — handoff:PRICE_OBJECTION (oferta_sem_resposta)

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › quero cobrir terceiros e vidros também
- **agente** [question] › Anotado: cobertura do plano Completo. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Completo:
  • Mensalidade: R$ 241,38
  • Franquia: R$ 3.000,00
  • Cobre: colisão, roubo, furto, danos a terceiros e vidros
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Completo.
  Se algum dado estiver errado, me avisa que eu refaço.
- **lead** › achei caro
- **agente** [text] › Entendo que o valor pesou. Posso te mostrar outro plano para você comparar?
- **lead** › talvez
- **agente** [question] › Não entendi. Você quer ver outro plano para comparar? Responda só sim ou não.
- **lead** › sei lá
- **agente** [handoff] › Entendo. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-price-objection-sem-plano-mais-barato` — handoff:PRICE_OBJECTION

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › só roubo e colisão
- **agente** [question] › Anotado: cobertura do plano Essencial. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Essencial:
  • Mensalidade: R$ 137,88
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.
- **lead** › tá muito caro
- **agente** [handoff] › Entendo. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-out-of-scope` — handoff:OUT_OF_SCOPE

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › quero um seguro de vida
- **agente** [text] › Isso foge do que eu consigo ajudar: eu só faço cotação de seguro de carro. Qual é o ano do modelo do seu carro? Se o documento mostra dois anos, como 2015/2016, vale o segundo.
- **lead** › e um seguro de viagem?
- **agente** [handoff] › Isso foge do que eu consigo ajudar: eu só faço cotação de seguro de carro. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-safety-guard-llm-fora` — handoff:SAFETY_GUARD (http_503 | falha simulada)

- **lead** › oi
- **agente** [handoff] › Olá! Sou a assistente virtual da AutoSeguro. Estou com uma instabilidade e não consigo continuar a conversa agora. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `handoff-safety-guard-filtro-do-provedor` — handoff:SAFETY_GUARD (content_filter)

- **lead** › oi
- **agente** [fallback] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro? Se o documento mostra dois anos, como 2015/2016, vale o segundo.
- **lead** › oi de novo
- **agente** [handoff] › Não consegui processar a sua mensagem com segurança. Um consultor vai dar continuidade à sua conversa, e o que você me contou ficou registrado.

#### `sem-handoff-desconto-antes-da-cotacao` — open

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › me dá um desconto de 50%?
- **agente** [text] › Isso não é comigo: eu só mostro o valor que sai da cotação, e não consigo prometer nada além dele. Qual é o ano do modelo do seu carro? Se o documento mostra dois anos, como 2015/2016, vale o segundo.

#### `sem-handoff-objecao-com-alternativa-aceita` — quoted

- **lead** › oi
- **agente** [text] › Olá! Sou a assistente virtual da AutoSeguro. Qual é o ano do modelo do seu carro?
- **lead** › é um onix 2019, tenho 34 anos e moro no cep 30130-010
- **agente** [question] › Anotado: modelo 2019, 34 anos e CEP 30130-010. O que você quer cobrir? Só colisão, roubo e furto; também danos a terceiros e vidros; ou também carro reserva e assistência 24h?
- **lead** › quero cobrir terceiros e vidros também
- **agente** [question] › Anotado: cobertura do plano Completo. Em que dia você quer que o seguro comece a valer?
- **lead** › começando dia 01/11/2026
- **agente** [quote] › Aqui está a cotação do plano Completo:
  • Mensalidade: R$ 241,38
  • Franquia: R$ 3.000,00
  • Cobre: colisão, roubo, furto, danos a terceiros e vidros
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Completo.
  Se algum dado estiver errado, me avisa que eu refaço.
- **lead** › achei caro
- **agente** [text] › Entendo que o valor pesou. Posso te mostrar outro plano para você comparar?
- **lead** › sim, pode mostrar
- **agente** [quote] › Aqui está a cotação do plano Essencial (outra opção para você comparar):
  • Mensalidade: R$ 137,88
  • Franquia: R$ 4.500,00
  • Cobre: colisão, roubo e furto
  • Carência: roubo e furto só passam a valer 30 dias depois do início da vigência.
  Dados usados: modelo 2019, 34 anos, CEP 30130-010, início em 01/11/2026 (domingo) e plano Essencial.
  Se algum dado estiver errado, me avisa que eu refaço.
