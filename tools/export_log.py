"""Exporta o log de UMA execucao do SQLite para Markdown (mascarado e varrido). Ver src/autoseguro/logexport.py.

    python tools/export_log.py --db var/autoseguro.db --trace trc_ab12cd34ef56 --out var/log.md
    python tools/export_log.py --db var/autoseguro.db --trace latest-quoted      # a conversa cotada mais recente
    python tools/export_log.py --db var/autoseguro.db --trace all --out var/logs/   # TODAS as conversas do banco: um .md por conversa e um index.md

Com `--trace all`, `--out` e uma PASTA. Uma conversa recusada pela varredura nao e escrita (as outras sao), e a saida e 3.

Sai com 3 se a varredura achar PII ou segredo (nada e escrito) e com 2 se a conversa nao existe.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from autoseguro.logexport import ExportRefused, Origins, export_markdown, index_markdown, latest_trace, list_traces, origins_of  # noqa: E402
from autoseguro.store import Store  # noqa: E402


def export_all(store: Store, out_dir: Path) -> int:
    traces = list_traces(store)
    if not traces:
        print("o banco nao tem nenhuma conversa", file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)
    files, refused = {}, []
    for t in traces:
        try:
            (out_dir / f"{t}.md").write_text(export_markdown(store, t), encoding="utf-8")
            files[t] = f"{t}.md"
        except ExportRefused as exc:
            refused.append(f"{t}: {exc}")
    (out_dir / "index.md").write_text(index_markdown(store, traces, files=files), encoding="utf-8")
    print(f"{len(files)} de {len(traces)} conversas exportadas em {out_dir}/ (index.md lista todas)")
    total = Origins()
    for t in traces:
        total += origins_of(store.messages(t))
    print(f"texto do modelo: {total.counts['llm']} de {total.total} respostas ao lead; barrados pelo guardrail: {total.counts['barrado']}")
    for line in refused:
        print(f"RECUSADA pela varredura de PII, nada escrito: {line}", file=sys.stderr)
    return 3 if refused else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/export_log.py", description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=ROOT / "var" / "autoseguro.db")
    ap.add_argument("--trace", required=True, help="trace_id, ou 'latest' / 'latest-quoted'")
    ap.add_argument("--out", type=Path, default=ROOT / "var" / "log.md")
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"banco nao encontrado: {args.db}", file=sys.stderr)
        return 2
    store = Store(args.db)
    if args.trace == "all":
        return export_all(store, args.out)
    trace = args.trace
    if trace in ("latest", "latest-quoted"):
        trace = latest_trace(store, status="quoted" if trace == "latest-quoted" else None) or ""
    try:
        text = export_markdown(store, trace)
    except KeyError:
        print(f"conversa nao encontrada: {args.trace!r}", file=sys.stderr)
        return 2
    except ExportRefused as exc:
        print(f"{exc}. Nada foi escrito.", file=sys.stderr)
        return 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"log de {trace} em {args.out} ({len(text.splitlines())} linhas)")
    for line in text.splitlines():
        if line.startswith("| LLM real") or line.startswith("| Existe") or line.startswith("| Todo"):
            print("  " + line.strip("| ").replace(" | ", ": "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
