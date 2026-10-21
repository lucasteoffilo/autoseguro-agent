#!/usr/bin/env bash
# Prova que o repo funciona num ambiente LIMPO. Extrai uma arvore do git (git archive) para dentro de um container python:3.12-slim, cria um venv novo, instala
# do pyproject (pip install -e ".[EXTRAS]") e roda os testes. NADA do venv nem do disco do host entra no container: so os arquivos versionados.
#
#   tools/verify_clean.sh [REV] [EXTRAS]
#     REV      commit, branch ou tag (padrao HEAD), ou --worktree para provar a arvore de trabalho sem commitar (respeita o .gitignore)
#     EXTRAS   extras do pyproject: "dev,llm" (padrao: tudo que o autor usa) ou "dev" (so o nucleo: sem o SDK da Anthropic, o que o avaliador pode ter)
#
# Saida: versao do Python, pacotes instalados que importam, e o resumo do pytest com o motivo de cada skip.
set -euo pipefail
REV=${1:-HEAD}
EXTRAS=${2:-dev,llm}
IMAGE=${IMAGE:-python:3.12-slim}

cd "$(git rev-parse --show-toplevel)"
if [ "$REV" = "--worktree" ]; then
  INDEX=$(mktemp -u)
  trap 'rm -f "$INDEX"' EXIT
  GIT_INDEX_FILE="$INDEX" git add -A
  REV=$(GIT_INDEX_FILE="$INDEX" git write-tree)
  LABEL="arvore de trabalho ($REV)"
else
  LABEL="$REV ($(git rev-parse --short "$REV"))"
fi

echo "== verify-clean: $LABEL | extras=[$EXTRAS] | imagem=$IMAGE"
git archive --format=tar "$REV" | docker run --rm -i -e EXTRAS="$EXTRAS" -e PIP_DISABLE_PIP_VERSION_CHECK=1 -e PYTHONDONTWRITEBYTECODE=1 "$IMAGE" bash -euc '
  mkdir /src && tar -x -C /src && cd /src
  python --version
  python -m venv /venv
  /venv/bin/pip install -q -e ".[$EXTRAS]"
  echo "-- instalado:"; /venv/bin/pip list --format=freeze 2>/dev/null | grep -iE "^(anthropic|pytest|pandas|pyarrow|autoseguro)" || true
  /venv/bin/python -c "import anthropic" 2>/dev/null && echo "anthropic: PRESENTE" || echo "anthropic: ausente"
  /venv/bin/pytest -m "not integration and not contract and not llm_real" -rs -q -p no:cacheprovider
'
