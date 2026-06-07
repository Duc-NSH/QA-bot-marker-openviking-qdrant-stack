COMPOSE   = docker compose
QUESTION ?= Tổng tài sản của MSB năm 2024 là bao nhiêu?

.PHONY: help dev setup pre-convert up down clean build logs test demo-prep fix-summaries

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

dev: ## Install all workspace dependencies into .venv (run once after clone)
	uv sync --all-extras

setup: ## Generate openviking/ov.conf from template (reads .env or env vars)
	python3 -c "import sys; sys.path.insert(0,'scripts'); exec(open('scripts/pre_convert.py').read()); generate_ov_conf()"

pre-convert: ## Convert PDF on host (full RAM + GPU). Runs setup first.
	uv run --project services/marker python scripts/pre_convert.py

up: ## Start all services (detached)
	$(COMPOSE) up -d

down: ## Stop services, keep volumes
	$(COMPOSE) down

clean: ## Stop services and wipe all volumes (fresh start)
	$(COMPOSE) down -v

build: ## Rebuild Docker images
	$(COMPOSE) build

logs: ## Follow logs for all services
	$(COMPOSE) logs -f

logs-%: ## Follow logs for a specific service  e.g. make logs-api
	$(COMPOSE) logs -f $*

test: ## Run smoke test query against the running stack
	python3 scripts/smoke_test.py "$(QUESTION)"

demo-prep: ## Pre-run demo questions and save to frontend/static/demo_data.json
	uv run python scripts/demo_prep.py

fix-summaries: ## Translate OV L0/L1 summaries to English in-place (stack must be running)
	uv run python scripts/fix_ov_summaries.py
