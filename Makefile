.PHONY: install lint format typecheck test check run data docker-build docker-run

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

docker-build:
	docker build -t belegfluss:dev .

docker-run:
	docker run --rm -p 8000:8000 belegfluss:dev
