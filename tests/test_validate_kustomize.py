from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/validate_kustomize.py"


class ValidateKustomizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")
        self.manifest("applications/example")
        self.command("kustomize", "echo build >> calls\nprintf 'apiVersion: v1\\nkind: ConfigMap\\n'\n")
        self.command("kubeconform", "echo schema >> calls\ntest -s \"$1\"\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def manifest(self, directory: str, kind: str = "Kustomization") -> None:
        path = self.root / directory
        path.mkdir(parents=True)
        (path / "kustomization.yaml").write_text(f"kind: {kind}\n")

    def command(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/bin/sh\n{body}")
        path.chmod(0o755)

    def run_validation(self, *flags: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *flags], cwd=self.root,
            env=self.env, capture_output=True, text=True, check=False,
        )

    def test_failed_build_fails_gate_and_never_runs_schema_validation(self) -> None:
        self.command("kustomize", "echo build >> calls\necho render-failed >&2\nexit 9\n")
        result = self.run_validation("--schemas")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("render-failed", result.stderr)
        self.assertEqual((self.root / "calls").read_text(), "build\n")

    def test_schema_validation_uses_one_successful_render(self) -> None:
        result = self.run_validation("--schemas")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "calls").read_text(), "build\nschema\n")

    def test_failed_schema_validation_fails_gate(self) -> None:
        self.command("kubeconform", "exit 2\n")
        result = self.run_validation("--schemas")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAIL schemas: applications/example", result.stderr)

    def test_archives_caches_and_components_are_not_standalone_builds(self) -> None:
        self.manifest("archive/applications/retired")
        self.manifest("applications/example/charts/vendored")
        self.manifest(".venv/package")
        self.manifest(".cache/baseline")
        self.manifest("groups/all", "Component")
        result = self.run_validation()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "calls").read_text(), "build\n")

    def test_empty_repository_fails_instead_of_reporting_success(self) -> None:
        (self.root / "applications/example/kustomization.yaml").unlink()
        result = self.run_validation()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No Kustomizations found", result.stderr)

    def test_inactive_workloads_still_build_and_validate_schemas(self) -> None:
        self.manifest("inactive/applications/dormant")
        result = self.run_validation("--schemas")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS build: inactive/applications/dormant", result.stdout)
        self.assertEqual((self.root / "calls").read_text(), "build\nschema\nbuild\nschema\n")


if __name__ == "__main__":
    unittest.main()
