"""Fast-path ESTRITO por regex: CANDIDATO, DESLIGADO por padrao. Nada no produto o chama.

Existe para ser MEDIDO pelo smoke-llm (divergencia regex vs LLM nas mesmas mensagens). Se divergir, sai; se nao divergir, so entra se o
ganho medido justificar (docs/PLAN.md, secoes 3 e 5.1). O risco que ele carrega e extrair o slot errado em silencio e chegar a um preco errado,
por isso so vale quando o turno e RESPOSTA DIRETA ao slot que foi perguntado e o valor e INEQUIVOCO: a mensagem inteira tem que casar. Qualquer
texto a mais, qualquer duvida, qualquer formato fora disto devolve None e a mensagem vai para o LLM.
"""
from __future__ import annotations

import re
from datetime import date

_ANO = re.compile(r"(?:(?:o\s+)?ano\s*(?:é|e|:)?\s*)?((?:19|20)[0-9]{2})", re.IGNORECASE)
_IDADE = re.compile(r"(?:tenho\s+)?([0-9]{2,3})(?:\s*anos)?", re.IGNORECASE)
_CEP = re.compile(r"(?:(?:o\s+|meu\s+)?cep\s*(?:é|e|:)?\s*)?([0-9]{5})[-.\s]?([0-9]{3})", re.IGNORECASE)


def fast_extract(asked_slot: str | None, text: str, *, today: date) -> str | None:
    """Valor normalizado do slot perguntado, ou None. Idade e ano: so numero plausivel; CEP: 8 digitos."""
    if asked_slot is None:
        return None
    t = text.strip()
    if asked_slot == "veiculo_ano" and (m := _ANO.fullmatch(t)) and 1950 <= int(m.group(1)) <= today.year:
        return m.group(1)
    if asked_slot == "idade" and (m := _IDADE.fullmatch(t)) and 18 <= int(m.group(1)) <= 110:
        return m.group(1)
    if asked_slot == "cep" and (m := _CEP.fullmatch(t)):
        return m.group(1) + m.group(2)
    return None
