# transcript-postprocess

`transcript-postprocess` is a small standalone package for transcript text
sanitisation and controlled proper-noun replacement. It is intentionally kept
independent from `whisperx-daemon` so it can be reused in other workflows and
later moved into its own repository with minimal reshaping.

## What It Does

- person-name pseudonymisation with Hugging Face NER models
- deterministic pseudonym assignment within one document
- configured proper-noun replacement from JSON
- file-based or stdin/stdout CLI usage

## Installation

Term replacement only:

```bash
pip install .
```

Pseudonymisation additionally requires the optional NER dependencies:

```bash
pip install ".[ner]"
```

From this monorepo during development:

```bash
pip install -e ./packages/transcript-postprocess[ner]
```

## CLI Usage

File-based usage:

```bash
python3 -m transcript_postprocess \
  --input-file ./raw.txt \
  --output-file ./sanitised.txt \
  --pseudonymize-person-names \
  --term-replacements-file ./term-replacements.json
```

Pipeline usage:

```bash
cat ./raw.txt | python3 -m transcript_postprocess \
  --pseudonymize-person-names \
  --term-replacements-file ./term-replacements.json
```

## Term-Replacement File Formats

Object form:

```json
{
  "Boeing": "Test",
  "Boeing Defense": "Test Toto",
  "Boeing Defense and Space": "Tata"
}
```

List-of-pairs form:

```json
[
  ["Boeing", "Test"],
  ["Boeing Defense", "Test Toto"],
  ["Boeing Defense and Space", "Tata"]
]
```

Replacement semantics:

- matching is case-insensitive
- longer overlapping matches win over shorter ones
- replacement values are normalised to start with a capital letter

That means `Boeing Defense and Space` is replaced as one term when configured,
rather than being partially rewritten as `Test Toto and Space`.

## Behaviour Notes

Pseudonymisation:

- depends on the configured NER model detecting person entities
- replaces explicit person-name mentions only
- can replace full names and, when detected by the model, standalone first
  names or surnames
- is best-effort text transformation, not a legal anonymisation guarantee

Execution order:

1. person-name pseudonymisation
2. configured proper-noun replacement

## Relationship To whisperx-daemon

`whisperx-daemon` uses this package as a dependency boundary. The daemon owns
audio processing, runtime orchestration, and output generation; this package
owns only reusable text post-processing behaviour.
