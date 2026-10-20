# Preferimos o Python do container da API (3.12) por paridade; cai para o que existir (>= 3.12).
PYTHON ?= $(shell command -v python3.12 || command -v python3.13 || command -v python3.14)
VENV   ?= .venv
BIN    := $(VENV)/bin

# O parquet e dado externo (nao vai no repo). O padrao assume o clone do desafio ao lado deste repo.
DATASET_PATH ?= ../namastex-fde-challenge/dataset/conversations.parquet
export DATASET_PATH

.PHONY: help setup test test-integration api-up api-down api-test-up api-test-down analysis-dataset analysis-latency analysis-e2e analysis-cost

help: ## lista os alvos
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

setup: ## cria o venv e instala dev + analysis
	@test -n "$(PYTHON)" || (echo "precisa de Python >= 3.12"; exit 1)
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q -e ".[dev,analysis]"

test: ## testes unitarios e de higiene (nao precisam da API; a checagem do dataset roda se DATASET_PATH existir)
	$(BIN)/pytest -m "not integration and not contract and not llm_real"

test-integration: api-test-up ## sobe a API de teste (porta 8100, sem falhas) e roda os testes que a usam
	$(BIN)/pytest -m "integration or contract"

api-up: ## API com a instabilidade padrao do desafio (porta 8000)
	docker compose up --build -d --wait

api-down:
	docker compose down

api-test-up: ## API deterministica para testes (porta 8100, falha e lentidao zeradas)
	docker compose -f docker-compose.test.yml up --build -d --wait

api-test-down:
	docker compose -f docker-compose.test.yml down

analysis-dataset: ## perfil agregado do dataset -> analysis/results/dataset_profile.json
	$(BIN)/python -I analysis/dataset_profile.py --parquet $(DATASET_PATH) --out analysis/results/dataset_profile.json

analysis-latency: ## simulacao das politicas de cliente -> analysis/results/latency_sim.{json,md}
	$(BIN)/python -I analysis/latency_sim.py --out analysis/results

analysis-e2e: ## latencia fim a fim (LLM + /quote); a latencia do LLM e hipotese -> analysis/results/e2e_latency_sim.{json,md}
	$(BIN)/python -I analysis/e2e_latency_sim.py --out analysis/results

analysis-cost: ## custo por conversa (tokens estimados, precos da skill claude-api) -> analysis/results/cost_model.{json,md}
	$(BIN)/python -I analysis/cost_model.py --out analysis/results
