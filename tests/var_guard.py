"""A suite nao escreve no var/ de verdade (a cota do provedor, os bancos e os logs de quem roda o projeto).

`snapshot` fotografa a arvore, `changes` diz o que mudou e `VarGuard` e o plugin do pytest que tira a foto na largada e, no fim, reprova a execucao inteira se var/ mudou
(`tests/conftest.py` o registra para o var/ do repo; `tests/test_var_guard.py` o exercita numa suite de mentira)."""
from __future__ import annotations

from pathlib import Path

import pytest


def snapshot(root: Path) -> dict[str, tuple[str, int, int]]:
    """caminho relativo -> (tipo, tamanho, mtime_ns). Diretorios entram (um var/ criado do nada tambem e escrita); arquivos por tamanho e instante da ultima escrita."""
    if not root.exists():
        return {}
    out: dict[str, tuple[str, int, int]] = {".": ("dir", 0, 0)}
    for p in sorted(root.rglob("*")):
        st = p.lstat()
        rel = p.relative_to(root).as_posix()
        out[rel] = ("dir", 0, 0) if p.is_dir() else ("file", st.st_size, st.st_mtime_ns)
    return out


def changes(before: dict[str, tuple[str, int, int]], after: dict[str, tuple[str, int, int]]) -> list[str]:
    """Uma linha por diferenca: criado, removido ou alterado."""
    lines = [f"criado: {p}" for p in sorted(after.keys() - before.keys())]
    lines += [f"removido: {p}" for p in sorted(before.keys() - after.keys())]
    lines += [f"alterado: {p} {before[p][1:]} -> {after[p][1:]}" for p in sorted(before.keys() & after.keys()) if before[p] != after[p]]
    return lines


class VarGuard:
    def __init__(self, root: Path) -> None:
        self.root, self.before = root, None

    def pytest_sessionstart(self, session) -> None:
        self.before = snapshot(self.root)

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        if self.before is None:
            return
        diff = changes(self.before, snapshot(self.root))
        if diff:
            print(f"\n\nA SUITE ESCREVEU EM {self.root} (ela nao pode: isole o caminho em tmp_path):\n  " + "\n  ".join(diff))
            session.exitstatus = int(pytest.ExitCode.TESTS_FAILED)
