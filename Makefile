# Preferimos o Python do container da API (3.12) por paridade; cai para o que existir (>= 3.12).
PYTHON ?= $(shell command -v python3.12 || command -v python3.13 || command -v python3.14)
VENV   ?= .venv
BIN    := $(VENV)/bin

# O parquet e dado externo (nao vai no repo). O padrao assume o clone do desafio ao lado deste repo.
DATASET_PATH ?= ../namastex-fde-challenge/dataset/conversations.parquet
export DATASET_PATH

.PHONY: help setup test test-integration api-up api-down api-test-up api-test-down chat demo evals evals-api export-log export-logs probe-seed verify-clean analysis-dataset analysis-latency analysis-e2e analysis-cost llm-ping smoke-llm smoke-llm-anthropic smoke-llm-dry

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

chat: ## conversa no terminal (MockLLM, offline). ARGS="--api http://localhost:8100" aponta a API de teste; ARGS="--llm real" usa o modelo do .env (gasta a cota do provedor)
	$(BIN)/python -m autoseguro $(ARGS)

demo: api-test-up ## os quatro cenarios (cotacao, recusa, /quote fora do ar, pedido de humano) com o MockLLM e a API de teste; grava var/scenarios/
	$(BIN)/python tools/scenarios.py

evals: ## os evals: sinteticos de handoff (sempre) + conversas derivadas do dataset (se DATASET_PATH existir), contra o servico vendorizado em processo. Grava evals/results/. Sai com 1 se um criterio quebrar
	$(BIN)/python tools/evals.py $(ARGS)

evals-api: api-test-up ## os mesmos evals, com a /quote e o oraculo na API HTTP de teste (porta 8100)
	$(BIN)/python tools/evals.py --api http://localhost:8100 $(ARGS)

export-log: ## exporta o log de UMA conversa em Markdown (transcricao, decisoes, tentativas da /quote), mascarado e varrido. TRACE=trc_... (ou latest-quoted) DB=var/autoseguro.db OUT=var/log.md
	$(BIN)/python tools/export_log.py --db $(or $(DB),var/autoseguro.db) --trace $(TRACE) --out $(or $(OUT),var/log.md)

export-logs: ## exporta TODAS as conversas do banco: um .md por conversa e um index.md. DB=var/autoseguro.db OUT=var/logs
	$(BIN)/python tools/export_log.py --db $(or $(DB),var/autoseguro.db) --trace all --out $(or $(OUT),var/logs)

delivery-check: ## o minimo da entrega num clone limpo: README coerente, log da execucao real, ai-logs/ varridos, arvore limpa; depois roda make test
	$(BIN)/python tools/delivery_check.py
	$(MAKE) test

ai-logs-list: ## lista as sessoes do Claude Code (id, inicio, fim, mensagens, tamanho, primeiro pedido) para voce escolher quais entram em ai-logs/
	$(BIN)/python tools/export_ai_logs.py --list

ai-logs: ## copia SO as sessoes que voce passar para ai-logs/, redigidas, e refaz o INDEX.md. IDS="id1 id2" [ARGS='--redact "texto"']
	$(BIN)/python tools/export_ai_logs.py $(IDS) $(ARGS)

probe-seed: ## confere uma QUOTE_SEED contra a API que acabou de subir (porta 8000), SEM LLM: SEED=91 [N=8] [PORT=8000]
	$(BIN)/python tools/probe_seed.py --seed $(SEED) --port $(or $(PORT),8000) --n $(or $(N),8)

verify-clean: ## prova num container python:3.12 LIMPO: git archive + pip install do pyproject + testes. REV=HEAD|--worktree  EXTRAS=dev,llm|dev (dev = so o nucleo, sem o SDK da Anthropic)
	tools/verify_clean.sh $(or $(REV),HEAD) $(or $(EXTRAS),dev,llm)

llm-ping: ## preflight de 1 requisicao real: autenticacao, pedido aceito (json_schema + require_parameters), saida valida e latencia da amostra. Rode antes do smoke-llm
	$(BIN)/python tools/llm_ping.py $(ARGS)

smoke-llm: ## mede o LLM real: 15 mensagens escritas a mao, sem PII, 1 modelo, 2 repeticoes = 31 requisicoes, dentro do limite diario que o provedor informa (LLM_API_KEY ou OPENROUTER_API_KEY em .env)
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
