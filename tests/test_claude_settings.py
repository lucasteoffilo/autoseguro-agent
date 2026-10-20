"""A regra que impede a sessao do Claude Code de ler o .env (que guarda a chave do provedor de LLM).

ISTO NAO PROVA QUE A REGRA FUNCIONA: quem aplica `.claude/settings.json` e o Claude Code, nao este repo, e a regra so vale numa sessao aberta
DEPOIS que o arquivo existe. O que o teste garante e o que e nosso: o arquivo existe, e JSON valido, nega Read/Edit/Bash do .env e das variantes,
e NAO nega o `.env.example` (que e versionado e precisa continuar legivel). Para verificar de verdade, ver o README (secao Dados sensiveis).
"""
from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

import pytest

SETTINGS = Path(__file__).resolve().parent.parent / ".claude" / "settings.json"


@pytest.fixture(scope="module")
def deny() -> list[str]:
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    rules = data["permissions"]["deny"]
    assert all(isinstance(r, str) for r in rules)
    return rules


def rules_for(deny: list[str], tool: str) -> list[str]:
    return [m.group(1) for r in deny if (m := re.fullmatch(rf"{tool}\((.*)\)", r))]


def denied_path(deny: list[str], tool: str, path: str) -> bool:
    """Aproximacao do casamento de caminho (gitignore-style) com fnmatch: `**/x` casa `x` em qualquer pasta, inclusive a raiz."""
    for pat in rules_for(deny, tool):
        pat = pat.removeprefix("./")
        candidates = {pat, pat.removeprefix("**/")} if pat.startswith("**/") else {pat}
        if any(fnmatch.fnmatch(path, c) or fnmatch.fnmatch(path.removeprefix("./"), c) or fnmatch.fnmatch(Path(path).name, c) for c in candidates):
            return True
    return False


def denied_command(deny: list[str], command: str) -> bool:
    return any(fnmatch.fnmatchcase(command, pat) for pat in rules_for(deny, "Bash"))


def test_the_settings_file_exists_and_is_valid_json():
    assert SETTINGS.exists(), ".claude/settings.json sumiu: a sessao voltaria a poder ler o .env"
    assert isinstance(json.loads(SETTINGS.read_text(encoding="utf-8")), dict)


@pytest.mark.parametrize("path", [".env", "./.env", "autoseguro-agent/.env", "/abs/path/.env", ".env.local", "sub/.env.production", ".env.development"])
def test_reading_the_env_file_or_its_variants_is_denied(deny, path):
    assert denied_path(deny, "Read", path), path


@pytest.mark.parametrize("path", [".env.example", "./.env.example", "docs/.env.example", "README.md", "src/autoseguro/llm/config.py", "tests/fake_servers.py"])
def test_reading_other_files_including_the_example_stays_allowed(deny, path):
    assert not denied_path(deny, "Read", path), path


def test_overwriting_the_real_env_file_is_denied_but_not_the_example(deny):
    assert denied_path(deny, "Edit", ".env") and denied_path(deny, "Edit", "x/.env")
    assert not denied_path(deny, "Edit", ".env.example")


@pytest.mark.parametrize("command", [
    "cat .env", "cat ./.env", "cat /srv/proj/.env", "head -n 3 .env", "grep KEY .env", "grep -n KEY .env | head", 'cat ".env"', "cat '.env'",
    "sed -n 1p .env", "source .env", "set -a; . .env; set +a", "cat .env.local", "cat .env.production", "cp .env /tmp/x"])
def test_the_usual_shell_ways_to_read_the_env_file_are_denied(deny, command):
    assert denied_command(deny, command), command


@pytest.mark.parametrize("command", [
    "cat .env.example", "git add .env.example", "diff .env.example .env.example.bak", "make test", "make llm-ping", "make smoke-llm", "make smoke-llm-dry",
    "git status --short", "git commit -m 'docs: atualiza o .env.example'", "ls -la", ".venv/bin/pytest tests/test_key_safety.py -q"])
def test_ordinary_commands_and_the_example_file_are_not_blocked(deny, command):
    assert not denied_command(deny, command), command


def test_the_known_gap_is_documented_not_hidden():
    """Um comando que le o .env sem escrever o nome dele nao e pego por regra de texto. O README precisa dizer isso."""
    readme = (SETTINGS.parent.parent / "README.md").read_text(encoding="utf-8")
    assert "var/decoy/.env" in readme and "nao e uma barreira" in readme.replace("não", "nao").replace("é", "e")
