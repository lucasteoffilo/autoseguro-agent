"""Relatorio dos evals em Markdown e JSON. So AGREGADOS e ids de cenario: nenhum texto de mensagem do dataset sai daqui (higiene do repo)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from evals.criteria import Check
from evals.runner import Result
from evals.scenarios import Synthetic

LIMITS = [
    "O `MockLLM` extrai com o mesmo leitor determinístico da ancoragem: **o mock prova o encanamento, não a qualidade da conversa.** Estes números dizem que o sistema não deixa o "
    "modelo (qualquer um) inventar preço nem recusa; não medem a naturalidade das respostas nem a taxa de acerto do modelo real (isso é a Etapa 7).",
    "As conversas do dataset são **reproduções**: as mensagens do lead respondem ao vendedor humano, não ao agente. Perguntas fora de ordem e dados que o agente já pediu "
    "viram parte da rotina. Por isso o desfecho do agente (cotada, recusada, handoff) **não é comparado com o desfecho do dataset**, que não é usado.",
    "O oráculo é o serviço de cotação (a lógica vendorizada, ou a API HTTP no modo `--api`). Perto de 31/12 o relógio do agente e o do servidor (UTC) podem discordar por horas.",
    "Os cenários sintéticos são o gabarito do motivo de handoff: foram escritos por quem escreveu o código. Cobrem cada motivo uma ou duas vezes, **não** a variedade da fala real.",
]


def _pct(n: int, d: int) -> str:
    return "—" if d == 0 else f"{100 * n / d:.1f}%"


def distribution(results: list[Result]) -> list[tuple[str, int]]:
    return sorted(Counter(r.klass for r in results).items(), key=lambda kv: (-kv[1], kv[0]))


def markdown(*, backend_label: str, today: str, seed: int, checks: list[Check], synthetic: list[Synthetic], synth_results: list[Result],
             dataset: dict[str, Any] | None, sample: list[Result] | None) -> str:
    by_id = {r.id: r for r in synth_results}
    ok = all(c.passed for c in checks)
    out = [f"# Relatório dos evals — {'PASSA' if ok else 'NÃO PASSA'}", "",
           f"- **Gerado em:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · **relógio dos evals:** {today} · **semente da seleção:** {seed}",
           f"- **Backend da `/quote` e oráculo:** {backend_label}",
           "- **LLM:** `MockLLM` (determinístico) atrás do mesmo `GuardedLLM` e do mesmo orquestrador de produção; nenhuma chamada de rede para LLM.",
           "", "## Critérios do PLAN", "", "| # | Critério | Resultado | Alvo | Veredito |", "|---|---|---|---|---|"]
    for c in checks:
        out.append(f"| {c.id} | {c.title} | {c.ratio} ({_pct(c.numerator, c.denominator)}) | {c.target} | {'**PASSA**' if c.passed else '**FALHA**'} |")
    out.append("")
    for c in checks:
        if c.info:
            out.append(f"- **{c.id}** — " + "; ".join(f"{k}: {v}" for k, v in c.info.items()))
    for c in checks:
        if c.notes:
            out += ["", f"### {c.id}: o que explicar ({len(c.notes)})", "", "Perfis que a API recusaria e que **não** terminaram em recusa. Não são falhas do critério (nenhum foi cotado); são os dois caminhos em que o "
                    "agente deliberadamente não diz \"recusado\":", ""] + [f"- {n}" for n in c.notes[:20]]
    for c in checks:
        if c.failures:
            out += ["", f"### Falhas de {c.id} ({len(c.failures)})", ""] + [f"- {f}" for f in c.failures[:40]]
    out += ["", f"## Cenários sintéticos ({len(synthetic)}, escritos à mão)", "", "| Cenário | Esperado | Obteve | |", "|---|---|---|---|"]
    for s in synthetic:
        r = by_id[s.id]
        want = s.expect_status + (f" · {s.expect_reason}" if s.expect_reason else "") + (f" · {s.expect_refusal_kind}" if s.expect_refusal_kind else "")
        got = r.klass + (f" · {', '.join(str(m['meta'].get('refusal_kind')) for m in r.agent if m['kind'] == 'refusal')}" if r.status == "refused" else "")
        good = r.status == s.expect_status and (r.reason == s.expect_reason if s.expect_status == "handoff" else True)
        out.append(f"| `{s.id}` | {want} | {got} | {'✅' if good else '❌'} |")
    if dataset is not None:
        out += ["", "## Conversas derivadas do dataset (população inteira)", "",
                f"- **{dataset['conversations']} conversas** reproduzidas ({dataset['lead_messages']} mensagens do lead, {dataset['seconds']:.0f}s). "
                "Colunas lidas: `conversation_id`, `message_index`, `sender_role`, `message_type`, `message_body` — nenhuma das que vazam o gabarito.",
                f"- **O harness responde só o que o roteiro do vendedor nunca pergunta:** a cobertura e a data de início, uma vez cada e só quando o agente pergunta "
                f"({dataset['scripted_answers']} respostas no total). Todo o resto é a fala do próprio lead. Chegaram a uma cotação `ok`: {dataset['reached_quote']} conversas.",
                f"- Conversas com mídia sem transcrição: {dataset['with_media']} ({_pct(dataset['with_media'], dataset['conversations'])}) · "
                f"com PII mascarada: {dataset['with_pii']} ({_pct(dataset['with_pii'], dataset['conversations'])})", "",
                "| Desfecho do agente | Conversas | % |", "|---|---|---|"]
        total = dataset["conversations"]
        out += [f"| {k} | {n} | {_pct(n, total)} |" for k, n in dataset["distribution"]]
        if sample:
            out += ["", f"### Amostra determinística de {len(sample)} conversas (espalhada pelos desfechos do agente; os textos ficam em `var/evals/`, fora do repo)", "",
                    "| Conversa | Turnos | Desfecho do agente | Cotações (ok/recusa/fora) | Mídia | Pré-checagem |", "|---|---|---|---|---|---|"]
            for r in sample:
                qs = Counter(q["status"] for q in r.quotes)
                media = sum(1 for m in r.lead if m["meta"].get("media"))
                pre = next((m["meta"].get("precheck") for m in r.agent if m["meta"].get("precheck")), "—")
                out.append(f"| `{r.id}` | {r.turns} | {r.klass} | {qs.get('ok', 0)}/{qs.get('refused', 0)}/{qs.get('unavailable', 0)} | {media} | {pre} |")
    out += ["", "## O que estes números NÃO provam", ""] + [f"- {x}" for x in LIMITS] + [""]
    return "\n".join(out)


def summary(*, checks: list[Check], synth_results: list[Result], dataset: dict[str, Any] | None, backend_label: str, today: str, seed: int) -> dict[str, Any]:
    return {"passes": all(c.passed for c in checks), "backend": backend_label, "today": today, "seed": seed,
            "checks": {c.id: {"title": c.title, "numerator": c.numerator, "denominator": c.denominator, "failures": len(c.failures), "info": c.info, "notes": len(c.notes)} for c in checks},
            "synthetic": {"scenarios": len(synth_results), "distribution": dict(distribution(synth_results))},
            "dataset": None if dataset is None else {k: v for k, v in dataset.items() if k != "distribution"} | {"distribution": dict(dataset["distribution"])}}


def transcript(r: Result) -> str:
    """A conversa de um cenario (o texto do lead e o JA MASCARADO que ficou no banco)."""
    lines = [f"#### `{r.id}` — {r.klass}" + (f" ({r.detail})" if r.detail else ""), ""]
    # (as respostas do harness a perguntas de cobertura e data aparecem como mensagens normais do lead)
    leads, agents = iter(r.lead), iter(r.agent)
    # as mensagens alternam por turno; o 'hold' nao entra nos agentes terminais
    for turn in range(r.turns):
        lead = next(leads, None)
        if lead:
            lines.append(f"- **lead** › {lead['text']}")
        # todas as mensagens do agente deste turno: ate a terminal
        while True:
            m = next(agents, None)
            if m is None:
                break
            body = m["text"].replace("\n", "\n  ")
            lines.append(f"- **agente** [{m['kind']}] › {body}")
            if m["kind"] != "hold":
                break
    return "\n".join(lines)
