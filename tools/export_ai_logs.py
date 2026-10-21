"""Exporta as sessoes do Claude Code que VOCE escolher para `ai-logs/`, redigidas e com um INDEX.md. Nao decide quais sessoes entram.

    python tools/export_ai_logs.py --list                         # as sessoes que existem: id, inicio, fim, mensagens, tamanho e o primeiro pedido
    python tools/export_ai_logs.py ID [ID ...]                    # copia SO esses ids (id inteiro ou prefixo de 8+ caracteres) para ai-logs/ e refaz o INDEX.md
    python tools/export_ai_logs.py ID --redact "texto" --redact …  # redige tambem esse texto literal (um nome, um endereco)

Onde ficam as sessoes: `~/.claude/projects/<caminho-da-pasta-onde-a-sessao-abriu, com "/" trocado por "-">/<id>.jsonl`. Por padrao olha a pasta do repo e a pasta de cima
(onde estas sessoes foram abertas); `--sessions-dir` aponta outra, e pode ser repetido.

O que a ferramenta redige SOZINHA, em toda linha copiada: caminho de home (o diretorio do usuario no macOS, no Linux e no Windows vira `~`, e o resto do caminho fica: `~/dev/x`), o nome de usuario do sistema,
e todo endereco de e-mail (`[EMAIL]`). O que ela NAO redige e faz parar: segredo (chaves sk-ant-/sk-or-/sk-, Bearer, AKIA, ghp_, chave privada) e PII (CPF, telefone, placa) que sobrar
depois disso. A sessao com sobra NAO e escrita, a saida diz o TIPO e a LINHA (nunca o trecho) e o codigo e 3: leia a linha na sessao original e redija com `--redact`.
`tests/test_ai_logs.py` roda a mesma varredura sobre `ai-logs/**` do repo e reprova com um achado so.

Copiar so o `.jsonl`: as pastas `<id>/` ao lado (subagentes, resultados de ferramentas) NAO sao copiadas, e o INDEX.md diz isso.
Codigos de saida: 0 ok · 2 id inexistente, ambiguo ou pasta de sessoes ausente · 3 varredura achou segredo ou PII (nada daquela sessao foi escrito).
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from autoseguro.logexport import scan  # noqa: E402

HOME_PATH = re.compile(r"(?:/Users|/home)/[^/\s\"\\]+|[A-Za-z]:(?:\\\\|\\)Users(?:\\\\|\\)[^\\\s\"]+")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
# Formatos de segredo que a varredura do projeto (`autoseguro.pii`) ainda nao cobre; a varredura do repo (`tests/test_ai_logs.py`) e esta usam as mesmas.
EXTRA_SECRETS = {
    "chave_sk": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "bearer": re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{20,}"),
    "chave_aws": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "token_github": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "chave_privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
OUT_DIR = ROOT / "ai-logs"
MIN_PREFIX = 8
INDEX_NAME = "INDEX.md"


def default_sessions_dirs() -> list[Path]:
    """As pastas de sessao do repo e da pasta de cima (o Claude Code guarda por pasta de abertura: `/a/b/c` vira `-a-b-c`)."""
    base = Path.home() / ".claude" / "projects"
    return [base / str(p).replace("/", "-") for p in (ROOT, ROOT.parent) if (base / str(p).replace("/", "-")).is_dir()]


# --- redacao e varredura ------------------------------------------------------------------------------------------------------------------------------
def system_user() -> str:
    """O nome de usuario do sistema, para redigir onde ele aparece fora de um caminho. Vazio se for curto ou generico demais (trocaria palavras comuns)."""
    user = getpass.getuser()
    return user if len(user) >= 4 and user.lower() not in {"root", "user", "ubuntu", "admin", "runner", "vscode", "node"} else ""


def redact(text: str, literals: tuple[str, ...] = (), user: str = "") -> tuple[str, Counter]:
    """(texto redigido, quantas vezes cada coisa foi redigida). Caminho de home vira `~`, o usuario do sistema (`user`) e os literais viram marcas, e-mail vira `[EMAIL]`."""
    counts: Counter = Counter()

    def sub(rx: re.Pattern[str], repl: str, key: str, s: str) -> str:
        out, n = rx.subn(repl, s)
        counts[key] += n
        return out

    text = sub(HOME_PATH, "~", "caminhos de home", text)
    if user:
        text = sub(re.compile(re.escape(user)), "[USUARIO]", "usuario do sistema", text)
    for lit in literals:
        if lit:
            n = text.count(lit)
            counts["literais"] += n
            text = text.replace(lit, "[REDIGIDO]")
    return sub(EMAIL, "[EMAIL]", "e-mails", text), counts


def findings(text: str) -> list[tuple[int, str]]:
    """(linha, tipo) de cada segredo ou PII que ainda esta no texto. NUNCA o trecho."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        kinds = scan(line) + [k for k, rx in EXTRA_SECRETS.items() if rx.search(line)]
        out += [(n, k) for k in kinds]
    return out


