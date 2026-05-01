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

    def test_pyproject_declares_common_dependencies(self) -> None:
        pyproject_payload = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        dependencies = pyproject_payload["project"]["dependencies"]
        dep_text = " ".join(dependencies)

        for expected in ("transcript-postprocess", "torchcodec"):
            self.assertIn(expected, dep_text)

    def test_pyproject_declares_cpu_and_gpu_extras(self) -> None:
        pyproject_payload = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        extras = pyproject_payload["project"]["optional-dependencies"]

        for group in ("cpu", "gpu"):
            group_text = " ".join(extras[group])
            self.assertIn("whisperx", group_text)
            self.assertIn("torch", group_text)
            self.assertIn("torchaudio", group_text)

    def test_pyproject_declares_dev_dependency_group(self) -> None:
        pyproject_payload = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        dev_deps = pyproject_payload["dependency-groups"]["dev"]
        dev_text = " ".join(dev_deps)

        self.assertIn("mypy", dev_text)
        self.assertIn("ruff", dev_text)

    def test_pyproject_declares_uv_workspace(self) -> None:
        pyproject_payload = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertEqual(
            pyproject_payload["tool"]["uv"]["workspace"]["members"],
            ["packages/transcript-postprocess"],
        )
        self.assertEqual(
            pyproject_payload["tool"]["uv"]["sources"]["transcript-postprocess"],
            {"workspace": True},
        )
        self.assertEqual(
            pyproject_payload["tool"]["uv"]["sources"]["torch"],
            [
                {"index": "pytorch-cpu", "extra": "cpu"},
                {"index": "pytorch-gpu", "extra": "gpu"},
            ],
        )
        self.assertEqual(
            pyproject_payload["tool"]["uv"]["sources"]["torchaudio"],
            [
                {"index": "pytorch-cpu", "extra": "cpu"},
                {"index": "pytorch-gpu", "extra": "gpu"},
            ],
        )
        self.assertEqual(
            pyproject_payload["tool"]["uv"]["conflicts"],
            [[{"extra": "cpu"}, {"extra": "gpu"}]],
        )

    def test_uv_lock_exists(self) -> None:
        self.assertTrue((REPOSITORY_ROOT / "uv.lock").is_file())

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
        self.assertIn("COPY pyproject.toml uv.lock README.md /app/", dockerfile_text)
        self.assertIn(
            "uv sync --frozen --extra gpu --no-dev --all-packages",
            dockerfile_text,
        )
        self.assertIn("--no-install-workspace", dockerfile_text)
        self.assertIn("--no-editable", dockerfile_text)

    def test_dockerfile_uses_arbitrary_uid_safe_runtime_paths(self) -> None:
        dockerfile_text = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint_text = (REPOSITORY_ROOT / "docker" / "entrypoint.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "COPY docker/entrypoint.sh /usr/local/bin/whisperx-daemon-entrypoint",
            dockerfile_text,
        )
        self.assertIn(
            'ENTRYPOINT ["/usr/local/bin/whisperx-daemon-entrypoint"]',
            dockerfile_text,
        )
        self.assertIn("mkdir -p /app/runtime", dockerfile_text)
        self.assertIn("chmod 0777 /app/runtime", dockerfile_text)
        for unexpected_snippet in (
            "ENV XDG_CACHE_HOME=",
            "ENV XDG_CONFIG_HOME=",
            "ENV HF_HOME=",
            "ENV TRANSFORMERS_CACHE=",
            "ENV MPLCONFIGDIR=",
            "mkdir -p /tmp/.cache/huggingface/transformers",
            "mkdir -p /tmp/.config/matplotlib",
            "chown -R whisperx:whisperx /app /home/whisperx /tmp",
        ):
            self.assertNotIn(unexpected_snippet, dockerfile_text)
        self.assertIn(
            "container_state_dir=${WHISPERX_DAEMON_CONTAINER_STATE_DIR:-${runtime_dir}/.container-state}",
            entrypoint_text,
        )
        self.assertIn(
            "export HOME=${WHISPERX_DAEMON_HOME:-${container_state_dir}/home}",
            entrypoint_text,
        )
        self.assertIn(
            "export XDG_CACHE_HOME=${XDG_CACHE_HOME:-${container_state_dir}/cache}",
            entrypoint_text,
        )
        self.assertIn(
            "export XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-${container_state_dir}/config}",
            entrypoint_text,
        )
        self.assertIn(
            "export HF_HOME=${HF_HOME:-${container_state_dir}/huggingface}",
            entrypoint_text,
        )
        self.assertIn(
            "export TORCH_HOME=${TORCH_HOME:-${XDG_CACHE_HOME}/torch}",
            entrypoint_text,
        )
        self.assertIn(
            "export MPLCONFIGDIR=${MPLCONFIGDIR:-${container_state_dir}/matplotlib}",
            entrypoint_text,
        )

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
