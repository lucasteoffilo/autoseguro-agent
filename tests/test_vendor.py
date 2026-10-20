"""O que veio do desafio (vendor/) nao pode ser editado em silencio. Ver NOTICE.md."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_vendored_quote_service_is_unmodified():
    assert not (ROOT / "quote-service").exists(), "o servico vendorizado vive em vendor/quote-service/"
    listed = {}
    for line in (ROOT / "vendor" / "quote-service.sha256").read_text(encoding="utf-8").splitlines():
        digest, path = line.split(maxsplit=1)
        listed[path.strip()] = digest
    assert listed, "vendor/quote-service.sha256 vazio"
    for path, digest in listed.items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest, f"{path} foi alterado"
    actual = {p.relative_to(ROOT).as_posix() for p in (ROOT / "vendor" / "quote-service").rglob("*")
              if p.is_file() and "__pycache__" not in p.parts}
    assert actual == set(listed), f"arquivos fora do checksum: {sorted(actual ^ set(listed))}"
