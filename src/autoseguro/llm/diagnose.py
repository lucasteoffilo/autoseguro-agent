"""Causa PROVAVEL de uma falha de LLM, em portugues, para o smoke e o ping.

E uma dica, nao um diagnostico: o texto diz "provavel" e aponta a variavel de ambiente a conferir. Nao recebe nem imprime a chave: so o codigo
HTTP, o erro do adaptador e a configuracao (nomes e valores nao secretos).
"""
from __future__ import annotations

from .config import LLMConfig


def _pedido(cfg: LLMConfig) -> str:
    parts = []
    if cfg.structured_output == "json_schema":
        parts.append("json_schema" + (" + require_parameters" if cfg.provider == "openrouter" else ""))
    if cfg.reasoning_effort and cfg.provider == "openrouter":
        parts.append(f"reasoning={cfg.reasoning_effort}")
    return ", ".join(parts) or "sem saida estruturada"


def describe_request(cfg: LLMConfig) -> str:
    """O que o pedido tem de especial (o que o provedor pode recusar), para mostrar ao usuario."""
    return _pedido(cfg)


def explain_failure(cfg: LLMConfig, error: str | None, status: int | None) -> str:
    """Uma ou duas frases: o que provavelmente aconteceu e o que conferir."""
    if status == 401:
        return "A chave foi recusada (invalida, revogada ou de outra conta). Confira LLM_API_KEY (ou OPENROUTER_API_KEY) no .env."
    if status == 402:
        return "Sem creditos para este modelo, ou o modelo nao e gratuito. Use um LLM_MODEL terminado em ':free' ou compre creditos."
    if status == 403:
        return "O provedor recusou o conteudo (moderacao) ou a chave nao tem permissao para este modelo."
    if status == 404:
        if cfg.structured_output == "json_schema":
            return (f"Modelo inexistente, ou nenhum provedor aceita TODOS os parametros do pedido ({_pedido(cfg)}). "
                    "Tente LLM_STRUCTURED_OUTPUT=none, ou outro LLM_MODEL.")
        return "Modelo ou endpoint inexistente. Confira LLM_MODEL e LLM_BASE_URL."
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
