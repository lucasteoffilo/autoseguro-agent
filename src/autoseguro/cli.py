"""Terminal: a conversa de ponta a ponta. O LLM (mock ou real) entra pelo MESMO caminho: `GuardedLLM` -> `Orchestrator`.

    python -m autoseguro                       # conversa com o MockLLM (offline, deterministico) e a /quote em QUOTE_API_URL (padrao: localhost:8000)
    python -m autoseguro --llm real            # o modelo configurado em .env (LLM_PROVIDER, LLM_MODEL, LLM_API_KEY); gasta a cota diaria do provedor
    python -m autoseguro --script conversa.txt # as linhas do arquivo sao as mensagens do lead (uma por linha; '#' comenta)

Comandos na conversa: /novo (outra conversa), /sair. Tudo vai para o SQLite (`--db`, padrao var/autoseguro.db): o texto ja mascarado, as cotacoes
e as tentativas. O que o lead digita aparece so no terminal dele; nem o LLM, nem o banco, nem a saida do agente o veem sem mascara.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TextIO

from .facts import FactBase
from .llm.config import LLMConfig
from .llm.factory import make_llm
from .llm.guarded import GuardedLLM
from .llm.redact import redact
from .llm.throttle import QuotaLog, RateLimiter, ThrottledLLM
from .mock_llm import MockLLM
from .orchestrator import Orchestrator, Out
from .quote_client import QuoteClient
from .store import Store

ROOT = Path(__file__).resolve().parents[2]
VENDORED_PLANOS = ROOT / "vendor" / "quote-service" / "data" / "plans.json"
DEFAULT_API = "http://localhost:8000"
FREE_RPM, FREE_DAILY_FALLBACK = 20, 50


def load_env(path: Path) -> None:
    """KEY=VALUE de um .env, sem sobrescrever o ambiente. Nunca imprime valores; arquivo ilegivel = segue com o ambiente."""
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip("'\"")
        if value:
            os.environ.setdefault(key.strip(), value)


def fetch_planos(api_url: str, *, timeout_s: float = 5.0) -> tuple[dict[str, Any], str]:
    """(planos, de onde vieram). Sem /planos no ar, usa a copia vendorizada e DIZ isso: nao e silencioso."""
    try:
        with urllib.request.urlopen(api_url.rstrip("/") + "/planos", timeout=timeout_s) as r:  # noqa: S310 - URL vem de configuracao
            return json.loads(r.read()), api_url.rstrip("/") + "/planos"
    except (urllib.error.URLError, OSError, ValueError):
        return json.loads(VENDORED_PLANOS.read_text(encoding="utf-8")), f"{VENDORED_PLANOS.relative_to(ROOT)} (a /planos de {api_url} nao respondeu)"


def make_llm_for(mode: str, base: FactBase, *, env: dict[str, str] | None = None, quota_path: Path | None = None) -> GuardedLLM:
    """Mock e modelo real saem daqui como o MESMO tipo: `GuardedLLM` (gate de PII antes da chamada, guardrail depois)."""
    if mode == "mock":
        return GuardedLLM(MockLLM(base), base)
    if env is None:
        load_env(ROOT / ".env")
    cfg = LLMConfig.from_env(env if env is not None else dict(os.environ))
    quota = QuotaLog(quota_path or ROOT / "var" / "smoke" / "quota.jsonl", FREE_DAILY_FALLBACK)  # a cota do provedor e uma so: smoke e conversa dividem o contador
    if cfg.model.endswith(":free"):
        quota.daily_limit = quota.last_remote_limit() or FREE_DAILY_FALLBACK
    else:
        quota.daily_limit = 10**9
    return make_llm(cfg, base, wrap=lambda a: ThrottledLLM(a, limiter=RateLimiter(FREE_RPM), quota=quota))


def build_orchestrator(*, llm_mode: str = "mock", api_url: str = DEFAULT_API, quote_url: str | None = None, db_path: str | Path = ":memory:",
                       ids: Any = None, handoff_next_step: str = "", env: dict[str, str] | None = None) -> tuple[Orchestrator, Store, dict[str, str]]:
    """O orquestrador de producao montado. `quote_url`: onde fica a /quote, se for diferente de onde vem a /planos (os cenarios de queda usam isso)."""
    planos, planos_from = fetch_planos(api_url)
    base = FactBase.from_planos(planos)
    store = Store(db_path)
    llm = make_llm_for(llm_mode, base, env=env)
    orc = Orchestrator(llm=llm, store=store, quote_client=QuoteClient.http(quote_url or api_url), planos=planos, fact_base=base, ids=ids, mode=llm_mode,
                       handoff_next_step=handoff_next_step)
    return orc, store, {"llm": f"{llm.provider}/{llm.model}", "planos": planos_from, "quote_api": quote_url or api_url, "db": str(db_path)}


def show(out: Out, stream: TextIO) -> None:
    label = "agente" if out.terminal else "agente (aguarde)"
    lines = out.text.splitlines() or [""]
    print(f"{label}> {lines[0]}", file=stream)
    for line in lines[1:]:
        print(f"        {line}", file=stream)
    stream.flush()


def converse(orc: Orchestrator, lines: Iterable[str], *, stdout: TextIO, interactive: bool, echo: bool) -> list[str]:
    """Roda a conversa. Devolve os trace_ids. `echo`: repete a linha do lead (no modo script; no interativo o terminal ja a mostra)."""
    traces = [orc.start()]
    if interactive:
        print(f"[conversa {traces[0]}]", file=stdout)
    for raw in lines:
        line = raw.rstrip("\n")
        if line.strip() == "/sair":
            break
        if line.strip() == "/novo":
            traces.append(orc.start())
            print(f"[conversa {traces[-1]}]", file=stdout)
            continue
        if not interactive and (not line.strip() or line.lstrip().startswith("#")):
            continue
        if echo:
            print(f"lead> {line}", file=stdout)
        result = orc.handle(traces[-1], line, send=lambda o: show(o, stdout))
        if result.status == "handoff" and not result.duplicate and interactive and len(result.terminal) and result.terminal[0].kind == "handoff":
            print("[conversa encaminhada a um consultor; /novo abre outra]", file=stdout)
    return traces


def _lines_from(stdin: TextIO | None, out: TextIO) -> Iterable[str]:
    """Interativo: o `input()` do terminal. Com um `stdin` dado (pipe, teste): le dele e repete a linha na saida, para a transcricao ficar completa."""
    if stdin is None:
        while True:
            try:
                yield input("lead> ")
            except EOFError:
                return
    else:
        for line in stdin:
            print(f"lead> {line.rstrip(chr(10))}", file=out)
            yield line.rstrip("\n")


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m autoseguro", description="Agente de cotacao de seguro auto, no terminal.")
    ap.add_argument("--llm", choices=("mock", "real"), default="mock", help="mock: offline e deterministico. real: o modelo do .env (usa a cota do provedor)")
    ap.add_argument("--api", default=os.environ.get("QUOTE_API_URL", DEFAULT_API), help="API de cotacao (/planos e /quote)")
    ap.add_argument("--quote-api", default=None, help="/quote em outro endereco (para simular a queda da cotacao)")
    ap.add_argument("--db", default=str(ROOT / "var" / "autoseguro.db"), help="arquivo SQLite (padrao: var/autoseguro.db)")
    ap.add_argument("--script", type=Path, default=None, help="arquivo com as mensagens do lead, uma por linha")
    args = ap.parse_args(argv)
    out = stdout or sys.stdout
    try:
        orc, _store, info = build_orchestrator(llm_mode=args.llm, api_url=args.api, quote_url=args.quote_api, db_path=args.db)
    except Exception as exc:  # noqa: BLE001 - configuracao: diz o que faltou, sem jamais imprimir uma chave
        print(f"nao foi possivel iniciar: {redact(str(exc), [os.environ.get('LLM_API_KEY'), os.environ.get('OPENROUTER_API_KEY')])}", file=sys.stderr)
        return 2
    print(f"[AutoSeguro | LLM {info['llm']} | /quote {info['quote_api']} | planos de {info['planos']} | banco {info['db']}]", file=out)
    if args.script:
        converse(orc, args.script.read_text(encoding="utf-8").splitlines(), stdout=out, interactive=False, echo=True)
        return 0
    print("Escreva como o lead. /novo abre outra conversa, /sair encerra.", file=out)
    converse(orc, _lines_from(stdin, out), stdout=out, interactive=True, echo=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
