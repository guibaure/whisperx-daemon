# Post-Processing

## Speaker Diarisation

Enable diarisation with:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --diarize \
  --hf-token "$HF_TOKEN"
```

Token precedence:

1. `--hf-token`
2. `HF_TOKEN`
3. `HUGGINGFACE_TOKEN`

Optional speaker-count hints:

- `--min-speakers`
- `--max-speakers`

If diarisation is requested without a token, the daemon fails fast.

## Person-Name Pseudonymisation

Enable pseudonymisation with:

```bash
uv run whisperx-daemon \
  --runtime-dir ./runtime \
  --once \
  --pseudonymize-person-names
```

Behaviour:

- uses a Hugging Face token-classification model
- replaces explicit person-name mentions only
- supports full names and, when detected by the model, standalone first names
  and surnames
- assigns deterministic pseudonyms within one document
- leaves timings and speaker labels unchanged
- does not rewrite metadata such as `source_path`

Default model:

- `Davlan/xlm-roberta-base-ner-hrl`

Important limitation:

This is best-effort text transformation, not a formal anonymisation guarantee.

## Proper-Noun Term Replacement

Replacement runs after pseudonymisation and can be enabled by:

- `--term-replacements-file /path/to/file.json`
- or `runtime/term-replacements.json`

Supported JSON formats:

```json
{
  "Boeing": "Test",
  "Boeing Defense": "Test Toto"
}
```

or:

```json
[
  ["Boeing", "Test"],
  ["Boeing Defense", "Test Toto"]
]
```

Behaviour:

- matching is case-insensitive
- longer overlapping matches win
- replacement values are normalised to start with a capital letter
- replacements apply to top-level transcript text and per-segment text

## Standalone Package

The reusable post-processing logic now lives in the sibling
`textformer` repository. Install that repository separately when
you need the standalone CLI or the Python package outside `whisperx-daemon`.

The daemon repository still consumes the package as a normal dependency and
uses the same post-processing behaviour internally.
