.PHONY: install lint format typecheck test check run data data-adversarial db-up eval-rules eval-xml eval-llm eval-agent eval-agent-llm eval-injection eval-injection-llm mcp docker-build docker-run

install:        ## Install the package with dev and synth extras (editable)
	pip install -e ".[dev]"

lint:           ## Ruff lint + format check
	ruff check .
	ruff format --check .

format:         ## Auto-format and auto-fix
	ruff format .
	ruff check . --fix

typecheck:      ## mypy in strict mode
	mypy src

test:           ## Run the test suite with coverage
	pytest --cov=belegfluss --cov-report=term-missing

check: lint typecheck test   ## Everything CI runs

run:            ## Start the API with auto-reload on http://localhost:8000/docs
	uvicorn belegfluss.api.main:app --reload

data:           ## Generate the synthetic dataset (200 sets) into data/synthetic
	belegfluss-synth --sets 200 --seed 42 --out data/synthetic --force

eval-rules:     ## Rule-based checks on ground-truth documents (no API key needed)
	belegfluss-eval checks --data data/synthetic --source ground-truth

eval-xml:       ## Extraction of XRechnung / ZUGFeRD invoices only (no API key needed)
	belegfluss-eval extraction --data data/synthetic --limit 200 --no-llm

eval-llm:       ## Full extraction incl. PDFs and scans (needs OPENAI_API_KEY; costs money)
	belegfluss-eval extraction --data data/synthetic --limit 20
	belegfluss-eval checks --data data/synthetic --source extracted

data-adversarial: ## 60 sets, every one with a planted prompt-injection attack, in data/adversarial
	belegfluss-synth --sets 60 --seed 7 --out data/adversarial --adversarial 1.0 --force

db-up:          ## Start PostgreSQL with pgvector (docker compose)
	docker compose up -d postgres

eval-agent:     ## Matching agent with the deterministic adjudicator (free)
	belegfluss-eval agent --data data/synthetic

eval-agent-llm: ## Matching agent with the LLM adjudicator and OpenAI embeddings (costs money)
	belegfluss-eval agent --data data/synthetic --adjudicator llm --embedder openai

eval-injection: ## Screening on the adversarial set (free)
	belegfluss-eval injection --data data/adversarial --no-llm

eval-injection-llm: ## Does an attack change what the LLM extracts? (costs money)
	belegfluss-eval injection --data data/adversarial

mcp:            ## Run the read-only MCP server on stdio
	belegfluss-mcp

docker-build:
	docker build -t belegfluss:dev .

docker-run:
	docker run --rm -p 8000:8000 belegfluss:dev
