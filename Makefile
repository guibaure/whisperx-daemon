PYTHON ?= python3
VENV_DIR ?= .venv
VENV_PYTHON := $(VENV_DIR)/bin/python

.PHONY: help venv setup-cpu setup-cuda test lint format format-check typecheck check

help:
	@printf '%s\n' \
		'Available targets:' \
		'  make venv       Create the local virtual environment in .venv' \
		'  make setup-cpu  Install both packages with the CPU development dependencies' \
		'  make setup-cuda Install both packages with the CUDA development dependencies' \
		'  make test       Run the repository test suite against the two source roots' \
		'  make lint       Run Ruff lint checks' \
		'  make format     Apply Ruff lint fixes where safe, then format the repository' \
		'  make format-check Run Ruff formatting checks' \
		'  make typecheck  Run the current mypy scope' \
		'  make check      Run lint, format-check, typecheck, and tests'

venv:
	uv venv $(VENV_DIR)

setup-cpu: venv
	uv pip install --python $(VENV_PYTHON) \
		--index-url https://download.pytorch.org/whl/cpu \
		--extra-index-url https://pypi.org/simple \
		-e "./packages/transcript-postprocess[ner]" -e ".[dev]"

setup-cuda: venv
	uv pip install --python $(VENV_PYTHON) \
		--index-url https://download.pytorch.org/whl/cu128 \
		--extra-index-url https://pypi.org/simple \
		-e "./packages/transcript-postprocess[ner]" -e ".[dev]"

test:
	PYTHONPATH=src:packages/transcript-postprocess/src $(PYTHON) -m unittest discover -s tests -v

lint:
	$(PYTHON) -m ruff check .

format:
	$(PYTHON) -m ruff check . --fix
	$(PYTHON) -m ruff format .

format-check:
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m mypy

check: lint format-check typecheck test
