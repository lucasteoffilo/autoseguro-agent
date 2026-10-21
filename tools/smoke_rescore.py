"""Reaplica os criterios ATUAIS do smoke, inclusive a ANCORAGEM, a um relatorio JA GRAVADO. Nao chama provedor nenhum, nao precisa de chave.

    python tools/smoke_rescore.py var/smoke/smoke-20261020T232421Z.json        # grava ao lado: smoke-...-ancorado.json (o original nao e tocado)

Para cada extracao gravada, reaplica o `SlotLedger` e acrescenta ao relatorio: (1) slots errados que chegariam a /quote sem confirmacao (o gate duro,
tem que dar 0), (2) confirmacoes pedidas por mensagem (o custo em turnos), (3) o erro silencioso do modelo CRU (reportado, nao e gate). O motivo
da mudanca de gate esta em README D7: o smoke mede o modelo cru, mas a garantia de preco e do sistema.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from autoseguro.anchoring import SlotLedger  # noqa: E402
from autoseguro.llm.base import LLMResult, Usage  # noqa: E402
from autoseguro.llm.schema import SlotValue, TurnOutput  # noqa: E402
from tools.smoke_llm import CallRecord, load_fact_base, print_report, score_call, summarize  # noqa: E402
from tools.smoke_messages import MESSAGES, SMOKE_TODAY  # noqa: E402

_DEFAULT_USAGE = {"input_tokens": 1340, "output_tokens": 61, "cache_read_tokens": 0, "cache_write_tokens": 0, "reasoning_tokens": 0}


def _turn_output(o: dict) -> TurnOutput:
    return TurnOutput(tuple(SlotValue(s["slot"], s["value"], s["uncertain"]) for s in o["slots"]), o["intent"], tuple(o["facts_used"]), o["reply"])


def rescore(report: dict) -> tuple[dict, list[dict]]:
    """(resumo com os criterios atuais, detalhe da ancoragem por chamada). Tolera fixtures sem latencia nem uso."""
    base, by_id = load_fact_base(), {m.id: m for m in MESSAGES}
    records, detail = [], []
    for c in report["calls"]:
        msg = by_id[c["msg_id"]]
        usage = c.get("usage") or _DEFAULT_USAGE
        if c.get("output") is None:
            res = LLMResult(None, c.get("error"), c.get("latency_s", 1.0), None, None, http_status=c.get("http_status"))
        else:
            res = LLMResult(_turn_output(c["output"]), None, c.get("latency_s", 1.9), Usage(**usage), "stop", http_status=c.get("http_status"))
            led = SlotLedger()
            led.ingest(res.output, msg.text, asked_slot=msg.asked_slot)
            if not c["warmup"]:
                detail.append({"msg_id": msg.id, "repeat": c["repeat"], "slots": [
                    {"slot": s, "status": led.state(s).status.value, "reason": led.state(s).reason.value if led.state(s).reason else None,
                     "value": led.state(s).value, "proposed": led.state(s).proposed, "question": led.question(s, base) if not led.state(s).quotable else None}
                    for s in dict.fromkeys(e.slot for e in res.output.slots)]})
        records.append(CallRecord(msg.id, report.get("model", "?"), c["repeat"], c["warmup"], c.get("error"), res.latency_s,
                                  None if res.usage is None else res.usage.__dict__, c.get("output"), score_call(msg, res, base),
                                  c.get("served_model"), c.get("http_status"), msg.adversarial))
    return summarize(records, report.get("model", "?")), detail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="onde gravar (padrao: ao lado do original, com o sufixo -ancorado)")
    a = ap.parse_args(argv)
    report = json.loads(a.report.read_text(encoding="utf-8"))
    summary, detail = rescore(report)
    print(f"relatorio: {a.report.name} | modelo: {report.get('model')} | hoje do smoke: {SMOKE_TODAY}")
    print_report([summary], dry=False)
    out = a.out or a.report.with_name(a.report.stem + "-ancorado.json")
    augmented = {**{k: v for k, v in report.items() if k not in ("summary",)}, "summary_original": report.get("summary"), "summary": summary,
                 "anchoring_detail": detail, "rescored_with": "tools/smoke_rescore.py (criterios atuais; ver README D7)"}
    out.write_text(json.dumps(augmented, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nrelatorio complementado: {out}")
    return 0 if summary["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
