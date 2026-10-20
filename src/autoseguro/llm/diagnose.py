"""Causa PROVAVEL de uma falha de LLM, em portugues, para o smoke e o ping.

E uma dica, nao um diagnostico: o texto diz "provavel" e aponta a variavel de ambiente a conferir. Nao recebe nem imprime a chave: so o codigo
HTTP, o erro do adaptador, a configuracao (nomes e valores nao secretos) e o detalhe do erro, que o adaptador ja entrega mascarado. Do detalhe
sai so o nome do provedor de origem (`provedor=<nome>`, o `provider_name` do `error.metadata` do OpenRouter), passado de novo por `redact`.

Um 404 tem DUAS causas que a mensagem precisa listar, porque uma mensagem que aponta so uma induz ao palpite errado (ja induziu): o modelo (ou o
provedor dele) fora do ar, e nenhum provedor aceitar todos os parametros do pedido.
"""
from __future__ import annotations

import re

from .config import LLMConfig
from .redact import redact

_PROVIDER = re.compile(r"(?:^|\| )provedor=([^|]+?)\s*(?:\||$)")


def _parametros(cfg: LLMConfig) -> list[str]:
    """Os parametros do pedido que um provedor pode nao aceitar. Vazio = pedido simples."""
    parts = []
    if cfg.structured_output == "json_schema":
        parts.append("json_schema" + (" + require_parameters" if cfg.provider == "openrouter" else ""))
    if cfg.reasoning_effort and cfg.provider == "openrouter":
        parts.append(f"reasoning={cfg.reasoning_effort}")
    return parts


def _pedido(cfg: LLMConfig) -> str:
    return ", ".join(_parametros(cfg)) or "sem saida estruturada"


def provider_name_from(detail: str | None) -> str | None:
    """O nome do provedor de origem, se o detalhe do erro o trouxer (`... | provedor=Nvidia | retorno=...`). Mascarado de novo, por precaucao."""
    m = _PROVIDER.search(detail or "")
    name = redact(m.group(1).strip()) if m else ""
    return name or None


def describe_request(cfg: LLMConfig) -> str:
    """O que o pedido tem de especial (o que o provedor pode recusar), para mostrar ao usuario."""
    return _pedido(cfg)


def explain_failure(cfg: LLMConfig, error: str | None, status: int | None, detail: str | None = None) -> str:
    """Uma ou duas frases: o que provavelmente aconteceu e o que conferir. `detail` e o detalhe do erro do adaptador (so serve para nomear o provedor)."""
    if status == 401:
        return "A chave foi recusada (invalida, revogada ou de outra conta). Confira LLM_API_KEY (ou OPENROUTER_API_KEY) no .env."
    if status == 402:
        return "Sem creditos para este modelo, ou o modelo nao e gratuito. Use um LLM_MODEL terminado em ':free' ou compre creditos."
    if status == 403:
        return "O provedor recusou o conteudo (moderacao) ou a chave nao tem permissao para este modelo."
    if status == 404:
        name = provider_name_from(detail)
        provedor = f"o provedor {name} (o que devolveu o erro)" if name else "o provedor dele"
        fora = f"o modelo ou {provedor} esta fora do ar, ou o modelo nao existe"
        if _parametros(cfg):
            return (f"Duas hipoteses: (1) {fora}; (2) nenhum provedor aceita TODOS os parametros do pedido ({_pedido(cfg)}). "
                    "Para separar, repita com um pedido simples (LLM_STRUCTURED_OUTPUT=none e LLM_REASONING_EFFORT=off): se o 404 continuar, e a (1), "
                    "troque o LLM_MODEL; se passar, e a (2), tire o parametro suspeito.")
        return (f"O pedido ja e simples, entao os parametros nao sao a causa: {fora}. "
                "Confira LLM_MODEL e LLM_BASE_URL, ou troque de modelo.")
    if status in (400, 422):
        return (f"O pedido foi rejeitado por formato ou parametro ({_pedido(cfg)}). Suspeitos, nesta ordem: LLM_STRUCTURED_OUTPUT=none, "
                "LLM_REASONING_EFFORT=off, LLM_MAX_TOKENS.")
    if status is not None and 400 <= status < 500 and status not in (408, 429):
        return "O provedor recusou o pedido. Veja o detalhe dele acima."
    if status == 429:
        return "Limite de uso. O limite por minuto passa em instantes; o diario so renova a 00:00 UTC."
    if status == 408 or (status is not None and status >= 500):
        return "Falha do servico do provedor, nao do pedido. Tente de novo daqui a pouco."
    if error == "timeout":
        return "Sem resposta no prazo. O modelo pode estar lento ou fora do ar; veja a latencia e tente de novo."
    if error == "connection":
        return "Nao conectou. Confira a rede, um proxy e LLM_BASE_URL."
    if error == "max_tokens":
        return "O modelo gastou todos os max_tokens, provavelmente raciocinando. Use LLM_REASONING_EFFORT=none (ou low) ou suba LLM_MAX_TOKENS."
    if error and error.startswith("invalid_output"):
        base = "O modelo respondeu, mas fora do schema local."
        if cfg.structured_output == "json_schema":
            return base + " Com json_schema ligado isso indica que o modelo ou o provedor nao impos o schema."
        return base + " Sem saida estruturada o modelo precisa seguir o formato so pelo prompt."
    if error in ("no_text", "no_choices"):
        return "O provedor respondeu sem texto. Pode ser o raciocinio consumindo a resposta (LLM_REASONING_EFFORT=none) ou um modelo instavel."
    if error == "content_filter":
        return "O provedor filtrou a resposta (moderacao)."
    if error and error.startswith("provider_error"):
        return "O provedor devolveu um erro dentro de uma resposta 200. Veja o detalhe dele acima."
    return "Falha nao classificada. Veja o erro acima."
