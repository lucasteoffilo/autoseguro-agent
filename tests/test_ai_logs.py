"""tools/export_ai_logs.py: lista as sessoes, copia SO os ids passados, redige caminho de home, gera o INDEX.md e a varredura de segredos e PII vira teste sobre `ai-logs/**`."""
from __future__ import annotations

import io
import json
from collections import Counter
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


@pytest.fixture(autouse=True)
def _no_dataset_in_the_environment(monkeypatch):
    """Quem roda a suite pode ter DATASET_PATH; a ferramenta so le o dataset quando o teste o aponta."""
    monkeypatch.delenv("DATASET_PATH", raising=False)


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


# =============================================================================================================================================================
# --redact-dataset e --redact-findings
# =============================================================================================================================================================
ROWS = [
    "bom dia, quero cotar o seguro do meu fusca azul",                      # simples
    'preciso do seguro do meu "carro" novo, é urgente',                     # aspas e acento: no jsonl aparece escapado
    "primeira linha da mensagem\nsegunda linha da mensagem",                # quebra de linha de verdade
    "curta demais",                                                         # 12 caracteres: entra
    "só onze car",                                                          # 11 caracteres: NAO entra
]
MARK = E.DATASET_MARK


def jsonl_line(text: str) -> str:
    return json.dumps({"type": "user", "timestamp": "2026-10-20T10:00:00.000Z", "message": {"role": "user", "content": text}}, ensure_ascii=False)


def test_dataset_rows_are_found_in_every_form_they_take_inside_a_jsonl():
    idx = E.DatasetIndex(ROWS)
    quoted = ROWS[1]
    forms = {
        "cru": f"antes {ROWS[0]} depois",
        "maiuscula": f"antes {ROWS[0].upper()} depois",
        "escapado como string json": "antes " + json.dumps(quoted, ensure_ascii=False)[1:-1] + " depois",
        "escapado com \\uXXXX": "antes " + json.dumps(quoted)[1:-1] + " depois",
        "quebra de linha escapada": "antes " + json.dumps(ROWS[2])[1:-1] + " depois",
        "json dentro de json (saida de ferramenta)": "antes " + json.dumps(json.dumps({"message_body": quoted}, ensure_ascii=False), ensure_ascii=False)[1:-1] + " depois",
    }
    for name, text in forms.items():
        out, n = E.redact_dataset(text, idx)
        assert n >= 1 and MARK in out and out.startswith("antes ") and out.endswith(" depois"), name
        low = out.lower()
        assert not any(b in low for b in (r.strip().lower() for r in ROWS if len(r.strip()) >= 12)), name


def test_a_row_is_replaced_exactly_and_everything_around_it_is_byte_for_byte_the_same():
    idx = E.DatasetIndex(ROWS)
    text = f"início ¬ ç ã\t {ROWS[0]} meio {ROWS[0]} fim {ROWS[3]}…"
    out, n = E.redact_dataset(text, idx)
    assert n == 3 and out == f"início ¬ ç ã\t {MARK} meio {MARK} fim {MARK}…"


def test_rows_under_twelve_characters_and_text_without_rows_are_untouched():
    idx = E.DatasetIndex(ROWS)
    text = f"uma frase qualquer: {ROWS[4]} e {ROWS[0][:20]}"
    assert E.redact_dataset(text, idx) == (text, 0)
    assert idx.size == 4


def test_the_longest_row_wins_when_one_starts_like_another():
    idx = E.DatasetIndex(["quero cotar o seguro", "quero cotar o seguro do meu fusca azul"])
    assert E.redact_dataset("x quero cotar o seguro do meu fusca azul y", idx) == (f"x {MARK} y", 1)


def test_lowercasing_keeps_the_length_even_for_characters_that_grow():
    text = "İstanbul İİ"
    assert len(E._lower(text)) == len(text)


@pytest.mark.parametrize("kind,sample", [
    ("cpf", V["cpf"]), ("cpf_valido", V["cpf_digits"]), ("telefone_br", V["tel_plus"]), ("placa_mercosul", V["placa_mercosul"]),
    ("chave_openrouter", V["key_or"]), ("chave_anthropic", V["key_ant"]), ("bearer", V["bearer"] + "x" * 8), ("chave_sk", "sk-" + "A1b2C3d4" * 3),
    ("chave_aws", "AK" + "IA" + "ABCDEFGHIJKLMNOP"), ("token_github", "gh" + "p_" + "a1B2" * 9),
])
def test_each_finding_type_becomes_a_visible_typed_marker_and_only_that_stretch_changes(kind, sample):
    text = f"antes {sample} depois"
    out, counts = E.redact_findings(text)
    assert out == f"antes [REDIGIDO:{kind}] depois" and counts[kind] == 1 and E.findings(out) == []


