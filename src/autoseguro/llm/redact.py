"""Redacao de segredos. Nenhuma chave pode aparecer em log, erro, relatorio nem saida.

Duas defesas: (1) o valor EXATO dos segredos que o processo conhece e (2) os formatos conhecidos de chave e de cabecalho
Authorization, para o caso de um provedor ecoar um segredo que o processo nao conhecia.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

REDACTED = "[REDACTED]"
_KNOWN_FORMATS = (
    re.compile(r"sk-or-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.=]{8,}"),
    re.compile(r"(?i)(x-api-key['\"]?\s*[:=]\s*['\"]?)[A-Za-z0-9_\-\.=]{8,}"),
)


def redact(text: str | None, secrets: Iterable[str | None] = (), *, limit: int | None = None) -> str:
    """Troca por [REDACTED] cada segredo conhecido e todo formato de chave/Authorization. `limit` trunca o resultado."""
    out = text or ""
    for s in secrets:
        if s and len(s) >= 6:
            out = out.replace(s, REDACTED)
    for rx in _KNOWN_FORMATS:
        out = rx.sub(lambda m: (m.group(1) if m.groups() else "") + REDACTED, out)
    return out if limit is None or len(out) <= limit else out[:limit] + "…"
