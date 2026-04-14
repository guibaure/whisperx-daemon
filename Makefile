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
	$(PYTHON) -m venv $(VENV_DIR)

setup-cpu: venv
	$(VENV_PYTHON) -m pip install -r requirements-dev-cpu.txt

setup-cuda: venv
	$(VENV_PYTHON) -m pip install -r requirements-dev-cuda.txt

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
