.PHONY: help check check-attribution install-hooks test lint format

help: ## Show available targets.
	@awk 'BEGIN{FS=":.*##"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-10s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

check: check-attribution ## Everything CI runs. Run before pushing.
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	uv run pytest -q --doctest-modules src tests

check-attribution: ## No commit may claim a machine wrote it, and the hooks must be live.
	@# A repository should not get weaker process by being split out of one
	@# that had it. This package was a directory in a repository whose
	@# `make check` enforced all of this; the guards came with it.
	@echo "==> checking the attribution guard rejects what it claims to"
	@sh scripts/attribution_guard_test.sh | tail -1
	@echo "==> checking no commit claims a machine wrote it"
	@sh scripts/check_attribution.sh
	@echo "==> checking the hooks still contain the gates they claim to"
	@sh scripts/check_hooks.sh

install-hooks: ## Point git at .githooks. Needed once per clone.
	@git config core.hooksPath .githooks
	@chmod +x .githooks/* scripts/*.sh
	@echo "    hooks installed - commit-msg rejects attribution; pre-push"
	@echo "    rejects attribution and refuses any direct push to master"

test: ## Tests and doctests only.
	uv run pytest -q --doctest-modules src tests

lint: ## Lint and type-check only.
	uv run ruff check .
	uv run mypy

format: ## Apply formatting.
	uv run ruff format .
