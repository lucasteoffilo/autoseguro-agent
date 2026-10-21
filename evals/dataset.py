"""Cenarios derivados do TEXTO das mensagens do dataset. Sem gabarito, de proposito.

O parquet tem tres colunas que vazam o resultado (`conversation_outcome`, `lead_idade_informada`, `veiculo_texto`: replicadas em toda linha da conversa, ver
docs/FINDINGS.md). Este modulo so le `LEAD_COLUMNS` (um teste confere que nenhuma outra coluna e pedida), e so as mensagens do LEAD: o que o vendedor humano disse
(preco, cobertura) nao e entrada do agente. O que o agente faz com elas e conferido contra o SERVICO, nao contra o desfecho do dataset.

O texto do dataset nunca entra no repo (teste de higiene): os cenarios sao montados a cada execucao a partir do parquet em `DATASET_PATH`, e a selecao dos ~30 e
deterministica (semente + hash do id). Quem tem o parquet reproduz os mesmos 30. A mascara e a do proprio agente (o orquestrador mascara antes de qualquer coisa).
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

LEAD_COLUMNS = ["conversation_id", "message_index", "sender_role", "message_type", "message_body"]


def _read_parquet_rows(path: str | Path, columns: list[str]) -> list[dict]:
    import pandas as pd   # extra opcional: pip install -e '.[analysis]'

    return pd.read_parquet(path, columns=columns).to_dict("records")


def load_conversations(path: str | Path, *, read_rows: Callable[[str | Path, list[str]], Iterable[dict]] = _read_parquet_rows) -> dict[str, list[str]]:
    """{conversation_id: mensagens do lead em ordem}. Midia chega como o marcador do dataset (`[audio] ...`), sem transcricao."""
    rows = [r for r in read_rows(path, list(LEAD_COLUMNS)) if r["sender_role"] == "lead"]
    rows.sort(key=lambda r: (r["conversation_id"], r["message_index"]))
    out: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        out[r["conversation_id"]].append(str(r["message_body"]))
    return dict(out)


def _rank(seed: int, cid: str) -> str:
    return hashlib.sha256(f"{seed}:{cid}".encode()).hexdigest()


def select(classes: dict[str, str], n: int, seed: int) -> list[str]:
    """~n conversas, espalhadas pelas classes de DESFECHO DO AGENTE (cotada, recusada, cada motivo de handoff, aberta), sem olhar o desfecho do dataset.
    Round-robin das menores classes para as maiores, e dentro da classe pela ordem do hash (deterministico)."""
    by_class: dict[str, list[str]] = defaultdict(list)
    for cid in sorted(classes, key=lambda c: _rank(seed, c)):
        by_class[classes[cid]].append(cid)
    queues = sorted(by_class.items(), key=lambda kv: (len(kv[1]), kv[0]))
    picked: list[str] = []
    while len(picked) < n and any(q for _, q in queues):
        for _, q in queues:
            if q and len(picked) < n:
                picked.append(q.pop(0))
    return sorted(picked)


def lines_for(convs: dict[str, Sequence[str]], cid: str) -> list[str]:
    return list(convs[cid])
