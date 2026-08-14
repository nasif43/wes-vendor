.PHONY: dev test test-int lint typecheck migrate seed build clean install

install:
	pip install -r requirements.txt
	pip install -e ".[dev]"

dev:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest tests/unit/ -v --tb=short

test-int:
	pytest tests/integration/ -v --tb=short

test-all:
	pytest tests/ -v --tb=short

lint:
	ruff check app/ tests/

lint-fix:
	ruff check --fix app/ tests/

typecheck:
	mypy app/

migrate:
	alembic upgrade head

migrate-new:
	alembic revision --autogenerate -m "$(msg)"

seed:
	python -m scripts.seed

build:
	pip install -r requirements.txt

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
