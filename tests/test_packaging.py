"""Packaging and dependency-boundary regression tests."""

from __future__ import annotations

import subprocess
import tomllib
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


class PackagingContractTests(unittest.TestCase):
    """Assert the daemon repository keeps the extracted-package boundary explicit."""

    def test_root_distribution_packages_only_daemon_source_tree(self) -> None:
        pyproject_payload = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        package_roots = pyproject_payload["tool"]["setuptools"]["packages"]["find"][
            "where"
        ]

        self.assertEqual(package_roots, ["src"])

    def test_pyproject_declares_daemon_runtime_dependencies(self) -> None:
        pyproject_payload = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        dependencies = pyproject_payload["project"]["dependencies"]
        dep_text = " ".join(dependencies)

        self.assertIn("transcript-postprocess[ner]", dep_text)
        self.assertIn("torchcodec", dep_text)

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

        self.assertIn("coverage", dev_text)
        self.assertIn("mypy", dev_text)
        self.assertIn("ruff", dev_text)

    def test_pyproject_no_longer_declares_workspace_membership(self) -> None:
        pyproject_payload = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        self.assertNotIn("workspace", pyproject_payload.get("tool", {}).get("uv", {}))
        self.assertEqual(
            pyproject_payload["tool"]["uv"]["sources"]["transcript-postprocess"],
            {"path": "../transcript-postprocess"},
        )

    def test_mypy_scope_targets_daemon_modules_only(self) -> None:
        pyproject_payload = tomllib.loads(
            (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )

        mypy_files = pyproject_payload["tool"]["mypy"]["files"]

        self.assertIn("src/whisperx_daemon/pipeline.py", mypy_files)
        self.assertNotIn("packages/transcript-postprocess", " ".join(mypy_files))

    def test_makefile_declares_coverage_target(self) -> None:
        makefile_text = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn("coverage:", makefile_text)
        self.assertIn("coverage run -m unittest discover -s tests -v", makefile_text)
        self.assertIn("coverage report", makefile_text)
        self.assertIn(
            "PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v",
            makefile_text,
        )

    def test_makefile_declares_docker_smoke_target(self) -> None:
        makefile_text = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
        smoke_script_text = (
            REPOSITORY_ROOT / "scripts" / "docker-smoke-test.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("docker-smoke:", makefile_text)
        self.assertIn("sh scripts/docker-smoke-test.sh", makefile_text)
        self.assertIn("whisperx-daemon:test", smoke_script_text)
        self.assertIn('docker build -t "$IMAGE_TAG"', smoke_script_text)
        self.assertIn('docker image rm "$IMAGE_TAG"', smoke_script_text)
        self.assertIn("--entrypoint nvidia-smi", smoke_script_text)
        self.assertIn("NVIDIA_VISIBLE_DEVICES", smoke_script_text)
        self.assertIn("PyTorch CUDA unavailable", smoke_script_text)

    def test_uv_lock_exists(self) -> None:
        self.assertTrue((REPOSITORY_ROOT / "uv.lock").is_file())

    def test_project_readmes_exist(self) -> None:
        self.assertTrue((REPOSITORY_ROOT / "README.md").is_file())
        self.assertTrue((REPOSITORY_ROOT / "docs" / "post-processing.md").is_file())

    def test_project_readmes_are_not_ignored(self) -> None:
        completed_process = subprocess.run(
            [
                "git",
                "check-ignore",
                "README.md",
                "docs/post-processing.md",
            ],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(completed_process.returncode, 0, completed_process.stdout)

    def test_repository_root_no_longer_contains_package_shim(self) -> None:
        self.assertFalse((REPOSITORY_ROOT / "transcript_postprocess").exists())
        self.assertFalse(
            (REPOSITORY_ROOT / "packages" / "transcript-postprocess").exists()
        )

    def test_dockerfile_no_longer_copies_package_tree(self) -> None:
        dockerfile_text = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("COPY pyproject.toml uv.lock README.md /app/", dockerfile_text)
        self.assertNotIn(
            "COPY packages/transcript-postprocess /app/packages/transcript-postprocess",
            dockerfile_text,
        )
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
