# Preferimos o Python do container da API (3.12) por paridade; cai para o que existir (>= 3.12).
PYTHON ?= $(shell command -v python3.12 || command -v python3.13 || command -v python3.14)
VENV   ?= .venv
BIN    := $(VENV)/bin

# O parquet e dado externo (nao vai no repo). O padrao assume o clone do desafio ao lado deste repo.
DATASET_PATH ?= ../namastex-fde-challenge/dataset/conversations.parquet
export DATASET_PATH

.PHONY: help setup test test-integration api-up api-down api-test-up api-test-down analysis-dataset analysis-latency analysis-e2e analysis-cost llm-ping smoke-llm smoke-llm-anthropic smoke-llm-dry

help: ## lista os alvos
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/'

setup: ## cria o venv e instala dev + analysis
	@test -n "$(PYTHON)" || (echo "precisa de Python >= 3.12"; exit 1)
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q -e ".[dev,analysis,llm]"

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

llm-ping: ## preflight de 1 requisicao real: autenticacao, pedido aceito (json_schema + require_parameters), saida valida e latencia da amostra. Rode antes do smoke-llm
	$(BIN)/python tools/llm_ping.py $(ARGS)

smoke-llm: ## mede o LLM real: 15 mensagens escritas a mao, sem PII, 1 modelo, 2 repeticoes = 31 de 50 requisicoes/dia do free tier (LLM_API_KEY ou OPENROUTER_API_KEY em .env)
	$(BIN)/python tools/smoke_llm.py $(ARGS)

smoke-llm-anthropic: ## o mesmo smoke pela API direta da Anthropic (ClaudeLLM). Opcional: instala o SDK e precisa de LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY
	$(BIN)/pip install -q -e ".[llm]"
	LLM_PROVIDER=anthropic $(BIN)/python tools/smoke_llm.py $(ARGS)

smoke-llm-dry: ## o mesmo encanamento com um LLM de mentira: sem chave e sem rede
	$(BIN)/python tools/smoke_llm.py --dry-run $(ARGS)

analysis-dataset: ## perfil agregado do dataset -> analysis/results/dataset_profile.json
	$(BIN)/python -I analysis/dataset_profile.py --parquet $(DATASET_PATH) --out analysis/results/dataset_profile.json

analysis-latency: ## simulacao das politicas de cliente -> analysis/results/latency_sim.{json,md}
	$(BIN)/python -I analysis/latency_sim.py --out analysis/results

analysis-e2e: ## latencia fim a fim (LLM + /quote); a latencia do LLM e hipotese -> analysis/results/e2e_latency_sim.{json,md}
	$(BIN)/python -I analysis/e2e_latency_sim.py --out analysis/results

analysis-cost: ## custo por conversa (tokens estimados, precos da skill claude-api) -> analysis/results/cost_model.{json,md}
	$(BIN)/python -I analysis/cost_model.py --out analysis/results