def scan_folder(folder: Path) -> list[str]:
    """Os problemas de TODO arquivo em `folder`: segredo ou PII (com a linha), caminho de home e e-mail que sobraram. Vazio = limpo. Nunca o trecho."""
    problems = []
    for p in sorted(folder.rglob("*")):
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        problems += [f"{p.relative_to(folder)}:{n}: {kind}" for n, kind in findings(text)]
        problems += [f"{p.relative_to(folder)}: {name}" for name, rx in (("caminho de home", HOME_PATH), ("e-mail", EMAIL)) if rx.search(text)]
    return problems


# --- leitura das sessoes -------------------------------------------------------------------------------------------------------------------------------
@dataclass
class Session:
    id: str
    path: Path
    started: str
    ended: str
    messages: int
    size: int
    first_prompt: str


def _text_of(message: object) -> str:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def describe(path: Path, user: str = "") -> Session:
    first, last, n, prompt = "", "", 0, ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        ts = row.get("timestamp")
        if isinstance(ts, str):
            first, last = first or ts, ts
        if row.get("type") in ("user", "assistant"):
            n += 1
        if not prompt and row.get("type") == "user" and not row.get("isMeta"):
            text = _text_of(row.get("message")).strip()
            if text and not text.startswith("<"):
                prompt = text
    shown, _ = redact(" ".join(prompt.split())[:120], user=user)
    return Session(path.stem, path, first, last, n, path.stat().st_size, shown or "—")


def list_sessions(dirs: list[Path], user: str = "") -> list[Session]:
    return sorted((describe(p, user) for d in dirs for p in d.glob("*.jsonl")), key=lambda s: s.started or "")


