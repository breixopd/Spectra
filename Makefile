# Spectra Makefile — developer convenience targets
# All test targets run inside Docker containers.

.PHONY: test test-unit test-integration test-all test-coverage test-compose \
       lint format check clean docker-build docker-up docker-down \
       deploy rollback deploy-check services-up services-down services-logs help

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

deploy: ## Deploy to production (usage: make deploy VERSION=2026.03.12)
	@./scripts/deploy.sh $(VERSION)

rollback: ## Rollback to previous version (usage: make rollback VERSION=2026.03.11)
	@./scripts/rollback.sh $(VERSION)

# --- Microservices Mode ---
services-up: ## Start in microservices mode (split services)
	@docker compose -f docker/docker-compose.yml -f docker/docker-compose.services.yml up -d --build

services-down: ## Stop microservices mode
	@docker compose -f docker/docker-compose.yml -f docker/docker-compose.services.yml down

services-logs: ## Tail logs for all microservices
	@docker compose -f docker/docker-compose.yml -f docker/docker-compose.services.yml logs -f

deploy-check: ## Run pre-deploy checks without deploying
	@echo "Running pre-deploy checks..."
	@docker info > /dev/null 2>&1 || { echo "ERROR: Docker not running"; exit 1; }
	@test -f docker/docker-compose.prod.yml || { echo "ERROR: Prod compose file missing"; exit 1; }
	@test -x scripts/deploy.sh || { echo "ERROR: deploy.sh not executable"; exit 1; }
	@test -x scripts/health_check.sh || { echo "ERROR: health_check.sh not executable"; exit 1; }
	@echo "All pre-deploy checks passed."


