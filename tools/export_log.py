"""Exporta o log de UMA execucao do SQLite para Markdown (mascarado e varrido). Ver src/autoseguro/logexport.py.

    python tools/export_log.py --db var/autoseguro.db --trace trc_ab12cd34ef56 --out var/log.md
    python tools/export_log.py --db var/autoseguro.db --trace latest-quoted      # a conversa cotada mais recente

Sai com 3 se a varredura achar PII ou segredo (nada e escrito) e com 2 se a conversa nao existe.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from autoseguro.logexport import ExportRefused, export_markdown, latest_trace  # noqa: E402
from autoseguro.store import Store  # noqa: E402


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