def _day(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts or "—"


def format_listing(sessions: list[Session]) -> str:
    rows = [f"{s.id}  {_day(s.started)} → {_day(s.ended)}  {s.messages:5d} msgs  {s.size // 1024:6d} KB  {s.first_prompt}" for s in sessions]
    return "\n".join(rows) if rows else "nenhuma sessao encontrada"


def resolve(ids: list[str], sessions: list[Session]) -> list[Session]:
    chosen: list[Session] = []
    for want in ids:
        hits = [s for s in sessions if s.id == want] or ([s for s in sessions if s.id.startswith(want)] if len(want) >= MIN_PREFIX else [])
        if len(hits) != 1:
            raise LookupError(f"id {want!r}: " + ("nenhuma sessao" if not hits else f"{len(hits)} sessoes comecam assim; passe o id inteiro") + f" (prefixo de {MIN_PREFIX}+ caracteres)")
        if hits[0] not in chosen:
            chosen.append(hits[0])
    return chosen


# --- INDEX.md --------------------------------------------------------------------------------------------------------------------------------------------
def index_markdown(out_dir: Path, user: str = "") -> str:
    rows = [describe(p, user) for p in sorted(out_dir.glob("*.jsonl"))]
    rows.sort(key=lambda s: s.started or "")
    lines = ["# Logs de IA", "",
             "Sessoes do Claude Code usadas neste desafio, escolhidas pelo autor, copiadas como saíram (`.jsonl`) depois da redação abaixo. Gerado por `tools/export_ai_logs.py`.", "",
             "| Sessão | Início | Fim | Mensagens | Tamanho | Primeiro pedido |", "|---|---|---|---|---|---|"]
    for s in rows:
        lines.append(f"| `{s.id}` | {_day(s.started)} | {_day(s.ended)} | {s.messages} | {s.size // 1024} KB | {s.first_prompt.replace('|', '/')} |")
    if not rows:
        lines.append("| — | — | — | — | — | nenhuma sessão exportada |")
    lines += ["", "## O que foi redigido", "",
              "- Caminho de home (o diretório do usuário no macOS, no Linux e no Windows) virou `~`; o nome de usuário do sistema virou `[USUARIO]`; todo endereço de e-mail virou `[EMAIL]`; textos literais indicados pelo autor viraram `[REDIGIDO]`.",
              "- A varredura de segredos (chaves `sk-ant-`, `sk-or-`, `sk-`, Bearer, AKIA, `ghp_`, chave privada) e de PII (CPF, telefone, placa) tem de dar zero achados; uma sessão com achado não é escrita. A mesma varredura roda como teste sobre esta pasta (`tests/test_ai_logs.py`).", "",
              "## O que foi excluído, e por quê", "",
              "- **As outras sessões da pasta de sessões do Claude Code**: são de outros trabalhos, não deste desafio. O autor escolhe os ids.",
              "- **As pastas `<id>/` ao lado de cada sessão** (subagentes e resultados de ferramentas): só o `.jsonl` da conversa foi copiado.",
              "- **Conversas em outras ferramentas** (ChatGPT, Cursor etc.), se houve: não estão aqui.", ""]
    return "\n".join(lines)


# --- comando ---------------------------------------------------------------------------------------------------------------------------------------------
def export(chosen: list[Session], out_dir: Path, literals: tuple[str, ...], stdout, user: str = "") -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    code = 0
    for s in chosen:
        text, counts = redact(s.path.read_text(encoding="utf-8", errors="replace"), literals, user)
        left = findings(text)
        if left:
            code = 3
            by_kind = Counter(k for _, k in left)
            print(f"{s.id}: NAO escrita. A varredura achou {dict(by_kind)}; linhas (da sessao REDIGIDA) {sorted({n for n, _ in left})[:12]}. Redija com --redact e rode de novo.", file=stdout)
            continue
        (out_dir / f"{s.id}.jsonl").write_text(text, encoding="utf-8")
        print(f"{s.id}: ok · {s.messages} msgs · redigido: {dict(counts) or 'nada'}", file=stdout)
    (out_dir / INDEX_NAME).write_text(index_markdown(out_dir, user), encoding="utf-8")
    print(f"{INDEX_NAME} refeito em {out_dir}", file=stdout)
    return code


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(description="Exporta as sessoes do Claude Code escolhidas para ai-logs/, redigidas.")
    ap.add_argument("ids", nargs="*", help="ids das sessoes a copiar (inteiro ou prefixo de 8+ caracteres)")
    ap.add_argument("--list", action="store_true", help="lista as sessoes e sai")
    ap.add_argument("--sessions-dir", type=Path, action="append", default=None, help="pasta com os .jsonl (repetivel); padrao: a do repo e a de cima em ~/.claude/projects")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="pasta de saida (padrao: ai-logs/)")
    ap.add_argument("--redact", action="append", default=[], help="texto literal a redigir tambem (repetivel)")
    args = ap.parse_args(argv)
    dirs = args.sessions_dir or default_sessions_dirs()
    missing = [d for d in dirs if not d.is_dir()]
    if not dirs or missing:
        print("pasta de sessoes nao encontrada: " + (", ".join(map(str, missing)) or "nenhuma das padrao em ~/.claude/projects") + " (use --sessions-dir)", file=sys.stderr)
        return 2
    user = system_user()
    sessions = list_sessions(dirs, user)
    if args.list or not args.ids:
        print(format_listing(sessions), file=stdout)
        return 0
    try:
        chosen = resolve(args.ids, sessions)
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 2
    return export(chosen, args.out, tuple(args.redact), stdout, user)


if __name__ == "__main__":
    raise SystemExit(main())