def test_an_eleven_digit_number_that_is_not_a_cpf_is_left_alone_and_a_private_key_goes_whole():
    plain = f"telefone sem DDD? {V['eleven_not_cpf']} fica"
    assert E.redact_findings(plain)[0] == plain
    key = "-----BEGIN RSA " + "PRIVATE KEY-----\\nMIIEabc\\ndef\\n-----END RSA " + "PRIVATE KEY-----"
    out, counts = E.redact_findings(f'{{"c": "{key}", "k": 1}}')
    assert out == '{"c": "[REDIGIDO:chave_privada]", "k": 1}' and counts["chave_privada"] == 1
    cut = "-----BEGIN " + 'PRIVATE KEY-----\\nMIIEabc'
    assert E.redact_findings(f'{{"c": "{cut}", "k": 1}}')[0] == '{"c": "[REDIGIDO:chave_privada]", "k": 1}'


def test_redaction_never_breaks_the_json_of_a_line_and_leaves_clean_lines_byte_identical(sessions_dir):
    clean = [jsonl_line(f"linha limpa número {i}: a cotação veio da API, ç ã é ü, \"aspas\" e \\barras") for i in range(5)]
    dirty = [jsonl_line(f"o lead mandou {V['cpf']} e a chave {V['key_or']}"), jsonl_line(f"linha do dataset: {ROWS[1]}"), jsonl_line(f"ligue para {V['tel_plus']} {V['placa_mercosul']}")]
    original = "\n".join([clean[0], dirty[0], clean[1], dirty[1], clean[2], clean[3], dirty[2], clean[4]]) + "\n"
    out, counts = E.redact_all(original, dataset=E.DatasetIndex(ROWS), auto=True)
    o_lines, r_lines = original.splitlines(), out.splitlines()
    assert len(o_lines) == len(r_lines) == 8
    for a, b in zip(o_lines, r_lines, strict=True):
        json.loads(b)
        assert (a == b) == (a in clean), "so a linha com achado muda; as outras sao identicas"
    expected = original.replace(V["cpf"], "[REDIGIDO:cpf]").replace(V["key_or"], "[REDIGIDO:chave_openrouter]").replace(V["tel_plus"], "[REDIGIDO:telefone_br]") \
        .replace(V["placa_mercosul"], "[REDIGIDO:placa_mercosul]").replace(json.dumps(ROWS[1], ensure_ascii=False)[1:-1], MARK)
    assert out == expected
    assert counts == {"linhas do dataset": 1, "cpf": 1, "chave_openrouter": 1, "telefone_br": 1, "placa_mercosul": 1}


def test_text_with_nothing_to_redact_comes_out_identical_whatever_the_characters():
    import random
    rng = random.Random(20261021)
    alphabet = "abcdefghij klmnop,.;:-_/\\\"'{}[]()0123456789çãéíóúüÇÃÉ\n\t"
    idx = E.DatasetIndex(ROWS)
    for _ in range(200):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 300)))
        if E.findings(text) or idx.spans(text):
            continue
        out, counts = E.redact_all(text, dataset=idx, auto=True)
        assert out == text and not counts


# --- a linha de comando --------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def parquet(tmp_path):
    pd = pytest.importorskip("pandas", reason="extra opcional ausente (pip install -e '.[analysis]')")
    pytest.importorskip("pyarrow")
    path = tmp_path / "ds.parquet"
    pd.DataFrame({"message_body": ROWS + [None]}).to_parquet(path)
    return path


def messy_session(path: Path) -> Path:
    rows = [line("user", f"cole isto: {ROWS[0]}", "2026-10-20T10:00:00.000Z"), line("assistant", f"vi o cpf {V['cpf']} e a chave {V['key_or']} (teste)", "2026-10-20T10:01:00.000Z"),
            jsonl_line(f"saida de ferramenta: {json.dumps({'message_body': ROWS[1]}, ensure_ascii=False)}"), line("user", "uma linha limpa", "2026-10-20T10:03:00.000Z")]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def test_without_the_flags_a_session_with_dataset_rows_and_findings_is_stopped_with_counts_per_type(sessions_dir, tmp_path, parquet, monkeypatch):
    messy_session(sessions_dir / f"{ID_B}.jsonl")
    monkeypatch.setenv("DATASET_PATH", str(parquet))
    out_dir = tmp_path / "ai-logs"
    code, out = run(ID_B, "--sessions-dir", str(sessions_dir), "--out", str(out_dir))
    assert code == 3 and not (out_dir / f"{ID_B}.jsonl").exists()
    assert "cpf" in out and "chave_openrouter" in out and "linha_do_dataset" in out and "--redact-findings" in out and "--redact-dataset" in out
    assert V["cpf"] not in out and V["key_or"] not in out and ROWS[0] not in out


