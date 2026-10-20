# Origem de terceiros

**Tudo em `vendor/` veio do desafio e não é autoral.** O restante do repositório é do autor.

`vendor/quote-service/` é uma cópia **não modificada** do serviço de cotação fornecido no desafio:

- Repositório: <https://github.com/namastexlabs/namastex-fde-challenge>
- Commit de origem: `52a006c`
- Integridade: `vendor/quote-service.sha256`, conferido por `tests/test_repo_hygiene.py`. O teste reprova se
  qualquer arquivo for alterado, removido ou acrescentado dentro de `vendor/quote-service/`. Se o serviço precisar
  mudar, a mudança tem que ser deliberada: atualizar o checksum e justificar no `docs/PLAN.md`.

O serviço e a tabela de planos pertencem aos autores do desafio. A cópia existe só para que `make api-up` funcione a
partir deste repositório, sem depender de um segundo clone.

Derivados (autorais, mas baseados no material do desafio):

- `docker-compose.yml` é baseado no do desafio, com tag de imagem e healthcheck acrescentados.
- `docker-compose.test.yml` é nosso.

O dataset de conversas (`conversations.parquet`) **não** é copiado para cá: o caminho vem de `DATASET_PATH`
(padrão: o clone do desafio ao lado deste repo).
