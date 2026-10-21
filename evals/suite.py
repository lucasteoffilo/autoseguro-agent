"""Orquestra os evals: sinteticos (sempre), dataset (se o parquet existir), criterios, relatorio. Sai com codigo 1 se algum criterio quebrar."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

from evals import criteria, dataset, report, scenarios
from evals.runner import Backend, Result, run_conversation

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEED = 20261021
DEFAULT_SAMPLE = 30


def run_synthetic(backend: Backend) -> tuple[list[scenarios.Synthetic], list[Result]]:
    specs = scenarios.build(backend.today)
    return specs, [run_conversation(backend, s.id, s.lines, api=s.api, llm_failures=s.llm_failures) for s in specs]


def run_dataset(backend: Backend, convs: dict[str, list[str]], progress=None) -> list[Result]:
    out = []
    for n, (cid, lines) in enumerate(convs.items(), 1):
        out.append(run_conversation(backend, cid, lines, source="dataset", fill_in=True))
        if progress and n % 250 == 0:
            progress(n, len(convs))
    return out


def evaluate(backend: Backend, *, parquet: Path | None, sample_size: int, seed: int, progress=None) -> dict:
    specs, synth = run_synthetic(backend)
    ds_results: list[Result] = []
    ds_info = None
    if parquet is not None:
        convs = dataset.load_conversations(parquet)
        t0 = time.monotonic()
        ds_results = run_dataset(backend, convs, progress)
        ds_info = {"conversations": len(ds_results), "lead_messages": sum(len(v) for v in convs.values()), "seconds": time.monotonic() - t0,
                   "with_media": sum(1 for r in ds_results if any(m["meta"].get("media") for m in r.lead)),
                   "with_pii": sum(1 for r in ds_results if any(m["meta"].get("mask_kinds") for m in r.lead)),
                   "scripted_answers": sum(r.scripted for r in ds_results), "reached_quote": sum(1 for r in ds_results if any(q["kind"] == "quote" and q["status"] == "ok" for q in r.quotes)),
                   "distribution": report.distribution(ds_results)}
    everything = synth + ds_results
    checks = [criteria.price_check(everything, backend), criteria.synthetic_check(synth, specs), criteria.refusal_check(everything, backend),
              criteria.terminal_check(everything), criteria.pii_check(everything)]
    checks.sort(key=lambda c: c.id)
    by_id = {r.id: r for r in ds_results}
    picked = dataset.select({r.id: r.klass for r in ds_results}, sample_size, seed) if ds_results else []
    sample = [by_id[c] for c in picked]
    return {"specs": specs, "synth": synth, "dataset": ds_info, "ds_results": ds_results, "sample": sample, "checks": checks}


def write(outcome: dict, backend: Backend, seed: int, out_dir: Path, var_dir: Path, suffix: str = "") -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = report.markdown(backend_label=backend.label, today=backend.today.isoformat(), seed=seed, checks=outcome["checks"], synthetic=outcome["specs"],
                         synth_results=outcome["synth"], dataset=outcome["dataset"], sample=outcome["sample"])
    (out_dir / f"report{suffix}.md").write_text(md, encoding="utf-8")
    (out_dir / f"summary{suffix}.json").write_text(json.dumps(report.summary(checks=outcome["checks"], synth_results=outcome["synth"], dataset=outcome["dataset"],
                                                                     backend_label=backend.label, today=backend.today.isoformat(), seed=seed),
                                                      ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # transcricoes dos sinteticos (escritas a mao, podem ir ao repo) e da amostra do dataset (texto mascarado, mas do dataset: so em var/)
    (out_dir / "synthetic_transcripts.md").write_text("# Transcrições dos cenários sintéticos\n\n" + "\n\n".join(report.transcript(r) for r in outcome["synth"]) + "\n", encoding="utf-8")
    if outcome["sample"]:
        var_dir.mkdir(parents=True, exist_ok=True)
        (var_dir / "dataset_sample_transcripts.md").write_text("# Amostra do dataset (texto já mascarado; NÃO versionar)\n\n" + "\n\n".join(report.transcript(r) for r in outcome["sample"]) + "\n",
                                                               encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python tools/evals.py", description="Evals: sinteticos de handoff e conversas derivadas do dataset, contra os criterios do PLAN.")
    ap.add_argument("--api", default=None, help="API de cotacao HTTP (ex.: http://localhost:8100). Sem ela, usa o servico vendorizado em processo")
    ap.add_argument("--today", default=None, help="relogio dos evals (AAAA-MM-DD); padrao: hoje. No modo --api o servidor usa o relogio dele")
    ap.add_argument("--dataset", default=os.environ.get("DATASET_PATH"), help="parquet do dataset (padrao: DATASET_PATH); sem ele, so os sinteticos")
    ap.add_argument("--no-dataset", action="store_true")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", type=Path, default=ROOT / "evals" / "results")
    ap.add_argument("--var", type=Path, default=ROOT / "var" / "evals")
    args = ap.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else (datetime.now(UTC).date() if args.api else date.today())
    backend = Backend.http(args.api, today) if args.api else Backend.offline(today)
    parquet = None if args.no_dataset or not args.dataset or not Path(args.dataset).exists() else Path(args.dataset)
    if parquet is None and not args.no_dataset:
        print("[evals] dataset indisponivel (DATASET_PATH ausente ou inexistente): so os sinteticos.", file=sys.stderr)
    print(f"[evals] backend: {backend.label}", file=sys.stderr)
    outcome = evaluate(backend, parquet=parquet, sample_size=args.sample, seed=args.seed, progress=lambda n, t: print(f"[evals] {n}/{t} conversas", file=sys.stderr))
    suffix = "_api" if args.api else ""
    write(outcome, backend, args.seed, args.out, args.var, suffix)
    for c in outcome["checks"]:
        print(f"{c.id} {c.title}: {c.ratio} -> {'PASSA' if c.passed else 'FALHA'}")
        for f in c.failures[:10]:
            print(f"    - {f}")
    ok = all(c.passed for c in outcome["checks"])
    print(f"[evals] relatorio em {args.out / f'report{suffix}.md'} | {'PASSA' if ok else 'NAO PASSA'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
