"""Atalho: `python tools/evals.py` (ver evals/suite.py)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from evals.suite import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
