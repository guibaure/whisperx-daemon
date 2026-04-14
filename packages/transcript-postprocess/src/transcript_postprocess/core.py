"""Reusable transcript post-processing helpers.

The module is independent of ``whisperx-daemon`` so other workflows can reuse
the same pseudonymisation and term-replacement behaviour.
"""

from __future__ import annotations

import importlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_PERSON_NER_MODEL = "Davlan/xlm-roberta-base-ner-hrl"
PERSON_ENTITY_JOINER_PATTERN = re.compile(r"[ \t'’\-–]*")


class PostprocessError(RuntimeError):
    """Raised when standalone transcript post-processing cannot complete."""


def load_person_ner_pipeline(model_name: str) -> Callable[[str], list[dict[str, Any]]]:
    """Load the configured Hugging Face NER pipeline lazily."""

    try:
        transformers_module = importlib.import_module("transformers")
    except ModuleNotFoundError as exc:
        raise PostprocessError(
            "transformers is not installed. Install the transcript-postprocess "
            "dependency set or disable person-name pseudonymisation."
        ) from exc

    try:
        tokenizer = transformers_module.AutoTokenizer.from_pretrained(
            model_name,
            use_fast=False,
        )
        model = transformers_module.AutoModelForTokenClassification.from_pretrained(
            model_name
        )
    except Exception as exc:
        raise PostprocessError(
            "Unable to load the person-name NER model. Ensure the selected "
            "model is valid and that tokenizer dependencies such as "
            "sentencepiece are installed."
        ) from exc

    return transformers_module.pipeline(
        task="token-classification",
        model=model,
        tokenizer=tokenizer,
        aggregation_strategy="simple",
    )


def postprocess_text(
    text: str,
    pseudonymize_person_names: bool = False,
    person_ner_model: str = DEFAULT_PERSON_NER_MODEL,
    term_replacements_path: Path | None = None,
    person_ner_pipeline_loader: Callable[[str], Callable[[str], list[dict[str, Any]]]]
    | None = None,
) -> str:
    """Apply person-name pseudonymisation and configured term replacement."""

    updated_text = text
    if pseudonymize_person_names:
        loader = person_ner_pipeline_loader or load_person_ner_pipeline
        replacement_map = build_person_replacement_map(
            updated_text,
            loader(person_ner_model),
        )
        updated_text = replace_person_names(updated_text, replacement_map)
    if term_replacements_path is not None:
        updated_text = replace_named_terms(
            updated_text,
            load_term_replacement_map(term_replacements_path),
        )
    return updated_text


