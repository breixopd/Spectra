# Spectra Makefile — developer convenience targets
# All test targets run inside Docker containers.

.PHONY: test test-unit test-integration test-all test-coverage test-compose help

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
