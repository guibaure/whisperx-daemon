PYTHON ?= uv run python
VENV_DIR ?= .venv
UV_CACHE_DIR ?= $(CURDIR)/.uv-cache
UV_LINK_MODE ?= copy

export UV_CACHE_DIR
export UV_LINK_MODE

.PHONY: help sync-cpu sync-cuda setup-cpu setup-cuda test lint format format-check typecheck check

help:
	@printf '%s\n' \
		'Available targets:' \
		'  make sync-cpu   Synchronise the uv environment with CPU dependencies' \
		'  make sync-cuda  Synchronise the uv environment with CUDA dependencies' \
		'  make setup-cpu  Alias for make sync-cpu' \
		'  make setup-cuda Alias for make sync-cuda' \
		'  make test       Run the repository test suite against the two source roots' \
		'  make lint       Run Ruff lint checks' \
		'  make format     Apply Ruff lint fixes where safe, then format the repository' \
		'  make format-check Run Ruff formatting checks' \
		'  make typecheck  Run the current mypy scope' \
		'  make check      Run lint, format-check, typecheck, and tests'

sync-cpu:
	uv sync --extra cpu --group dev --all-packages

sync-cuda:
	uv sync --extra gpu --group dev --all-packages

setup-cpu: sync-cpu

setup-cuda: sync-cuda

test:
	PYTHONPATH=src:packages/transcript-postprocess/src $(PYTHON) -m unittest discover -s tests -v

lint:
	uv run --group dev ruff check .

format:
	uv run --group dev ruff check . --fix
	uv run --group dev ruff format .

format-check:
	uv run --group dev ruff format --check .

typecheck:
	uv run --group dev mypy

check: lint format-check typecheck test
