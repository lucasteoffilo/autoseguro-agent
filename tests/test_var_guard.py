"""Item 7: a suite nao escreve no var/ real. Tres camadas: o fotografo, o plugin numa suite de mentira (reprova de verdade) e a cota do cli redirecionada."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

from autoseguro import cli
from tests.var_guard import changes, snapshot

ROOT = Path(__file__).resolve().parent.parent


def test_snapshot_sees_created_changed_and_removed_files_and_directories(tmp_path):
    var = tmp_path / "var"
    (var / "smoke").mkdir(parents=True)
    (var / "smoke" / "quota.jsonl").write_text("a\n")
    (var / "gone.txt").write_text("x")
    before = snapshot(var)
    (var / "smoke" / "quota.jsonl").write_text("a\nb\n")
    (var / "gone.txt").unlink()
    (var / "novo").mkdir()
    (var / "novo" / "z.db").write_text("z")
    lines = changes(before, snapshot(var))
    assert [x.split(":")[0] for x in lines] == ["criado", "criado", "removido", "alterado"]
    assert "criado: novo" in lines and "criado: novo/z.db" in lines and "removido: gone.txt" in lines and any(x.startswith("alterado: smoke/quota.jsonl") for x in lines)


def test_an_untouched_tree_and_a_missing_one_have_no_changes(tmp_path):
    var = tmp_path / "var"
    (var / "a").mkdir(parents=True)
    (var / "a" / "f").write_text("1")
    assert changes(snapshot(var), snapshot(var)) == [] and changes(snapshot(tmp_path / "nao-existe"), snapshot(tmp_path / "nao-existe")) == []


def test_a_var_that_did_not_exist_and_is_created_by_the_suite_is_a_change(tmp_path):
    assert changes(snapshot(tmp_path / "var"), {".": ("dir", 0, 0)}) == ["criado: ."]


def _mini_suite(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    """Uma suite de mentira com o MESMO plugin apontado para um var/ de mentira: o que o plugin faz com a suite de verdade, ele faz aqui."""
    var = tmp_path / "var"
    var.mkdir()
    (var / "ja_existia.txt").write_text("de quem roda o projeto")
    (tmp_path / "conftest.py").write_text(textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        from pathlib import Path
        from tests.var_guard import VarGuard

        def pytest_configure(config):
            config.pluginmanager.register(VarGuard(Path({str(var)!r})), "var-guard")
    """))
    (tmp_path / "test_mini.py").write_text(textwrap.dedent(body).format(var=str(var)))
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_mini.py"], cwd=tmp_path, capture_output=True, text=True, timeout=60)


def test_the_plugin_fails_the_whole_run_when_a_test_writes_in_var(tmp_path):
    r = _mini_suite(tmp_path, """
        from pathlib import Path
        def test_ok_but_writes():
            Path("{var}/smoke").mkdir()
            (Path("{var}/smoke") / "quota.jsonl").write_text("{{}}")
        """)
    assert "1 passed" in r.stdout and r.returncode != 0, "o teste passou, a execucao NAO"
    assert "criado: smoke/quota.jsonl" in r.stdout and "A SUITE ESCREVEU" in r.stdout


def test_the_plugin_fails_the_run_when_a_test_appends_to_an_existing_file(tmp_path):
    r = _mini_suite(tmp_path, """
        from pathlib import Path
        def test_appends():
            with open("{var}/ja_existia.txt", "a") as f:
                f.write(" mais")
        """)
    assert r.returncode != 0 and "alterado: ja_existia.txt" in r.stdout


def test_the_plugin_lets_a_suite_that_leaves_var_alone_pass(tmp_path):
    r = _mini_suite(tmp_path, """
        def test_clean(tmp_path):
            (tmp_path / "x").write_text("fora do var")
        """)
    assert r.returncode == 0 and "A SUITE ESCREVEU" not in r.stdout


def test_the_suite_has_its_quota_log_redirected_away_from_the_real_var():
    assert ROOT / "var" not in cli.QUOTA_LOG.parents and cli.QUOTA_LOG.name == "quota.jsonl"


def test_the_real_llm_built_by_the_cli_counts_its_requests_in_the_redirected_quota():
    """Era o que o test_cli fazia: montar o LLM real com um servidor falso e gravar 'request' no var/smoke/quota.jsonl de quem roda a suite."""
    import json
    from autoseguro.facts import FactBase
    planos = json.loads((ROOT / "vendor" / "quote-service" / "data" / "plans.json").read_text(encoding="utf-8"))
    env = {"LLM_PROVIDER": "openai_compat", "LLM_BASE_URL": "http://localhost:1/v1", "LLM_API_KEY": "chave-de-teste-123456", "LLM_MODEL": "fornecedor/modelo",
           "LLM_STRUCTURED_OUTPUT": "none"}
    llm = cli.make_llm_for("real", FactBase.from_planos(planos), env=env)
    assert llm.inner._quota.path == cli.QUOTA_LOG