def test_with_both_flags_the_session_passes_with_a_per_type_report_and_never_the_snippet(sessions_dir, tmp_path, parquet, monkeypatch):
    messy_session(sessions_dir / f"{ID_B}.jsonl")
    monkeypatch.setenv("DATASET_PATH", str(parquet))
    out_dir = tmp_path / "ai-logs"
    code, out = run(ID_B, "--sessions-dir", str(sessions_dir), "--out", str(out_dir), "--redact-dataset", "--redact-findings")
    assert code == 0
    assert "linhas do dataset 2" in out and "cpf 1" in out and "chave_openrouter 1" in out
    for secret in (V["cpf"], V["key_or"], ROWS[0], ROWS[1]):
        assert secret not in out
    written = (out_dir / f"{ID_B}.jsonl").read_text(encoding="utf-8")
    assert E.scan_folder(out_dir) == [] and written.count(MARK) == 2 and "[REDIGIDO:cpf]" in written and "uma linha limpa" in written
    assert all(json.loads(x) for x in written.splitlines())
    assert not any(b.strip().lower() in written.lower() for b in ROWS if len(b.strip()) >= 12), "o mesmo teste de higiene do repo passa"


def test_a_secret_redaction_prints_the_rotate_warning_and_a_pii_only_one_does_not(sessions_dir, tmp_path, parquet, monkeypatch):
    monkeypatch.setenv("DATASET_PATH", str(parquet))
    session(sessions_dir / f"{ID_B}.jsonl", f"a chave era {V['key_or']}", "ok")
    _, out = run(ID_B, "--sessions-dir", str(sessions_dir), "--out", str(tmp_path / "a"), "--redact-findings")
    assert "AVISO (segredo)" in out and "rotacione" in out and "chave_openrouter 1" in out
    session(sessions_dir / f"{ID_B}.jsonl", f"o cpf era {V['cpf']}", "ok")
    _, out = run(ID_B, "--sessions-dir", str(sessions_dir), "--out", str(tmp_path / "b"), "--redact-findings")
    assert "AVISO" not in out and "cpf 1" in out


def test_redact_dataset_without_the_environment_variable_is_exit_2(sessions_dir, tmp_path, capsys):
    code, _ = run(ID_A, "--sessions-dir", str(sessions_dir), "--out", str(tmp_path / "x"), "--redact-dataset")
    assert code == 2 and "DATASET_PATH" in capsys.readouterr().err and not (tmp_path / "x").exists()


def test_the_scan_runs_again_after_the_redaction_and_a_leftover_still_stops_the_session(sessions_dir, tmp_path, monkeypatch):
    session(sessions_dir / f"{ID_B}.jsonl", f"a chave era {V['key_or']}", "ok")
    monkeypatch.setattr(E, "redact_findings", lambda text: (text, Counter()))      # um redator que nao redige nada
    out_dir = tmp_path / "ai-logs"
    code, out = run(ID_B, "--sessions-dir", str(sessions_dir), "--out", str(out_dir), "--redact-findings")
    assert code == 3 and not (out_dir / f"{ID_B}.jsonl").exists() and "ainda acha" in out and "chave_openrouter" in out


def test_the_dataset_path_is_never_written_in_the_output_or_the_index(sessions_dir, tmp_path, parquet, monkeypatch):
    monkeypatch.setenv("DATASET_PATH", str(parquet))
    out_dir = tmp_path / "ai-logs"
    run(ID_A, "--sessions-dir", str(sessions_dir), "--out", str(out_dir), "--redact-dataset")
    assert all(str(parquet) not in p.read_text(encoding="utf-8") for p in out_dir.iterdir())


# --- e-mail dentro de escapes de JSON: o defeito que o dry-run achou -----------------------------------------------------------------------------------
AT = "@"       # montado em tempo de execucao: nenhum "e-mail" como literal neste arquivo (o teste de higiene do repo o acharia)


@pytest.mark.parametrize("raw,expected", [
    ("40\\t" + AT + "app.get(\\\"/health\\\")", "40\\t[EMAIL](\\\"/health\\\")"),     # decorator depois de um TAB escapado: nao e e-mail e nao pode comer o `t`
    ("linha\\nfulano" + AT + "dominio.com.br fim", "linha\\n[EMAIL] fim"),                     # e-mail logo depois de uma quebra de linha escapada
    ("acento\\u00e9maria" + AT + "dominio.com fim", "acento\\u00e9[EMAIL] fim"),
    ("contato maria" + AT + "dominio.com e outro", "contato [EMAIL] e outro"),
])
def test_email_redaction_keeps_the_json_escape_that_sits_right_before_it(raw, expected):
    out, counts = E.redact(raw)
    assert out == expected and counts["e-mails"] == 1
    json.loads('"' + out + '"')                                                   # continua sendo uma string JSON valida


def test_a_redaction_that_would_break_a_json_line_stops_the_session(sessions_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(E, "redact_all", lambda text, **kw: (text.replace('"type"', '"typ'), Counter()))     # um redator com defeito
    out_dir = tmp_path / "ai-logs"
    code, out = run(ID_A, "--sessions-dir", str(sessions_dir), "--out", str(out_dir))
    assert code == 3 and not (out_dir / f"{ID_A}.jsonl").exists() and "json_quebrado_pela_redacao" in out
