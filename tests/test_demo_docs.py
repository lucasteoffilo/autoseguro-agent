"""docs/DEMO.md: os cenarios de demonstracao continuam verdadeiros. Cada linha da tabela roda pelo agente (mock + API em processo) e termina como o documento diz; o README liga ao documento;
as sementes documentadas sao as testadas; os links relativos resolvem."""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from evals.runner import Backend, run_conversation
from tests.test_probe_seed import RETRY_SEED, SLOW_SEED

ROOT = Path(__file__).resolve().parent.parent
DEMO = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
TODAY = date(2026, 10, 21)   # os exemplos usam 01/11/2026: o relogio e fixo para o teste valer em qualquer dia


def scenarios() -> dict[int, tuple[str, list[str]]]:
    """{numero: (nome, mensagens do lead)} lidos da tabela 'Cenários' do documento."""
    table = DEMO.split("## Cenários", 1)[1].split("\n## ", 1)[0]
    out = {}
    for row in table.splitlines():
        cells = [c.strip() for c in row.strip().strip("|").split(" | ")]
        if len(cells) >= 4 and cells[0].isdigit():
            out[int(cells[0])] = (cells[1], re.findall(r"`([^`]+)`", cells[2]))
    return out


def run(n: int):
    return run_conversation(Backend.offline(TODAY), f"demo-{n}", scenarios()[n][1])


def test_the_document_has_the_eight_scenarios_and_each_one_has_messages():
    s = scenarios()
    assert sorted(s) == list(range(1, 9)) and all(len(lines) >= 2 for _, lines in s.values())


def test_scenarios_1_and_2_end_in_a_quote_built_from_the_api_answer():
    r1, r2 = run(1), run(2)
    assert (r1.status, r2.status) == ("quoted", "quoted")
    assert "plano Completo" in r1.agent[-1]["text"] and "plano Essencial" in r2.agent[-1]["text"]
    assert [q["kind"] for q in r1.quotes] == ["quote"] == [q["kind"] for q in r2.quotes]


def test_scenario_3_refuses_on_the_second_turn_after_the_apis_confirmation_without_asking_coverage_or_date():
    r = run(3)
    assert r.status == "refused" and [q["kind"] for q in r.quotes] == ["precheck"] and r.turns == 2 and len(r.agent) == 2
    assert r.agent[-1]["kind"] == "refusal"


def test_scenario_4_offers_one_alternative_and_quotes_it_again_on_the_api():
    r = run(4)
    assert r.status == "quoted" and [q["kind"] for q in r.quotes] == ["quote", "alternative"]
    assert "(outra opção para você comparar)" in r.agent[-1]["text"] and "desconto" not in "\n".join(m["text"] for m in r.agent).lower()


def test_scenario_5_is_a_human_request_handoff():
    r = run(5)
    assert (r.status, r.reason, r.component) == ("handoff", "HUMAN_REQUESTED", None)


def test_scenario_6_confirms_the_model_year_and_quotes_with_2016():
    r = run(6)
    assert r.status == "quoted" and any(m["text"].endswith("Só pra confirmar: modelo 2016?") for m in r.agent)
    assert '"veiculo_ano": 2016' in r.quotes[0]["request"]


def test_scenario_7_the_injection_gets_no_discount_no_prompt_and_no_price():
    r = run(7)
    said = "\n".join(m["text"] for m in r.agent)
    assert r.status == "open" and r.quotes == []
    for forbidden in ("R$", "90%", "desconto", "prompt", "regras do reply", "fatos"):
        assert forbidden not in said.lower(), forbidden


def test_scenario_8_audio_twice_goes_to_a_human():
    r = run(8)
    assert (r.status, r.reason) == ("handoff", "MEDIA_UNREADABLE") and r.lead[0]["meta"]["media"] == "audio"


def test_the_seeds_the_docs_name_are_exactly_the_tested_ones():
    for doc in (README, DEMO):
        assert f"QUOTE_SEED={RETRY_SEED}" in doc and f"QUOTE_SEED={SLOW_SEED}" in doc
        assert set(re.findall(r"QUOTE_SEED=(\d+)", doc)) <= {str(RETRY_SEED), str(SLOW_SEED)}, "semente documentada e nao testada"


@pytest.mark.parametrize("doc", ["README.md", "docs/DEMO.md"])
def test_every_relative_link_in_the_docs_resolves(doc):
    text = (ROOT / doc).read_text(encoding="utf-8")
    base = (ROOT / doc).parent
    broken = [t for t in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text) if not t.startswith(("http://", "https://", "mailto:")) and not (base / t).exists()]
    assert not broken, broken


def test_the_readme_links_to_the_demo_and_the_demo_is_where_the_scenarios_live():
    assert "[`docs/DEMO.md`](docs/DEMO.md)" in README
    assert "| 8 | Áudio |" in DEMO and "| 8 | Áudio |" not in README
