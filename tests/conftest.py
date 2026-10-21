"""Fixtures compartilhadas. Nada aqui depende da API de cotacao nem de chave de LLM."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VAR = ROOT / "var"

# Nenhum caminho do repo pode conter PII, nem de proposito: as amostras sinteticas dos testes sao montadas em tempo de execucao (tests/synthetic_pii.py).
# Nao sao texto nosso: lockfile do servico vendorizado.
SCAN_SKIP = ("vendor/quote-service/uv.lock",)
_FALLBACK_SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "var", "node_modules"}
_FALLBACK_SKIP_SUFFIXES = (".egg-info",)


def _repo_files() -> list[Path]:
    """Arquivos versionados + novos nao ignorados (funciona antes do primeiro commit)."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                             cwd=ROOT, capture_output=True, check=True).stdout.decode()
        paths = [ROOT / p for p in out.split("\0") if p]
    except (subprocess.CalledProcessError, FileNotFoundError):
        # sem git (um zip, um `git archive` extraido): tudo, menos o que a instalacao e a execucao geram
        paths = [p for p in ROOT.rglob("*") if not _FALLBACK_SKIP_DIRS & set(p.relative_to(ROOT).parts)
                 and not any(part.endswith(_FALLBACK_SKIP_SUFFIXES) for part in p.relative_to(ROOT).parts)]
    return [p for p in paths if p.is_file()]


# --- a suite nao escreve no var/ real ---------------------------------------------------------------------------------------------------------------
# var/ guarda o que e de quem roda o projeto: o contador de cota do provedor (var/smoke/quota.jsonl), os bancos e os logs. A cota de cada teste vai para um tmp (fixture abaixo);
# o que escapar disso reprova a execucao inteira no fim, com a lista do que mudou em var/.
def pytest_configure(config):
    from tests.var_guard import VarGuard
    config.pluginmanager.register(VarGuard(VAR), "var-guard")


@pytest.fixture(autouse=True)
def _isolate_quota_log(monkeypatch, tmp_path_factory):
    """Todo teste que monta o orquestrador (ou o LLM) pelo cli usa uma cota em tmp, nunca a de var/smoke/quota.jsonl."""
    from autoseguro import cli
    monkeypatch.setattr(cli, "QUOTA_LOG", tmp_path_factory.mktemp("quota") / "quota.jsonl")


@pytest.fixture(autouse=True)
def _isolate_llm_credentials(monkeypatch):
    """Nenhum teste enxerga credencial real: limpa as variaveis de LLM do ambiente e impede que o smoke leia o .env de quem roda os testes."""
    for name in list(os.environ):
        if name.startswith("LLM_") or name in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(name, raising=False)
    import tools.smoke_llm as smoke
    monkeypatch.setattr(smoke, "load_env", lambda path: None)


@pytest.fixture(scope="session")
def repo_text_files() -> list[tuple[str, str]]:
    """(caminho relativo, texto) de todo arquivo de texto do repo, exceto lockfiles. Sem allowlist de PII."""
    files = []
    for p in _repo_files():
        rel = p.relative_to(ROOT).as_posix()
        if rel in SCAN_SKIP:
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
    pd = pytest.importorskip("pandas", reason="extra opcional ausente (pip install -e '.[analysis]')")
    df = pd.read_parquet(path, columns=["message_body"])
    return sorted({b.strip().lower() for b in df.message_body if len(b.strip()) >= 12})
