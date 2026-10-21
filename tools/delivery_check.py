"""`make delivery-check`: o minimo que um avaliador abre primeiro, conferido num clone limpo. So o que os criterios de aceite da entrega exigem; depois dele o Makefile roda `make test`.

    python tools/delivery_check.py            # na raiz do repo (ou --root DIR)

1. README coerente: nenhum marcador de planejado, provisorio, TODO ou FIXME; "Como rodar" e a primeira secao, com os comandos; D3 nao diz mais que o LLM redige;
   D11 ("O LLM entende, o codigo fala") e "O que ficou de fora" existem; todo link relativo resolve.
2. O log de uma execucao completa com o LLM real (`logs/execucao-final/cenario-1.md`): modo `real`, trace_id e quote_id, cotacao `ok`, falha seguida de retry visivel, todo R$ numa
   cotacao ok, sem PII nem segredo, e o `index.md` da rodada ao lado.
3. `ai-logs/` presente, com `INDEX.md`, e a varredura de segredos e PII sem achado (a mesma de `tools/export_ai_logs.py` e de `tests/test_ai_logs.py`).
4. Arvore limpa (git), e nenhum `.env`, banco, parquet ou pasta `var/` versionado.

Sai com 0 se tudo passou e 1 se algo falhou; cada falha diz o que e onde, nunca o trecho de um segredo.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from autoseguro.logexport import scan  # noqa: E402
from tools.export_ai_logs import scan_folder  # noqa: E402

LOG = "logs/execucao-final/cenario-1.md"
LOG_INDEX = "logs/execucao-final/index.md"
MARKERS = re.compile(r"_\(planejad|_\(provis|\bplanejado\b|\bprovis[óo]rio|\bprovis[óo]rios\b|\bTODO\b|\bFIXME\b")
FORBIDDEN_TRACKED = re.compile(r"(^|/)(\.env(\..*)?|var/.*|.*\.(db|sqlite3?|parquet|pem|key))$")
Result = list[str]      # as falhas; vazio = passou


def readme(root: Path) -> Result:
    path = root / "README.md"
    if not path.is_file():
        return ["README.md ausente"]
    text = path.read_text(encoding="utf-8")
    problems = [f"README.md:{n}: marcador de planejado, provisorio, TODO ou FIXME" for n, line in enumerate(text.splitlines(), 1) if MARKERS.search(line)]
    h2 = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    if not h2 or not h2[0].lower().startswith("como rodar"):
        problems.append(f'a primeira secao ("## ") deve ser "Como rodar"; e {h2[0]!r}' if h2 else "README.md sem secoes")
    else:
        first = text.split("## ", 2)[1]
        block = re.search(r"```bash\n(.*?)```", first, flags=re.DOTALL)
        commands = [c for c in (block.group(1).splitlines() if block else []) if c.strip() and not c.strip().startswith("#")]
        if len(commands) != 3:
            problems.append(f'"Como rodar" deve abrir com um bloco de exatamente 3 comandos; tem {len(commands)}')
    if "O que ficou de fora" not in h2:
        problems.append('falta a secao "## O que ficou de fora"')
    d3 = re.search(r"^### D3\.(.*)$", text, flags=re.MULTILINE)
    if not d3:
        problems.append("falta a D3")
    elif re.search(r"\bredige\b", d3.group(1), flags=re.IGNORECASE):
        problems.append("o titulo da D3 ainda diz que o LLM redige a conversa")
    if not re.search(r"^### D11\..*LLM entende, o código fala", text, flags=re.MULTILINE):
        problems.append('falta a D11 "O LLM entende, o código fala"')
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
        if not target.startswith(("http://", "https://", "mailto:")) and not (root / target).exists():
            problems.append(f"link relativo quebrado: {target}")
    return problems


def execution_log(root: Path) -> Result:
    path = root / LOG
    if not path.is_file():
        return [f"{LOG} ausente"]
    text = path.read_text(encoding="utf-8")
    needs = {
        "modo `real` registrado": r"\(modo `real`\)",
        "LLM real registrado": r"\| LLM real registrado \| sim \|",
        "trace_id": r"`trc_[0-9a-f]{12}`",
        "quote_id": r"`qte_[0-9a-f]{12}`",
        "cotacao `ok`": r"\| Existe cotação `ok` \| sim",
        "falha seguida de retry visivel": r"\| Existe falha seguida de retry visível \| sim",
        "todo R$ numa cotacao ok": r"\| Todo `R\$` dito pelo agente existe numa cotação `ok` desta conversa \| sim",
        "sem PII nem segredo (declarado)": r"\| Sem PII nem segredo no texto exportado \| sim",
    }
    problems = [f"{LOG}: falta {what}" for what, rx in needs.items() if not re.search(rx, text)]
    problems += [f"{LOG}:{n}: PII ou segredo ({kind})" for n, line in enumerate(text.splitlines(), 1) for kind in scan(line)]
    if not (root / LOG_INDEX).is_file():
        problems.append(f"{LOG_INDEX} ausente")
    return problems


def ai_logs(root: Path) -> Result:
    folder = root / "ai-logs"
    if not folder.is_dir():
        return ["ai-logs/ ausente"]
    problems = [] if (folder / "INDEX.md").is_file() else ["ai-logs/INDEX.md ausente"]
    if not list(folder.glob("*.jsonl")):
        problems.append("ai-logs/ sem nenhuma sessao (.jsonl)")
    return problems + [f"ai-logs/{p}" for p in scan_folder(folder)]


def git_tree(root: Path) -> Result:
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)

    try:
        status = git("status", "--porcelain")
    except FileNotFoundError:
        return ["git ausente: a arvore limpa nao pode ser conferida"]
    if status.returncode != 0:
        return ["nao e um repositorio git (ou o git falhou)"]
    problems = [f"arvore suja: {line.strip()}" for line in status.stdout.splitlines()[:10]]
    problems += [f"versionado e nao deveria: {name}" for name in git("ls-files").stdout.splitlines() if FORBIDDEN_TRACKED.search(name)]
    return problems


CHECKS: list[tuple[str, Callable[[Path], Result]]] = [
    ("README coerente com o codigo", readme), ("log da execucao completa com o LLM real", execution_log), ("ai-logs/ presente, com indice e varredura", ai_logs),
    ("arvore limpa e nada que nao deveria estar versionado", git_tree)]


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(description="Confere o minimo da entrega.")
    ap.add_argument("--root", type=Path, default=ROOT)
    root = ap.parse_args(argv).root
    failed = 0
    for name, check in CHECKS:
        problems = check(root)
        print(f"[{'ok' if not problems else 'FALHOU'}] {name}", file=stdout)
        for p in problems:
            print(f"      - {p}", file=stdout)
        failed += bool(problems)
    print("delivery-check: " + ("tudo passou (falta `make test`)" if not failed else f"{failed} de {len(CHECKS)} verificacoes falharam"), file=stdout)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
