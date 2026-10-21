"""tools/delivery_check.py (`make delivery-check`): so o que os criterios de aceite da entrega exigem. Cada verificacao reprova com um controle negativo."""
from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest

from tests import synthetic_pii
from tools import delivery_check as D

V = synthetic_pii.values()
GOOD_README = """# Projeto

Descricao.

## Como rodar

```bash
make setup
make test
make chat
```

## Estado

Tudo certo, veja [o plano](docs/PLAN.md).

### D3. Uma chamada ao LLM por mensagem, que entende o lead

texto

### D11. O LLM entende, o código fala

texto

## O que ficou de fora

- coisas
"""
GOOD_LOG = """# Log de execução — `trc_0123456789ab`

- **LLM:** `openrouter/modelo` (modo `real`) · **criada em** 2026-10-21T18:18:26+00:00

| Verificação | Resultado |
|---|---|
| LLM real registrado | sim |
| Existe cotação `ok` | sim: qte_0123456789ab |
| Existe falha seguida de retry visível | sim: 1 tentativa(s) com decisão `retry` |
| Todo `R$` dito pelo agente existe numa cotação `ok` desta conversa | sim (2 valor(es)) |
| Sem PII nem segredo no texto exportado | sim (varredura do texto exportado: 0 achados) |

Cotação `qte_0123456789ab` para a conversa `trc_0123456789ab`.
"""
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git ausente (o container limpo do verify-clean nao o tem)")


def make_repo(root: Path, *, readme=GOOD_README, log=GOOD_LOG, ai_logs=True, commit=True) -> Path:
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "PLAN.md").write_text("plano\n", encoding="utf-8")
    (root / "README.md").write_text(readme, encoding="utf-8")
    if log is not None:
        (root / "logs" / "execucao-final").mkdir(parents=True)
        (root / "logs" / "execucao-final" / "cenario-1.md").write_text(log, encoding="utf-8")
        (root / "logs" / "execucao-final" / "index.md").write_text("# Conversas\n", encoding="utf-8")
    if ai_logs:
        (root / "ai-logs").mkdir()
        (root / "ai-logs" / "INDEX.md").write_text("# Logs de IA\n", encoding="utf-8")
        (root / "ai-logs" / "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa.jsonl").write_text('{"type": "user"}\n', encoding="utf-8")
    if shutil.which("git"):
        for cmd in (["init", "-q"], ["config", "user.email", "t@example.org"], ["config", "user.name", "t"], ["add", "-A"], ["commit", "-qm", "x"] if commit else ["status"]):
            subprocess.run(["git", *cmd], cwd=root, capture_output=True, check=True)
    return root


def run(root: Path) -> tuple[int, str]:
    out = io.StringIO()
    return D.main(["--root", str(root)], stdout=out), out.getvalue()


@needs_git
def test_a_good_repo_passes_every_check(tmp_path):
    code, out = run(make_repo(tmp_path))
    assert code == 0 and "FALHOU" not in out and "tudo passou" in out


# --- 1. README ------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad,expected", [
    (GOOD_README.replace("Descricao.", "Isto está _(planejado)_."), "marcador"),
    (GOOD_README.replace("Descricao.", "Valores provisórios até o smoke."), "marcador"),
    (GOOD_README.replace("Descricao.", "FIXME: rever."), "marcador"),
    (GOOD_README.replace("## Como rodar", "## Estado inicial", 1).replace("## Estado\n", "## Como rodar\n", 1), "primeira secao"),
    (GOOD_README.replace("make chat\n", "make chat\nmake mais\n"), "exatamente 3 comandos"),
    (GOOD_README.replace("## O que ficou de fora", "## Limites"), "O que ficou de fora"),
    (GOOD_README.replace("### D3. Uma chamada ao LLM por mensagem, que entende o lead", "### D3. O LLM redige a conversa"), "D3"),
    (GOOD_README.replace("### D11. O LLM entende, o código fala", "### D11. Outra coisa"), "D11"),
    (GOOD_README.replace("docs/PLAN.md", "docs/nao-existe.md"), "link relativo quebrado"),
])
def test_each_readme_problem_is_reported(tmp_path, bad, expected):
    repo = make_repo(tmp_path, readme=bad, commit=False)
    problems = D.readme(repo)
    assert any(expected in p for p in problems), problems


def test_a_missing_readme_is_reported(tmp_path):
    assert D.readme(tmp_path) == ["README.md ausente"]


def test_the_projects_own_readme_passes_the_readme_check():
    """O README de verdade: sem marcadores, com o Como rodar em tres comandos, a D3 corrigida, a D11, o que ficou de fora e os links resolvendo."""
    root = Path(__file__).resolve().parent.parent
    assert D.readme(root) == [], D.readme(root)


# --- 2. log da execucao ---------------------------------------------------------------------------------------------------------------------------
def test_the_log_check_passes_a_complete_real_run_log(tmp_path):
    assert D.execution_log(make_repo(tmp_path, commit=False)) == []