def load_term_replacement_map(replacements_path: Path) -> dict[str, str]:
    """Load configured proper-noun replacements from a JSON file."""

    try:
        payload = json.loads(replacements_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PostprocessError(
            f"Term replacements file not found: {replacements_path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise PostprocessError(
            f"Term replacements file is not valid JSON: {replacements_path}"
        ) from exc

    if isinstance(payload, dict):
        return normalise_term_replacement_entries(payload.items(), replacements_path)
    if isinstance(payload, list):
        entries: list[tuple[str, str]] = []
        for item in payload:
            if isinstance(item, list | tuple) and len(item) == 2:
                entries.append((str(item[0]), str(item[1])))
                continue
            raise PostprocessError(
                "Term replacements JSON must be an object or a list of two-item arrays."
            )
        return normalise_term_replacement_entries(entries, replacements_path)

    raise PostprocessError(
        "Term replacements JSON must be an object or a list of two-item arrays."
    )


def normalise_term_replacement_entries(
    entries: Any,
    replacements_path: Path,
) -> dict[str, str]:
    """Validate and normalise raw term-replacement entries."""

    replacement_map: dict[str, str] = {}
    seen_source_terms: set[str] = set()
    for raw_source, raw_replacement in entries:
        source_term = str(raw_source).strip()
        replacement_term = capitalise_proper_noun(str(raw_replacement).strip())
        if not source_term or not replacement_term:
            raise PostprocessError(
                "Term replacements file contains an empty source or "
                f"replacement term: {replacements_path}"
            )
        casefolded_source_term = source_term.casefold()
        if casefolded_source_term in seen_source_terms:
            raise PostprocessError(
                "Term replacements file contains a duplicate source term: "
                f"{source_term}"
            )
        seen_source_terms.add(casefolded_source_term)
        replacement_map[source_term] = replacement_term
    return replacement_map


def capitalise_proper_noun(value: str) -> str:
    """Ensure configured replacement proper nouns start with a capital letter."""

    if not value:
        return value
    return value[0].upper() + value[1:]


def build_person_replacement_map_from_fragments(
    text_fragments: list[str],
    person_ner_pipeline: Callable[[str], list[dict[str, Any]]],
) -> dict[str, str]:
    """Build a stable replacement map from smaller text fragments."""

    detected_person_names: list[str] = []
    seen_names: set[str] = set()
    for fragment in text_fragments:
        for detected_name in iter_detected_person_names(fragment, person_ner_pipeline):
            if detected_name in seen_names:
                continue
            seen_names.add(detected_name)
            detected_person_names.append(detected_name)
    return assign_person_pseudonyms(detected_person_names)


def build_person_replacement_map(
    text: str,
    person_ner_pipeline: Callable[[str], list[dict[str, Any]]],
) -> dict[str, str]:
    """Detect person entities and assign deterministic pseudonyms."""

    if not text.strip():
        return {}
    return assign_person_pseudonyms(
        iter_detected_person_names(text, person_ner_pipeline)
    )


def assign_person_pseudonyms(detected_person_names: list[str]) -> dict[str, str]:
    """Assign deterministic pseudonyms to already-detected person names."""

    replacement_map: dict[str, str] = {}
    full_name_map: dict[str, str] = {}
    standalone_names: list[str] = []

    next_pseudonym_index = 0
    for detected_name in detected_person_names:
        if len(detected_name.split()) >= 2:
            if detected_name in full_name_map:
                continue
            full_name_map[detected_name] = build_pseudonym(next_pseudonym_index)
            next_pseudonym_index += 1
            continue
        if detected_name not in standalone_names:
            standalone_names.append(detected_name)

    replacement_map.update(full_name_map)
    replacement_map.update(build_person_alias_map(full_name_map))
    replacement_map.update(
        build_standalone_person_name_map(
            standalone_names, full_name_map, replacement_map
        )
    )
    return replacement_map


def iter_detected_person_names(
    text: str,
    person_ner_pipeline: Callable[[str], list[dict[str, Any]]],
) -> list[str]:
    """Return normalised person-entity strings in first-appearance order."""

    detected_names: list[str] = []
    seen_names: set[str] = set()
    for original_name in iter_person_name_candidates(text, person_ner_pipeline(text)):
        if not original_name or original_name in seen_names:
            continue
        seen_names.add(original_name)
        detected_names.append(original_name)
    return detected_names


def iter_person_name_candidates(
    text: str,
    entities: list[dict[str, Any]],
) -> list[str]:
    """Return person-name candidates in pipeline order."""

    detected_names: list[str] = []
    entity_index = 0
    while entity_index < len(entities):
        entity = entities[entity_index]
        entity_group = str(
            entity.get("entity_group") or entity.get("entity") or ""
        ).upper()
        if entity_group not in {"PER", "PERSON"}:
            entity_index += 1
            continue

        name, next_index = extract_person_name_candidate(text, entities, entity_index)
        if name:
            detected_names.append(name)
        entity_index = next_index
    return detected_names


def extract_person_name_candidate(
    text: str,
    entities: list[dict[str, Any]],
    start_index: int,
) -> tuple[str, int]:
    """Extract one normalised person-name candidate from the entity stream."""

    entity = entities[start_index]
    start_offset, end_offset = parse_entity_span(entity, len(text))
    if start_offset is None or end_offset is None:
        return normalise_person_name(str(entity.get("word", ""))), start_index + 1

    merged_start = start_offset
    merged_end = end_offset
    next_index = start_index + 1
    while next_index < len(entities):
        next_entity = entities[next_index]
        next_group = str(
            next_entity.get("entity_group") or next_entity.get("entity") or ""
        ).upper()
        if next_group not in {"PER", "PERSON"}:
            break

        next_start, next_end = parse_entity_span(next_entity, len(text))
        if next_start is None or next_end is None:
            break
        if next_start < merged_end:
            merged_end = max(merged_end, next_end)
            next_index += 1
            continue

        separator = text[merged_end:next_start]
        if not PERSON_ENTITY_JOINER_PATTERN.fullmatch(separator):
            break
        merged_end = next_end
        next_index += 1

    return normalise_person_name(text[merged_start:merged_end]), next_index


def parse_entity_span(
    entity: dict[str, Any], text_length: int
) -> tuple[int | None, int | None]:
    """Return a validated entity span or ``(None, None)`` when unavailable."""

    start = entity.get("start")
    end = entity.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return None, None
    if start < 0 or end <= start or end > text_length:
        return None, None
    return start, end


def build_person_alias_map(full_name_map: dict[str, str]) -> dict[str, str]:
    """Derive safe single-token aliases from full-name replacements."""

    alias_candidates: dict[str, set[str]] = {}
    for original_name in full_name_map:
        for alias in iter_person_alias_tokens(original_name):
            alias_candidates.setdefault(alias, set()).add(original_name)

    alias_map: dict[str, str] = {}
    next_fallback_index = 0
    for alias, original_names in alias_candidates.items():
        if len(original_names) == 1:
            original_name = next(iter(original_names))
            pseudonym = full_name_map[original_name]
            pseudonym_alias = build_pseudonym_alias(alias, original_name, pseudonym)
            if pseudonym_alias:
                alias_map[alias] = pseudonym_alias
            continue
        alias_map[alias] = build_single_token_pseudonym(next_fallback_index)
        next_fallback_index += 1
    return alias_map


def build_standalone_person_name_map(
    standalone_names: list[str],
    full_name_map: dict[str, str],
    existing_replacement_map: dict[str, str],
) -> dict[str, str]:
    """Assign single-token pseudonyms to standalone detected person names."""

    if not standalone_names:
        return {}

    alias_owners: dict[str, set[str]] = {}
    for original_name in full_name_map:
        for alias in iter_person_alias_tokens(original_name):
            alias_owners.setdefault(alias, set()).add(original_name)

    standalone_map: dict[str, str] = {}
    next_fallback_index = 0
    for standalone_name in standalone_names:
        if (
            standalone_name in existing_replacement_map
            or standalone_name in standalone_map
        ):
            continue
        original_names = alias_owners.get(standalone_name, set())
        if len(original_names) == 1:
            original_name = next(iter(original_names))
            pseudonym = full_name_map[original_name]
            pseudonym_alias = build_pseudonym_alias(
                standalone_name, original_name, pseudonym
            )
            if pseudonym_alias:
                standalone_map[standalone_name] = pseudonym_alias
                continue
        standalone_map[standalone_name] = build_single_token_pseudonym(
            next_fallback_index
        )
        next_fallback_index += 1
    return standalone_map


def iter_person_alias_tokens(full_name: str) -> tuple[str, ...]:
    """Return the single-token aliases worth considering for a person name."""

    parts = full_name.split()
    if len(parts) < 2:
        return tuple()
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], parts[-1]


