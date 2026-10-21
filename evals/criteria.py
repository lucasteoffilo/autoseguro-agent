"""Os criterios do PLAN, medidos contra o SERVICO (o oraculo), nunca contra o proprio agente:

  C1  100% sem preco inventado        todo "R$" de toda mensagem do agente e igual a um valor que o servico devolve para a entrada guardada daquela cotacao
  C2  100% de motivo de handoff correto nos sinteticos (e de status esperado em todos)
  C3  100% das recusas batendo com a API   cada conversa que terminou cotada ou recusada concorda com uma chamada INDEPENDENTE ao servico para a idade e o ano verificados;
                                           toda recusa dita liga a uma recusa registrada da API; o lead nunca le o texto cru dela
  C4  exatamente uma mensagem terminal por turno
  C5  nenhuma PII nas mensagens, no banco nem no pacote de handoff
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from autoseguro.facts import strip_accents
from autoseguro.handoff import HandoffReason
from autoseguro.masker import cpf_is_valid
from autoseguro.pii import find_pii
from autoseguro.refusals import classify_motive
from autoseguro.store import brl, money_in
from evals.runner import Backend, Result
from evals.scenarios import Synthetic

_ELEVEN = re.compile(r"(?<![\d.-])\d{11}(?![\d.-])")
_RAW_API = re.compile(r"\b(aceitacao|nao e aceito|faixas aceitas|inexistente)\b")


@dataclass
class Check:
    id: str
    title: str
    target: str
    numerator: int = 0
    denominator: int = 0
    failures: list[str] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)       # o que o relatorio explica por extenso (nao e falha)

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def ratio(self) -> str:
        return f"{self.numerator}/{self.denominator}"


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    import json
    return json.loads(row["request"])


def price_check(results: list[Result], backend: Backend) -> Check:
    c = Check("C1", "Nenhum preço inventado", "100%: todo R$ dito ao lead vem do serviço para a entrada daquela cotação")
    import json
    shown_msgs = backed_quotes = 0
    for r in results:
        allowed: set[str] = set()
        for q in r.quotes:
            if q["status"] != "ok" or q["kind"] == "precheck":
                continue
            status, body = backend.oracle(_payload(q))
            stored = json.loads(q["response"])
            if status != 200:
                c.failures.append(f"{r.id}: o serviço não aceita mais a entrada da cotação {q['id']}")
                continue
            if stored.get("premio_mensal") != body.get("premio_mensal") or stored.get("franquia") != body.get("franquia"):
                c.failures.append(f"{r.id}: o preço guardado em {q['id']} difere do que o serviço devolve agora")
            pro = (body.get("primeiro_pagamento_pro_rata") or {}).get("valor_primeiro_pagamento")
            allowed |= {brl(float(v)) for v in (body["premio_mensal"], body["franquia"], pro) if isinstance(v, (int, float))}
            backed_quotes += 1
        for i, m in enumerate(r.agent):
            values = money_in(m["text"])
            if values:
                shown_msgs += 1
            for v in values:
                c.denominator += 1
                if v in allowed:
                    c.numerator += 1
                else:
                    c.failures.append(f"{r.id}: mensagem {i + 1} diz {v}, que o serviço não devolveu para nenhuma cotação desta conversa")
            if m["kind"] == "quote":
                q = next((x for x in r.quotes if x["id"] == m["quote_id"]), None)
                if q is None or f"Mensalidade: {brl(q['premio_mensal'])}" not in m["text"]:
                    c.failures.append(f"{r.id}: a mensagem de cotação não mostra a mensalidade da cotação que ela cita")
    c.info = {"mensagens com R$": shown_msgs, "valores em reais conferidos": c.denominator, "cotações recalculadas no serviço": backed_quotes}
    return c


def _why_not_refused(r: Result) -> str:
    detail = r.detail or ""
    if r.reason == "QUOTE_UNAVAILABLE" and detail.startswith("precheck:"):
        return ("a pré-checagem previu a recusa e a API estava fora. O agente só diz \"recusado\" depois que a API confirma, então a conversa foi a um humano com o veredito "
                f"(`precheck: {(r.package or {}).get('precheck')}`) no pacote. É o comportamento projetado, não um erro.")
    if "ano_modelo_futuro" in detail:
        return ("ano-modelo futuro. A API o recusaria como \"fora das faixas\", mas pode ser um modelo do próximo ano, então a decisão é de um humano (`DATA_AMBIGUOUS`) em vez de uma recusa "
                "automática. É a regra do PLAN, não um erro.")
    return "a conversa terminou antes de a API confirmar a recusa. Conferir se é o comportamento esperado."


def _verified(r: Result) -> dict[str, str]:
    return {s: v["value"] for s, v in r.slots.items() if v.get("status") in ("anchored", "confirmed") and v.get("value") is not None}


def refusal_check(results: list[Result], backend: Backend) -> Check:
    """Cada DECISAO que o lead leu (uma cotacao ou uma recusa) e refeita no servico com a MESMA entrada que o agente usou (a linha de `quotes` que a mensagem cita):
    a recusa tem que ser recusa da API, com a mesma razao; a cotacao nao pode ser de um perfil que a API recusa."""
    c = Check("C3", "Recusas e cotações batem com a API", "100%: cada cotação e cada recusa dita ao lead concorda com o serviço para a mesma entrada; recusa dita sempre liga a uma recusa registrada")
    cheapest = min(backend.planos["planos"], key=lambda p: len(p["coberturas"]))["id"]
    refusals = quotes = late_quote_changes = refusable_not_decided = 0
    for r in results:
        rows = {q["id"]: q for q in r.quotes}
        for m in r.agent:
            if m["kind"] == "refusal":
                c.denominator += 1
                refusals += 1
                row = rows.get(m["quote_id"])
                if row is None or row["status"] != "refused":
                    c.failures.append(f"{r.id}: recusa dita sem uma recusa registrada da API")
                    continue
                status, body = backend.oracle(_payload(row))
                if status != 422:
                    c.failures.append(f"{r.id}: o agente recusou e o serviço NÃO recusa a entrada {_payload(row)}")
                elif m["meta"].get("refusal_kind") != classify_motive(body.get("motivo", "")).value:
                    c.failures.append(f"{r.id}: a razão dita ({m['meta'].get('refusal_kind')}) difere da do serviço ({classify_motive(body.get('motivo', '')).value})")
                elif _RAW_API.search(strip_accents(m["text"]).lower()):
                    c.failures.append(f"{r.id}: o lead leu texto cru da API")
                else:
                    c.numerator += 1
            elif m["kind"] == "quote":
                c.denominator += 1
                quotes += 1
                row = rows.get(m["quote_id"])
                if row is None or row["status"] != "ok":
                    c.failures.append(f"{r.id}: cotação dita sem uma cotação ok registrada")
                    continue
                status, _ = backend.oracle(_payload(row))
                if status == 200:
                    c.numerator += 1
                else:
                    c.failures.append(f"{r.id}: o agente COTOU uma entrada que o serviço não cota ({status}): {_payload(row)}")
        if r.status not in ("quoted", "refused"):
            v = _verified(r)
            if "idade" in v and "veiculo_ano" in v:
                status, _ = backend.oracle({"plano_id": cheapest, "idade": int(v["idade"]), "veiculo_ano": int(v["veiculo_ano"])})
                if status == 422 and not any(m["kind"] == "refusal" for m in r.agent):
                    refusable_not_decided += 1
                    c.notes.append(f"`{r.id}` terminou em `{r.klass}` ({r.detail or 'sem detalhe'}), e a API recusaria: {_why_not_refused(r)}")
    c.info = {"recusas ditas ao lead": refusals, "cotações ditas ao lead": quotes, "perfil recusável que terminou sem recusa (handoff ou aberto)": refusable_not_decided}
    return c


def synthetic_check(results: list[Result], scenarios: list[Synthetic]) -> Check:
    by_id = {r.id: r for r in results}
    reasons = Check("C2", "Motivo de handoff correto nos sintéticos", "100%: status, motivo e componente esperados em cada cenário escrito à mão")
    covered = {s.expect_reason for s in scenarios if s.expect_reason}
    missing = {r.value for r in HandoffReason} - covered
    if missing:
        reasons.failures.append(f"motivos de handoff sem cenário sintético: {sorted(missing)}")
    for s in scenarios:
        r = by_id[s.id]
        reasons.denominator += 1
        problems = []
        if r.status != s.expect_status:
            problems.append(f"status {r.status!r} (esperado {s.expect_status!r})")
        if s.expect_status == "handoff":
            if r.reason != s.expect_reason:
                problems.append(f"motivo {r.reason!r} (esperado {s.expect_reason!r})")
            if (r.component or None) != (s.expect_component or None):
                problems.append(f"componente {r.component!r} (esperado {s.expect_component!r})")
            if r.package is None or r.package.get("reason") != s.expect_reason:
                problems.append("pacote de handoff ausente ou com outro motivo")
        if s.expect_refusal_kind:
            kinds = [m["meta"].get("refusal_kind") for m in r.agent if m["kind"] == "refusal"]
            if s.expect_refusal_kind not in kinds:
                problems.append(f"razão da recusa {kinds} (esperada {s.expect_refusal_kind!r})")
        if problems:
            reasons.failures.append(f"{s.id}: " + "; ".join(problems))
        else:
            reasons.numerator += 1
    reasons.info = {"cenários de handoff": sum(1 for s in scenarios if s.expect_status == "handoff"), "motivos cobertos": f"{len(covered)}/{len(list(HandoffReason))}"}
    return reasons


def terminal_check(results: list[Result]) -> Check:
    c = Check("C4", "Uma mensagem terminal por turno", "100% dos turnos: nem silêncio, nem duas respostas")
    for r in results:
        for i, n in enumerate(r.terminal_per_turn, 1):
            c.denominator += 1
            if n == 1:
                c.numerator += 1
            else:
                c.failures.append(f"{r.id}: o turno {i} terminou com {n} mensagens terminais")
    return c


def pii_check(results: list[Result]) -> Check:
    c = Check("C5", "Nenhuma PII gravada", "0 achados no banco, nas mensagens e no pacote (detector do gate de envio + CPF com verificadores válidos)")
    for r in results:
        c.denominator += 1
        text = r.stored_text + "\n" + "\n".join(m["text"] for m in r.agent)
        found = find_pii(text) + (["cpf_valido"] if any(cpf_is_valid(m.group(0)) for m in _ELEVEN.finditer(text)) else [])
        if found:
            c.failures.append(f"{r.id}: {sorted(set(found))} gravado (trecho omitido)")
        else:
            c.numerator += 1
    return c
