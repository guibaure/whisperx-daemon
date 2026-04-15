"""Packaging and development-bootstrap regression tests.

These tests verify the repository's intended monorepo contract:

- ``whisperx-daemon`` packages only its own ``src`` tree
- ``transcript-postprocess`` is installed separately during development
- plain repository checkouts still expose stable development-time entrypoints
- first-class project documentation is present and not hidden by ignore rules
"""

from __future__ import annotations

import os
import subprocess
import tomllib
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


class PackagingContractTests(unittest.TestCase):
    """Assert the repository keeps the two-package boundary explicit."""

    def test_root_distribution_packages_only_daemon_source_tree(self) -> None:
        pyproject_payload = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        package_roots = pyproject_payload["tool"]["setuptools"]["packages"]["find"][
            "where"
        ]

        self.assertEqual(package_roots, ["src"])

    def test_development_requirement_files_install_both_packages_editably(self) -> None:
        expected_lines = [
            "-e ./packages/transcript-postprocess[ner]",
            "-e .",
        ]

        for filename in ("requirements-dev-cpu.txt", "requirements-dev-cuda.txt"):
            content = (REPOSITORY_ROOT / filename).read_text(encoding="utf-8")
            for expected_line in expected_lines:
                self.assertIn(expected_line, content, filename)

    def test_project_readmes_exist(self) -> None:
        self.assertTrue((REPOSITORY_ROOT / "README.md").is_file())
        self.assertTrue(
            (
                REPOSITORY_ROOT / "packages" / "transcript-postprocess" / "README.md"
            ).is_file()
        )

    def test_docs_directory_contains_key_guides(self) -> None:
        expected_docs = [
            "getting-started.md",
            "installation.md",
            "usage.md",
            "configuration.md",
            "output.md",
            "post-processing.md",
            "docker.md",
            "architecture.md",
            "troubleshooting.md",
        ]

        for document_name in expected_docs:
            self.assertTrue((REPOSITORY_ROOT / "docs" / document_name).is_file())

    def test_project_readmes_are_not_ignored(self) -> None:
        completed_process = subprocess.run(
            [
                "git",
                "check-ignore",
                "README.md",
                "packages/transcript-postprocess/README.md",
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(completed_process.returncode, 0, completed_process.stdout)

    def test_repository_root_contains_transcript_postprocess_checkout_shim(
        self,
    ) -> None:
        self.assertTrue(
            (REPOSITORY_ROOT / "transcript_postprocess" / "__init__.py").exists()
        )
        self.assertTrue(
            (REPOSITORY_ROOT / "transcript_postprocess" / "__main__.py").exists()
        )

    def test_dockerfile_installs_transcript_postprocess_explicitly(self) -> None:
        dockerfile_text = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn(
            "COPY packages/transcript-postprocess /app/packages/transcript-postprocess",
            dockerfile_text,
        )
        self.assertIn(
            'pip install --no-cache-dir "/app/packages/transcript-postprocess[ner]"',
            dockerfile_text,
        )

    def test_dockerfile_uses_arbitrary_uid_safe_runtime_paths(self) -> None:
        dockerfile_text = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("ENV HOME=/tmp", dockerfile_text)
        self.assertIn("ENV XDG_CACHE_HOME=/tmp/whisperx-cache", dockerfile_text)
        self.assertIn("ENV XDG_CONFIG_HOME=/tmp/whisperx-config", dockerfile_text)
        self.assertIn("ENV MPLCONFIGDIR=/tmp/whisperx-matplotlib", dockerfile_text)
        self.assertIn("mkdir -p /app/runtime", dockerfile_text)
        self.assertIn("chmod 0777 /app/runtime", dockerfile_text)
        self.assertNotIn("mkdir -p /tmp/.cache/huggingface/transformers", dockerfile_text)
        self.assertNotIn("mkdir -p /tmp/.config/matplotlib", dockerfile_text)
        self.assertNotIn("chown -R whisperx:whisperx /app /home/whisperx /tmp", dockerfile_text)

    def test_plain_checkout_cli_help_still_works(self) -> None:
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)

        completed_process = subprocess.run(
            ["python3", "-m", "whisperx_daemon", "--help"],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed_process.returncode, 0, completed_process.stderr)
        self.assertIn("whisperx-daemon", completed_process.stdout)

    def test_plain_checkout_transcript_postprocess_cli_help_still_works(self) -> None:
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)

        completed_process = subprocess.run(
            ["python3", "-m", "transcript_postprocess", "--help"],
            cwd=REPOSITORY_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed_process.returncode, 0, completed_process.stderr)
        self.assertIn("transcript-postprocess", completed_process.stdout)
