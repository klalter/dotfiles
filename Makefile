# Makefile — convenience entrypoints for the devbox workflow.
# Everything here just shells out to the scripts under devbox/ and tests/, so
# the Makefile is optional sugar; the scripts work standalone on any host.
.DEFAULT_GOAL := help
SHELL := /usr/bin/env bash

.PHONY: help bootstrap build up shell doctor status down test test-unit test-integration

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Install Docker on this (fresh Ubuntu) host — idempotent
	./devbox/bootstrap.sh

build: ## Build the devbox image
	./devbox/devbox.sh build

up: ## Start the ephemeral devbox in the background
	./devbox/devbox.sh up

shell: ## Open a shell inside the running devbox
	./devbox/devbox.sh shell

doctor: ## Run the in-container selftest (DinD + browser)
	./devbox/devbox.sh doctor

status: ## Show devbox status
	./devbox/devbox.sh status

down: ## Tear the devbox down and remove its volumes
	./devbox/devbox.sh down

test: ## Run the full deterministic test suite (integration self-skips without Docker)
	./tests/run.sh

test-unit: ## Run only the fast, Docker-free tiers
	./tests/run.sh --no-integration

test-integration: ## Run the full suite and FAIL if Docker is unavailable
	./tests/run.sh --require-integration