@pytest.mark.parametrize("bad,expected", [
    (GOOD_LOG.replace("(modo `real`)", "(modo `mock`)"), "modo `real`"),
    (GOOD_LOG.replace("| Existe cotação `ok` | sim: qte_0123456789ab |", "| Existe cotação `ok` | **não** |"), "cotacao `ok`"),
    (GOOD_LOG.replace("| Existe falha seguida de retry visível | sim: 1 tentativa(s) com decisão `retry` |", "| Existe falha seguida de retry visível | **não** |"), "retry"),
    (GOOD_LOG.replace("| sim (2 valor(es)) |", "| **NÃO**: R$ 1,00 |"), "todo R$"),
    (GOOD_LOG.replace("trc_0123456789ab", "trc_xyz"), "trace_id"),
    (GOOD_LOG + f"\nO lead mandou {V['cpf']}\n", "PII"),
])
def test_each_execution_log_problem_is_reported(tmp_path, bad, expected):
    problems = D.execution_log(make_repo(tmp_path, log=bad, commit=False))
    assert any(expected in p for p in problems), problems


def test_a_missing_log_or_index_is_reported(tmp_path):
    assert D.execution_log(make_repo(tmp_path, log=None, commit=False)) == [f"{D.LOG} ausente"]
    repo = make_repo(tmp_path / "b", commit=False)
    (repo / D.LOG_INDEX).unlink()
    assert D.execution_log(repo) == [f"{D.LOG_INDEX} ausente"]


# --- 3. ai-logs -----------------------------------------------------------------------------------------------------------------------------------
def test_ai_logs_must_exist_have_an_index_a_session_and_a_clean_scan(tmp_path):
    repo = make_repo(tmp_path / "ok", commit=False)
    assert D.ai_logs(repo) == []
    assert D.ai_logs(make_repo(tmp_path / "none", ai_logs=False, commit=False)) == ["ai-logs/ ausente"]
    (repo / "ai-logs" / "INDEX.md").unlink()
    assert D.ai_logs(repo) == ["ai-logs/INDEX.md ausente"]
    for f in (repo / "ai-logs").glob("*.jsonl"):
        f.unlink()
    assert "ai-logs/ sem nenhuma sessao (.jsonl)" in D.ai_logs(repo)


def test_ai_logs_with_a_secret_or_an_email_fail_and_the_message_never_shows_the_snippet(tmp_path):
    repo = make_repo(tmp_path, commit=False)
    (repo / "ai-logs" / "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb.jsonl").write_text(f'{{"t": "{V["key_or"]} e {V["email"]}"}}\n', encoding="utf-8")
    problems = D.ai_logs(repo)
    assert any("chave_openrouter" in p for p in problems) and any("e-mail" in p for p in problems)
    assert all(V["key_or"] not in p and V["email"] not in p for p in problems)


# --- 4. arvore limpa -------------------------------------------------------------------------------------------------------------------------------
@needs_git
def test_a_dirty_tree_and_forbidden_tracked_files_fail(tmp_path):
    repo = make_repo(tmp_path)
    assert D.git_tree(repo) == []
    (repo / "novo.txt").write_text("x", encoding="utf-8")
    assert any("arvore suja" in p for p in D.git_tree(repo))
    (repo / "novo.txt").unlink()
    (repo / ".env").write_text("X=1\n", encoding="utf-8")
    (repo / "banco.db").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-f", ".env", "banco.db"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "ruim"], cwd=repo, check=True, capture_output=True)
    assert {p for p in D.git_tree(repo)} == {"versionado e nao deveria: .env", "versionado e nao deveria: banco.db"}


def test_outside_a_git_repo_the_tree_check_fails_clearly(tmp_path):
    (tmp_path / "x").mkdir()
    assert D.git_tree(tmp_path / "x") and "git" in D.git_tree(tmp_path / "x")[0]


# --- o comando -------------------------------------------------------------------------------------------------------------------------------------
def test_the_exit_code_and_the_summary_reflect_the_failures(tmp_path):
    code, out = run(make_repo(tmp_path, log=None, ai_logs=False, commit=False))
    assert code == 1 and out.count("[FALHOU]") >= 2 and "verificacoes falharam" in out


def test_the_make_target_runs_the_check_and_then_the_tests():
    makefile = (Path(__file__).resolve().parent.parent / "Makefile").read_text(encoding="utf-8")
    target = makefile.split("delivery-check:", 1)[1].split("\n\n", 1)[0]
    assert "tools/delivery_check.py" in target and "$(MAKE) test" in target and target.index("delivery_check.py") < target.index("$(MAKE) test")


def test_without_git_installed_the_tree_check_says_so_instead_of_crashing(tmp_path, monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(D.subprocess, "run", no_git)
    assert D.git_tree(tmp_path) == ["git ausente: a arvore limpa nao pode ser conferida"]
