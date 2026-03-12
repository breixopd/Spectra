# Spectra Makefile — developer convenience targets
# All test targets run inside Docker containers.

.PHONY: test test-unit test-integration test-all test-coverage test-compose \
       lint format check clean docker-build docker-up docker-down help \
       type-check security audit format-check

SHELL := /bin/bash

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

test: test-unit ## Run unit tests (default)

test-unit: ## Run unit tests in Docker
	@./scripts/test.sh unit

test-integration: ## Run integration tests in Docker
	@./scripts/test.sh integration

test-all: ## Run all tests (unit + integration) in Docker
	@./scripts/test.sh all

test-coverage: ## Run unit tests with coverage report
	@./scripts/test.sh coverage

test-compose: ## Run full test stack via docker-compose
	@./scripts/test.sh compose

lint: ## Run ruff linter on app/
	@ruff check app/

format: ## Format code with ruff
	@ruff format app/ tests/

check: lint test-unit ## Run lint + unit tests in sequence

clean: ## Clean caches and build artifacts
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name '*.pyc' -delete 2>/dev/null || true
	@rm -rf reports/coverage htmlcov .coverage 2>/dev/null || true
	@echo "Cleaned."

docker-build: ## Build Docker images
	@docker compose -f docker/docker-compose.yml build

docker-up: ## Start Docker Compose services
	@docker compose -f docker/docker-compose.yml up -d

docker-down: ## Stop Docker Compose services
	@docker compose -f docker/docker-compose.yml down

type-check: ## Run type checks with pyright
	@echo "Running type checks..."
	pyright app/ --pythonversion 3.11

security: ## Run security scan with bandit
	@echo "Running security scan..."
	bandit -r app/ -c pyproject.toml

audit: ## Run dependency audit
	@echo "Running dependency audit..."
	pip-audit -r requirements-app.txt

format-check: ## Check code formatting
	@echo "Checking code formatting..."
	ruff format --check app/ tests/
