"""Development-time import shim for the extracted transcript-postprocess package.

The reusable package lives under ``packages/transcript-postprocess/src`` during
monorepo development. This shim keeps plain checkout imports stable before the
package is installed into the active environment.
"""

from __future__ import annotations

from pathlib import Path

_SOURCE_PACKAGE_DIR = (
    Path(__file__).resolve().parent.parent
    / "packages"
    / "transcript-postprocess"
    / "src"
    / "transcript_postprocess"
)

__path__ = [str(_SOURCE_PACKAGE_DIR)]

from .core import (  # noqa: E402
    DEFAULT_PERSON_NER_MODEL,
    PostprocessError,
    build_person_replacement_map,
    build_person_replacement_map_from_fragments,
    load_person_ner_pipeline,
    load_term_replacement_map,
    postprocess_text,
    replace_named_terms,
    replace_person_names,
)

__all__ = [
    "DEFAULT_PERSON_NER_MODEL",
    "PostprocessError",
    "build_person_replacement_map",
    "build_person_replacement_map_from_fragments",
    "load_person_ner_pipeline",
    "load_term_replacement_map",
    "postprocess_text",
    "replace_named_terms",
    "replace_person_names",
]