def build_pseudonym_alias(alias: str, original_name: str, pseudonym: str) -> str | None:
    """Map a detected alias token onto the matching pseudonym token."""

    original_parts = original_name.split()
    pseudonym_parts = pseudonym.split()
    if len(original_parts) < 2 or len(pseudonym_parts) < 2:
        return None
    if alias == original_parts[0]:
        return pseudonym_parts[0]
    if alias == original_parts[-1]:
        return pseudonym_parts[-1]
    return None


def normalise_person_name(value: str) -> str:
    """Normalise a detected person name into a replacement-map key."""

    return re.sub(r"\s+", " ", value.replace("##", "")).strip()


def build_pseudonym(index: int) -> str:
    """Return a deterministic pseudonym for a detected person entity."""

    first_names = [
        "Alice",
        "Benjamin",
        "Clara",
        "Daniel",
        "Elena",
        "Felix",
        "Grace",
        "Henry",
        "Isabelle",
        "Julian",
        "Katherine",
        "Lucas",
        "Maya",
        "Nathan",
        "Olivia",
        "Peter",
        "Quinn",
        "Rachel",
        "Samuel",
        "Tessa",
    ]
    last_names = [
        "Archer",
        "Bennett",
        "Carter",
        "Donovan",
        "Ellis",
        "Foster",
        "Griffin",
        "Hayes",
        "Iverson",
        "Jensen",
        "Keller",
        "Lawson",
        "Mitchell",
        "Norris",
        "Owens",
        "Parker",
        "Quincy",
        "Reed",
        "Sawyer",
        "Turner",
    ]
    if index < len(first_names):
        return f"{first_names[index]} {last_names[index]}"
    return f"Alias Person {index + 1}"


def build_single_token_pseudonym(index: int) -> str:
    """Return a deterministic one-token pseudonym for short name mentions."""

    alias_names = [
        "Avery",
        "Blake",
        "Cameron",
        "Devon",
        "Emerson",
        "Finley",
        "Harper",
        "Jordan",
        "Morgan",
        "Parker",
        "Reese",
        "Rowan",
        "Sawyer",
        "Taylor",
        "Sydney",
    ]
    if index < len(alias_names):
        return alias_names[index]
    return f"Alias{index + 1}"


def replace_person_names(text: str, replacement_map: dict[str, str]) -> str:
    """Replace known person names in text."""

    return replace_named_terms(text, replacement_map)


def replace_named_terms(text: str, replacement_map: dict[str, str]) -> str:
    """Replace configured terms with longest-match, case-tolerant semantics."""

    if not replacement_map:
        return text

    casefolded_replacements = {
        source_term.casefold(): replacement_term
        for source_term, replacement_term in replacement_map.items()
    }
    ordered_source_terms = sorted(
        replacement_map,
        key=lambda term: (-len(term.split()), -len(term), term.casefold()),
    )
    pattern = re.compile(
        (
            rf"(?<!\w)(?:{'|'.join(re.escape(term) for term in ordered_source_terms)})"
            r"(?!\w)"
        ),
        flags=re.IGNORECASE,
    )

    def _replace_match(match: re.Match[str]) -> str:
        return casefolded_replacements[match.group(0).casefold()]

    return pattern.sub(_replace_match, text)
