"""Fixtures compartilhadas. Nada aqui depende da API de cotacao nem de chave de LLM."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Arquivos que podem conter PII *de proposito* (amostras sinteticas para testar o mascarador).
# Qualquer outro caminho com PII reprova a higiene do repo.
PII_ALLOWLIST_PREFIXES = ("tests/fixtures/pii_samples/",)
# Nao sao texto nosso: lockfile do servico vendorizado.
SCAN_SKIP = ("vendor/quote-service/uv.lock",)
_FALLBACK_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "var", "node_modules"}


def _repo_files() -> list[Path]:
    """Arquivos versionados + novos nao ignorados (funciona antes do primeiro commit)."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             cwd=ROOT, capture_output=True, check=True).stdout.decode()
        paths = [ROOT / p for p in out.split("\0") if p]
    except (subprocess.CalledProcessError, FileNotFoundError):
        paths = [p for p in ROOT.rglob("*") if not _FALLBACK_SKIP_DIRS & set(p.relative_to(ROOT).parts)]
    return [p for p in paths if p.is_file()]


@pytest.fixture(scope="session")
def repo_text_files() -> list[tuple[str, str]]:
    """(caminho relativo, texto) de todo arquivo de texto do repo, exceto allowlist e lockfiles."""
    files = []
    for p in _repo_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(PII_ALLOWLIST_PREFIXES) or rel in SCAN_SKIP:
            continue
        try:
            files.append((rel, p.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue  # binario
    return files


@pytest.fixture(scope="session")
def dataset_bodies() -> list[str]:
    """Textos de mensagem do dataset (minusculos, >= 12 chars). Pula se o parquet nao estiver disponivel."""
    path = os.getenv("DATASET_PATH")
    if not path or not Path(path).exists():
        pytest.skip("DATASET_PATH ausente: checagem contra linhas cruas do dataset pulada")
    pd = pytest.importorskip("pandas")
    df = pd.read_parquet(path, columns=["message_body"])
    return sorted({b.strip().lower() for b in df.message_body if len(b.strip()) >= 12})
