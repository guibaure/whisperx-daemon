# Installation

## Package Manager

This project is managed with [uv](https://docs.astral.sh/uv/). Install `uv`
with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Project Model

Dependency declarations live in `pyproject.toml`; the resolved dependency graph
lives in `uv.lock`.

- `[project].dependencies`: shared runtime dependencies that are safe in every
  local environment.
- `[project.optional-dependencies].cpu`: WhisperX with CPU PyTorch wheels.
- `[project.optional-dependencies].gpu`: WhisperX with CUDA PyTorch wheels.
- `[dependency-groups].dev`: development tools such as `mypy`, `ruff`, and
  `coverage`.
- `[tool.uv].conflicts`: declares `cpu` and `gpu` as mutually exclusive runtime
  extras, because the PyTorch wheel variants cannot coexist in one environment.

Current direct pins:

- `textformer[ner]`
- `torchcodec>=0.7,<0.8`
- `whisperx==3.8.4` through the `cpu` and `gpu` extras
- `torch==2.8.0` through the `cpu` and `gpu` extras
- `torchaudio==2.8.0` through the `cpu` and `gpu` extras

The `torchcodec` upper bound is intentional because the current WhisperX and
PyTorch combination is incompatible with `torchcodec > 0.7`.

CPU and CUDA variants are explicit and mutually exclusive. The selected extra
controls which PyTorch index `uv` uses: the `cpu` extra resolves CPU wheels,
while the `gpu` extra resolves CUDA 12.8 wheels from the PyTorch CUDA index.

## Local CPU Environment

```bash
make setup-cpu
```

Equivalent direct command:

```bash
uv sync --extra cpu --group dev --all-packages
```

## Local CUDA Environment

```bash
make setup-cuda
```

Equivalent direct command:

```bash
uv sync --extra gpu --group dev --all-packages
```

## External Post-Processing Dependency

`textformer` now lives in a separate sibling repository. During
local development, place the two repositories beside each other and point `uv`
at the sibling checkout with an editable source override:

```bash
uv add --editable ../textformer --extra ner
```

The committed configuration keeps the dependency explicit; it is no longer a
workspace member of this repository.
