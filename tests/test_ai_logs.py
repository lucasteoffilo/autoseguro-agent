"""tools/export_ai_logs.py: lista as sessoes, copia SO os ids passados, redige caminho de home, gera o INDEX.md e a varredura de segredos e PII vira teste sobre `ai-logs/**`."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tests import synthetic_pii
from tools import export_ai_logs as E

ROOT = Path(__file__).resolve().parent.parent
V = synthetic_pii.values()
HOME = "/Us" + "ers/fulana"           # montado em tempo de execucao: nenhum caminho de home como literal no repo
ID_A, ID_B, ID_C = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa", "aaaaaaaa-2222-4222-8222-bbbbbbbbbbbb", "cccccccc-3333-4333-8333-cccccccccccc"


def line(kind: str, text: str, ts: str, **extra) -> str:
    return json.dumps({"type": kind, "timestamp": ts, "message": {"role": kind, "content": text}, **extra}, ensure_ascii=False)


def session(path: Path, *texts: str, start: str = "2026-10-20T10:00:00.000Z") -> Path:
    rows = [line("user" if i % 2 == 0 else "assistant", t, f"2026-10-20T10:{i:02d}:00.000Z") for i, t in enumerate(texts)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def sessions_dir(tmp_path):
    d = tmp_path / "projects" / "-pasta"
    d.mkdir(parents=True)
    session(d / f"{ID_A}.jsonl", f"abra o arquivo {HOME}/dev/x/app.py e me explique", "claro, li o arquivo")
    session(d / f"{ID_B}.jsonl", "segunda sessão do mesmo dia", "ok", "mais uma", "resposta")
    session(d / f"{ID_C}.jsonl", "uma sessão de OUTRO trabalho", "ok")
    (d / ID_A).mkdir()                      # a pasta de subagentes ao lado: nao e copiada
    (d / ID_A / "subagent.jsonl").write_text("{}\n", encoding="utf-8")
    return d


def run(*argv, capsys=None):
    out = io.StringIO()
    code = E.main(list(argv), stdout=out)
    return code, out.getvalue()


# --- redacao -----------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    (HOME + "/dev/x/app.py", "~/dev/x/app.py"),
    ("cwd=" + HOME + "/dev/desafio", "cwd=~/dev/desafio"),
    ("/ho" + "me/fulana/projeto/a.py", "~/projeto/a.py"),
    (json.dumps("C:\\Users\\fulana\\Documents\\x"), json.dumps("~\\Documents\\x")),
    ('{"path": "' + HOME + '/a", "other": "' + HOME + '/b"}', '{"path": "~/a", "other": "~/b"}'),
])
def test_home_paths_in_every_form_become_a_tilde(raw, expected):
    text, counts = E.redact(raw)
    assert text == expected and counts["caminhos de home"] >= 1


def test_the_system_user_outside_a_path_and_the_given_literals_are_redacted():
    text, counts = E.redact("o usuário fulana-dev rodou; o nome Joana Prado apareceu duas vezes: Joana Prado", literals=("Joana Prado",), user="fulana-dev")
    assert text == "o usuário [USUARIO] rodou; o nome [REDIGIDO] apareceu duas vezes: [REDIGIDO]" and counts["literais"] == 2 and counts["usuario do sistema"] == 1


def test_every_email_becomes_a_mark_even_the_noreply_of_a_trailer():
    text, counts = E.redact(f"contato {V['email']} e Co-Authored-By: Claude <noreply" + "@anthropic.com> e " + "ok@example" + ".com")
    assert "@" not in text and text.count("[EMAIL]") == 3 and counts["e-mails"] == 3


def test_a_generic_system_user_is_never_used_as_a_literal(monkeypatch):
    for generic in ("root", "user", "ADMIN", "abc"):
        monkeypatch.setattr(E.getpass, "getuser", lambda g=generic: g)
        assert E.system_user() == "", generic
    monkeypatch.setattr(E.getpass, "getuser", lambda: "fulana-dev")
    assert E.system_user() == "fulana-dev"


# --- varredura ----------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("sample,kind", [
    (V["cpf"], "cpf"), (V["cpf_digits"], "cpf_valido"), (V["tel_plus"], "telefone_br"), (V["placa_mercosul"], "placa_mercosul"),
    (V["key_or"], "chave_openrouter"), (V["key_ant"], "chave_anthropic"), (V["bearer"] + "x" * 8, "bearer"),
    ("sk-" + "A1b2C3d4" * 3, "chave_sk"), ("AK" + "IA" + "ABCDEFGHIJKLMNOP", "chave_aws"), ("gh" + "p_" + "a1B2" * 9, "token_github"),
    ("-----BEGIN RSA " + "PRIVATE KEY-----", "chave_privada"),
])
def test_the_scan_finds_each_kind_and_reports_the_line_never_the_snippet(sample, kind):
    found = E.findings(f"primeira linha limpa\nlinha com {sample} no meio\nultima")
    assert (2, kind) in found and all(isinstance(n, int) and isinstance(k, str) for n, k in found)


def test_a_clean_text_has_no_findings():
    assert E.findings("Sessão normal: o agente cotou 2021, 34 anos, CEP 30130-010, e a mensalidade veio da API.\n{\"ok\": true}") == []


# --- lista, copia e indice ------------------------------------------------------------------------------------------------------------------------
def test_list_shows_id_dates_messages_size_and_the_first_request_redacted(sessions_dir):
    code, out = run("--list", "--sessions-dir", str(sessions_dir))
    assert code == 0 and ID_A in out and ID_B in out and ID_C in out
    assert "2026-10-20 10:00" in out and "msgs" in out and HOME not in out and "~/dev/x/app.py" in out


def test_without_ids_it_lists_instead_of_copying(sessions_dir, tmp_path):
    out_dir = tmp_path / "ai-logs"
    code, out = run("--sessions-dir", str(sessions_dir), "--out", str(out_dir))
    assert code == 0 and ID_A in out and not out_dir.exists()


def test_only_the_ids_you_pass_are_copied_redacted_and_indexed(sessions_dir, tmp_path):
    out_dir = tmp_path / "ai-logs"
    code, out = run(ID_A, "--sessions-dir", str(sessions_dir), "--out", str(out_dir))
    assert code == 0
    assert sorted(p.name for p in out_dir.iterdir()) == ["INDEX.md", f"{ID_A}.jsonl"], "nem as outras sessoes nem a pasta de subagentes"
    copied = (out_dir / f"{ID_A}.jsonl").read_text(encoding="utf-8")
    assert HOME not in copied and "~/dev/x/app.py" in copied and copied.count("\n") == 2
    index = (out_dir / "INDEX.md").read_text(encoding="utf-8")
    assert f"`{ID_A}`" in index and ID_B not in index and ID_C not in index
    assert "O que foi redigido" in index and "O que foi excluído, e por quê" in index and "outros trabalhos" in index and "subagentes" in index


def test_a_prefix_of_eight_characters_works_and_a_second_run_adds_to_the_index(sessions_dir, tmp_path):
    out_dir = tmp_path / "ai-logs"
    run(ID_A[:8] + "-1111", "--sessions-dir", str(sessions_dir), "--out", str(out_dir))
    run(ID_C[:8], "--sessions-dir", str(sessions_dir), "--out", str(out_dir))
    index = (out_dir / "INDEX.md").read_text(encoding="utf-8")
    assert f"`{ID_A}`" in index and f"`{ID_C}`" in index and ID_B not in index


@pytest.mark.parametrize("ids", [["nao-existe-123"], [ID_A[:8]], ["aaaa"]])
def test_unknown_ambiguous_or_too_short_ids_stop_with_exit_2_and_write_nothing(sessions_dir, tmp_path, ids, capsys):
    out_dir = tmp_path / "ai-logs"
    code, _ = run(*ids, "--sessions-dir", str(sessions_dir), "--out", str(out_dir))
    assert code == 2 and not out_dir.exists() and "id" in capsys.readouterr().err


def test_a_missing_sessions_folder_is_exit_2(tmp_path, capsys):
    assert run("--list", "--sessions-dir", str(tmp_path / "nao-existe"))[0] == 2 and "nao encontrada" in capsys.readouterr().err


def test_a_session_with_a_leftover_secret_or_pii_is_not_written_exit_3_and_the_output_never_shows_the_snippet(sessions_dir, tmp_path):
    session(sessions_dir / f"{ID_B}.jsonl", f"o lead mandou o cpf {V['cpf']} e a chave {V['key_or']}", "ok")
    out_dir = tmp_path / "ai-logs"
    code, out = run(ID_A, ID_B, "--sessions-dir", str(sessions_dir), "--out", str(out_dir))
    assert code == 3 and (out_dir / f"{ID_A}.jsonl").exists() and not (out_dir / f"{ID_B}.jsonl").exists(), "a boa e escrita, a com sobra nao"
    assert V["cpf"] not in out and V["key_or"] not in out and "cpf" in out and "chave_openrouter" in out and "--redact" in out
    assert ID_B not in (out_dir / "INDEX.md").read_text(encoding="utf-8")


def test_redact_lets_the_author_clean_what_the_scan_stopped(sessions_dir, tmp_path):
    session(sessions_dir / f"{ID_B}.jsonl", f"o lead mandou o cpf {V['cpf']}", "ok")
    out_dir = tmp_path / "ai-logs"
    assert run(ID_B, "--sessions-dir", str(sessions_dir), "--out", str(out_dir))[0] == 3
    code, _ = run(ID_B, "--sessions-dir", str(sessions_dir), "--out", str(out_dir), "--redact", V["cpf"])
    assert code == 0 and V["cpf"] not in (out_dir / f"{ID_B}.jsonl").read_text(encoding="utf-8")


def test_email_in_a_session_is_redacted_not_a_stopper(sessions_dir, tmp_path):
    session(sessions_dir / f"{ID_B}.jsonl", f"meu e-mail é {V['email']}", "ok")
    out_dir = tmp_path / "ai-logs"
    assert run(ID_B, "--sessions-dir", str(sessions_dir), "--out", str(out_dir))[0] == 0
    assert V["email"] not in (out_dir / f"{ID_B}.jsonl").read_text(encoding="utf-8")


# --- a varredura sobre o que o repo entrega ------------------------------------------------------------------------------------------------------
def test_the_folder_scan_flags_what_is_left_and_passes_a_clean_folder(tmp_path):
    clean, dirty = tmp_path / "clean", tmp_path / "dirty"
    clean.mkdir()
    dirty.mkdir()
    (clean / "a.jsonl").write_text(line("user", "tudo limpo", "2026-10-20T10:00:00.000Z") + "\n", encoding="utf-8")
    (dirty / "a.jsonl").write_text(f"limpa\n{V['cpf']}\nsó um caminho {HOME}/x e um e-mail {V['email']}\n", encoding="utf-8")
    assert E.scan_folder(clean) == []
    assert sorted(E.scan_folder(dirty)) == ["a.jsonl: caminho de home", "a.jsonl: e-mail", "a.jsonl:2: cpf", "a.jsonl:3: caminho_de_home", "a.jsonl:3: email"]


def test_the_repos_ai_logs_have_no_secret_pii_email_or_home_path():
    """Roda sobre `ai-logs/**` do repo. Sem a pasta (um clone sem os logs), pula com o motivo; a entrega (`make delivery-check`) exige a pasta."""
    folder = ROOT / "ai-logs"
    if not folder.is_dir():
        pytest.skip("ai-logs/ ainda nao existe neste clone")
    assert E.scan_folder(folder) == []
