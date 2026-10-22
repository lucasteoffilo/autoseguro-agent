"""Exporta as sessoes do Claude Code que VOCE escolher para `ai-logs/`, redigidas e com um INDEX.md. Nao decide quais sessoes entram.

    python tools/export_ai_logs.py --list                         # as sessoes que existem: id, inicio, fim, mensagens, tamanho e o primeiro pedido
    python tools/export_ai_logs.py ID [ID ...]                    # copia SO esses ids (id inteiro ou prefixo de 8+ caracteres) para ai-logs/ e refaz o INDEX.md
    python tools/export_ai_logs.py ID --redact "texto" --redact …  # redige tambem esse texto literal (um nome, um endereco)
    DATASET_PATH=…/conversations.parquet python tools/export_ai_logs.py ID --redact-dataset --redact-findings

Onde ficam as sessoes: `~/.claude/projects/<caminho-da-pasta-onde-a-sessao-abriu, com "/" trocado por "-">/<id>.jsonl`. Por padrao olha a pasta do repo e a de cima
(onde estas sessoes foram abertas); `--sessions-dir` aponta outra, e pode ser repetido.

O que a ferramenta redige SOZINHA, em toda linha copiada: caminho de home (o diretorio do usuario no macOS, no Linux e no Windows vira `~`, e o resto do caminho fica: `~/dev/x`),
o nome de usuario do sistema, e todo endereco de e-mail (`[EMAIL]`). O que ela NAO redige e faz parar: segredo (chaves sk-ant-/sk-or-/sk-, Bearer, AKIA, ghp_, chave privada) e PII
(CPF, telefone, placa) que sobrar, e linha do dataset. A sessao com sobra NAO e escrita, a saida diz o TIPO e a CONTAGEM (nunca o trecho) e o codigo e 3. Duas flags fazem a redacao:

  --redact-dataset   troca toda mensagem do dataset (corpo com 12 caracteres ou mais) por `[LINHA DO DATASET REDIGIDA]`, em qualquer lugar do texto, inclusive dentro de saida de
                     ferramenta e na forma escapada de JSON (aspas, acentos, quebra de linha, JSON dentro de JSON). O caminho do dataset vem da variavel DATASET_PATH, nunca de um arquivo
                     do repo. Sem a flag, mas com DATASET_PATH definida, a ferramenta so CONFERE e para se achar uma linha.
  --redact-findings  troca o que o scanner achar (segredo e PII: CPF, telefone, placa, chaves, Bearer…) por `[REDIGIDO:tipo]`. Para segredo, a saida AVISA: se alguma chave for real,
                     rotacione-a (a redacao limpa a copia, nao a sessao original nem quem ja a viu).

A redacao so toca o trecho que a linha do dataset ou o scanner indicam: o resto da sessao fica byte a byte igual (`tests/test_ai_logs.py`). Depois de redigir, a varredura roda de novo e
a sessao com sobra continua sem ser escrita. `tests/test_ai_logs.py` roda a mesma varredura sobre `ai-logs/**` do repo e reprova com um achado so.

Copiar so o `.jsonl`: as pastas `<id>/` ao lado (subagentes, resultados de ferramentas) NAO sao copiadas, e o INDEX.md diz isso.
Codigos de saida: 0 ok · 2 id inexistente, ambiguo, pasta de sessoes ausente ou DATASET_PATH ausente · 3 varredura achou segredo, PII ou linha do dataset (nada daquela sessao foi escrito).
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "src")]

from autoseguro.logexport import _ELEVEN, scan  # noqa: E402
from autoseguro.masker import cpf_is_valid  # noqa: E402
from autoseguro.pii import PATTERNS  # noqa: E402

HOME_PATH = re.compile(r"(?:/Users|/home)/[^/\s\"\\]+|[A-Za-z]:(?:\\\\|\\)Users(?:\\\\|\\)[^\\\s\"]+")
# O grupo 1 e uma barra invertida logo antes do endereco. Num .jsonl, um TAB escapado seguido de um decorator do Python parece, para o scanner do projeto, um e-mail que comeca na letra do
# escape e comeria o `t`, deixando uma barra solta e a linha deixaria de ser JSON valido. A redacao guarda o escape e troca so o resto.
EMAIL = re.compile(r"(\\)?([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
_JSON_ESCAPE = re.compile(r"u[0-9a-fA-F]{4}|[ntrbf\"/\\]")
# Formatos de segredo que a varredura do projeto (`autoseguro.pii`) ainda nao cobre; a varredura do repo (`tests/test_ai_logs.py`) e esta usam as mesmas.
EXTRA_SECRETS = {
    "chave_sk": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "bearer": re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{20,}"),
    "chave_aws": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "token_github": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "chave_privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
SECRET_KINDS = frozenset({"chave_anthropic", "chave_openrouter", "chave_sk", "bearer", "chave_aws", "token_github", "chave_privada"})
DATASET_MARK = "[LINHA DO DATASET REDIGIDA]"
DATASET_MIN = 12          # o mesmo corte do teste de higiene do repo (corpos com 12+ caracteres)
# Chave privada: do cabecalho ate o rodape; sem rodape, ate o fim da string JSON (nunca come as aspas de fechamento).
_PRIVATE_KEY = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.*?-----END [A-Z ]*PRIVATE KEY-----|[^"\n]*)', re.DOTALL)
# O que `--redact-findings` troca, em ordem (o mais especifico primeiro). E-mail e caminho de home ja foram tratados antes, sempre.
AUTO_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("chave_privada", _PRIVATE_KEY), ("chave_openrouter", PATTERNS["chave_openrouter"]), ("chave_anthropic", PATTERNS["chave_anthropic"]),
    ("chave_sk", EXTRA_SECRETS["chave_sk"]), ("bearer", EXTRA_SECRETS["bearer"]), ("chave_aws", EXTRA_SECRETS["chave_aws"]), ("token_github", EXTRA_SECRETS["token_github"]),
    ("cpf", PATTERNS["cpf"]), ("telefone_br", PATTERNS["telefone_br"]), ("placa_mercosul", PATTERNS["placa_mercosul"]))
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

    def email(m: re.Match[str]) -> str:
        lead, rest = m.group(1) or "", m.group(2)
        counts["e-mails"] += 1
        esc = _JSON_ESCAPE.match(rest) if lead else None
        return lead + (esc.group(0) if esc else "") + "[EMAIL]"

    return EMAIL.sub(email, text), counts


def redact_findings(text: str) -> tuple[str, Counter]:
    """`--redact-findings`: troca o que o scanner acha por `[REDIGIDO:tipo]`. So o trecho achado muda."""
    counts: Counter = Counter()
    for kind, rx in AUTO_PATTERNS:
        text, counts[kind] = rx.subn(f"[REDIGIDO:{kind}]", text)
    valid = 0

    def mark(m: re.Match[str]) -> str:
        nonlocal valid
        if not cpf_is_valid(m.group(0)):
            return m.group(0)
        valid += 1
        return "[REDIGIDO:cpf_valido]"

    text = _ELEVEN.sub(mark, text)
    counts["cpf_valido"] = valid
    return text, counts


def _lower(text: str) -> str:
    """`text.lower()` com o MESMO comprimento (alguns caracteres ganham letras ao minusculo; ali o caractere fica como esta), para os indices valerem no original."""
    low = text.lower()
    return low if len(low) == len(text) else "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


def _variants(body: str) -> set[str]:
    """Como um corpo aparece num .jsonl: cru, escapado como string JSON (com e sem \\uXXXX para acento) e escapado duas vezes (JSON dentro de JSON, o caso da saida de ferramenta)."""
    once, once_ascii = json.dumps(body, ensure_ascii=False)[1:-1], json.dumps(body)[1:-1]
    return {body, once, once_ascii, json.dumps(once, ensure_ascii=False)[1:-1], json.dumps(once_ascii)[1:-1]}


class DatasetIndex:
    """As mensagens do dataset (corpo com 12+ caracteres, sem espaco nas pontas, minusculo, como no teste de higiene do repo), prontas para achar onde aparecem num texto."""

    def __init__(self, bodies: Iterable[str]) -> None:
        by_prefix: dict[str, set[str]] = defaultdict(set)
        distinct = set()
        for raw in bodies:
            body = raw.strip().lower() if isinstance(raw, str) else ""
            if len(body) < DATASET_MIN:
                continue
            distinct.add(body)
            for v in _variants(body):
                by_prefix[v[:DATASET_MIN]].add(v)
        self._table = {k: sorted(vs, key=len, reverse=True) for k, vs in by_prefix.items()}
        self.size = len(distinct)

    @classmethod
    def from_parquet(cls, path: Path) -> DatasetIndex:
        import pandas as pd      # extra opcional `analysis`; o mesmo que o teste de higiene usa
        return cls(pd.read_parquet(path, columns=["message_body"]).message_body)

    def spans(self, text: str) -> list[tuple[int, int]]:
        """(inicio, fim) de cada mensagem do dataset no texto, sem sobreposicao, sem diferenciar maiuscula de minuscula; a mais longa vence."""
        low, table, out = _lower(text), self._table, []
        i, last = 0, len(low) - DATASET_MIN + 1
        while i < last:
            candidates = table.get(low[i:i + DATASET_MIN])
            if candidates:
                hit = next((v for v in candidates if low.startswith(v, i)), None)
                if hit:
                    out.append((i, i + len(hit)))
                    i += len(hit)
                    continue
            i += 1
        return out


def redact_dataset(text: str, index: DatasetIndex) -> tuple[str, int]:
    """Troca cada mensagem do dataset por `[LINHA DO DATASET REDIGIDA]`. So o trecho achado muda."""
    spans = index.spans(text)
    if not spans:
        return text, 0
    parts, pos = [], 0
    for start, end in spans:
        parts += [text[pos:start], DATASET_MARK]
        pos = end
    parts.append(text[pos:])
    return "".join(parts), len(spans)


def redact_all(text: str, *, literals: tuple[str, ...] = (), user: str = "", dataset: DatasetIndex | None = None, auto: bool = False) -> tuple[str, Counter]:
    """Toda a redacao de uma sessao, na ordem: linhas do dataset (se houver indice), literais, caminho de home, usuario, e-mail e, com `auto`, segredo e PII por tipo.
    Devolve o texto e a contagem por tipo (so os tipos que aconteceram)."""
    counts: Counter = Counter()
    if dataset is not None:
        text, counts["linhas do dataset"] = redact_dataset(text, dataset)
    text, base = redact(text, literals, user)
    counts.update(base)
    if auto:
        text, found = redact_findings(text)
        counts.update(found)
    return text, Counter({k: n for k, n in counts.items() if n})


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
              "- Quando o autor usou `--redact-dataset`, toda mensagem do dataset do desafio (corpo com 12 caracteres ou mais) virou `[LINHA DO DATASET REDIGIDA]`, também dentro de saída de ferramenta: o dataset não entra no repo. Com `--redact-findings`, o que o scanner achou (CPF, telefone, placa, chaves, Bearer) virou `[REDIGIDO:tipo]`; são, em geral, valores sintéticos dos testes do agente.",
              "- A varredura de segredos (chaves `sk-ant-`, `sk-or-`, `sk-`, Bearer, AKIA, `ghp_`, chave privada) e de PII (CPF, telefone, placa) roda de novo depois da redação e tem de dar zero achados; uma sessão com achado não é escrita. A mesma varredura roda como teste sobre esta pasta (`tests/test_ai_logs.py`).",
              "- Fora o trecho redigido, a sessão é copiada byte a byte como saiu.", "",
              "## O que foi excluído, e por quê", "",
              "- **As outras sessões da pasta de sessões do Claude Code**: são de outros trabalhos, não deste desafio. O autor escolhe os ids.",
              "- **As pastas `<id>/` ao lado de cada sessão** (subagentes e resultados de ferramentas): só o `.jsonl` da conversa foi copiado.",
              "- **Conversas em outras ferramentas** (ChatGPT, Cursor etc.), se houve: não estão aqui.", ""]
    return "\n".join(lines)


# --- comando ---------------------------------------------------------------------------------------------------------------------------------------------
def json_breaks(before: str, after: str) -> int:
    """Quantas linhas eram JSON valido e deixaram de ser depois da redacao. Tem de ser 0: seria um defeito da ferramenta, e a sessao nao e escrita."""
    def valid(line: str) -> bool:
        try:
            json.loads(line)
        except ValueError:
            return False
        return True

    b, a = before.split("\n"), after.split("\n")
    return sum(1 for x, y in zip(b, a, strict=False) if x.strip() and valid(x) and not valid(y)) if len(b) == len(a) else sum(1 for y in a if y.strip() and not valid(y))


def leftovers(text: str, dataset: DatasetIndex | None) -> Counter:
    """O que a varredura ainda acha DEPOIS da redacao, por tipo (nunca o trecho): segredo e PII, mais linha do dataset se houver indice."""
    left: Counter = Counter(k for _, k in findings(text))
    if dataset is not None:
        left["linha_do_dataset"] = len(dataset.spans(text))
    return Counter({k: n for k, n in left.items() if n})


def _fmt(counts: Counter) -> str:
    return ", ".join(f"{k} {n}" for k, n in sorted(counts.items())) or "nada"


def export(chosen: list[Session], out_dir: Path, literals: tuple[str, ...], stdout, user: str = "", *, dataset: DatasetIndex | None = None, redact_dataset_rows: bool = False,
           auto: bool = False) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    code, rotate = 0, Counter()
    for s in chosen:
        original = s.path.read_text(encoding="utf-8", errors="replace")
        text, counts = redact_all(original, literals=literals, user=user, dataset=dataset if redact_dataset_rows else None, auto=auto)
        left = leftovers(text, dataset)
        if broken := json_breaks(original, text):
            left["json_quebrado_pela_redacao"] = broken
        if left:
            code = 3
            hint = ("" if auto else " --redact-findings (segredo e PII)") + (" --redact-dataset (linhas do dataset, com DATASET_PATH)" if not redact_dataset_rows and (left.get("linha_do_dataset") or dataset is None) else "")
            print(f"{s.id}: NAO escrita. Depois da redacao a varredura ainda acha: {_fmt(left)}. Redigido ate aqui: {_fmt(counts)}."
                  + (f" Use{hint}, ou --redact com o literal." if hint else " Redija o que sobrou com --redact."), file=stdout)
            continue
        (out_dir / f"{s.id}.jsonl").write_text(text, encoding="utf-8")
        print(f"{s.id}: ok · {s.messages} msgs · redigido: {_fmt(counts)}", file=stdout)
        rotate.update({k: n for k, n in counts.items() if k in SECRET_KINDS})
    (out_dir / INDEX_NAME).write_text(index_markdown(out_dir, user), encoding="utf-8")
    print(f"{INDEX_NAME} refeito em {out_dir}", file=stdout)
    if rotate:
        print(f"AVISO (segredo): a redacao trocou {_fmt(rotate)} nas copias. Se alguma dessas chaves for REAL, rotacione-a no provedor: a redacao limpa a copia, "
              "nao a sessao original nem quem ja a viu. (Nos logs deste projeto as chaves vistas sao valores sinteticos de teste.)", file=stdout)
    return code


def main(argv: list[str] | None = None, *, stdout=None) -> int:
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(description="Exporta as sessoes do Claude Code escolhidas para ai-logs/, redigidas.")
    ap.add_argument("ids", nargs="*", help="ids das sessoes a copiar (inteiro ou prefixo de 8+ caracteres)")
    ap.add_argument("--list", action="store_true", help="lista as sessoes e sai")
    ap.add_argument("--sessions-dir", type=Path, action="append", default=None, help="pasta com os .jsonl (repetivel); padrao: a do repo e a de cima em ~/.claude/projects")
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="pasta de saida (padrao: ai-logs/)")
    ap.add_argument("--redact", action="append", default=[], help="texto literal a redigir tambem (repetivel)")
    ap.add_argument("--redact-dataset", action="store_true", help="troca toda mensagem do dataset (12+ caracteres) por [LINHA DO DATASET REDIGIDA]; o caminho vem de DATASET_PATH")
    ap.add_argument("--redact-findings", action="store_true", help="troca segredo e PII que o scanner achar por [REDIGIDO:tipo]; para segredo, avisa para rotacionar a chave se for real")
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
    dataset = None
    path = os.environ.get("DATASET_PATH")
    if args.redact_dataset and not (path and Path(path).is_file()):
        print("--redact-dataset precisa da variavel DATASET_PATH apontando para o conversations.parquet (o dataset nunca fica no repo)", file=sys.stderr)
        return 2
    if path and Path(path).is_file():            # com a flag, redige; sem ela, so confere (e para se achar)
        try:
            dataset = DatasetIndex.from_parquet(Path(path))
        except ImportError:
            if args.redact_dataset:
                print("--redact-dataset precisa do pandas e do pyarrow (pip install -e '.[analysis]')", file=sys.stderr)
                return 2
    return export(chosen, args.out, tuple(args.redact), stdout, user, dataset=dataset, redact_dataset_rows=args.redact_dataset, auto=args.redact_findings)


if __name__ == "__main__":
    raise SystemExit(main())
