.DEFAULT_GOAL := check

.PHONY: install lint lint-fix format type-check test test-cov check clean

install:
	poetry install --with dev

lint:
	poetry run ruff check .
	poetry run ruff format --check .

lint-fix:
	poetry run ruff check --fix .
	poetry run ruff format .

format:
	poetry run ruff format .

type-check:
	poetry run mypy zamp_sdk

test:
	poetry run pytest

test-cov:
	poetry run pytest --cov=zamp_sdk --cov-report=xml --cov-report=term-missing

check: lint type-check test

clean:
	rm -rf .mypy_cache .pytest_cache .ruff_cache coverage.xml dist build *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
