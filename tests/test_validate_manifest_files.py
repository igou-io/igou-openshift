from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import validate_manifest_files as validator


class ValidateManifestFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.original_repo_root = validator.REPO_ROOT
        validator.REPO_ROOT = self.root

    def tearDown(self) -> None:
        validator.REPO_ROOT = self.original_repo_root
        self.temporary_directory.cleanup()

    def write(self, filename: str, content: str) -> Path:
        path = self.root / filename
        path.write_text(content, encoding="utf-8")
        return path

    def test_correctly_named_object_passes(self) -> None:
        path = self.write(
            "example-configmap.yaml",
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: example\n",
        )

        self.assertEqual(validator.validate(path), [])

    def test_multiple_kubernetes_documents_fail(self) -> None:
        path = self.write(
            "first-configmap.yaml",
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: first\n"
            "---\n"
            "apiVersion: v1\nkind: Secret\nmetadata:\n  name: second\n",
        )

        self.assertEqual(
            validator.validate(path),
            [
                "first-configmap.yaml: expected exactly one non-empty Kubernetes "
                "object; found 2 object(s) in 2 document(s)"
            ],
        )

    def test_object_without_metadata_name_fails(self) -> None:
        path = self.write(
            "generated-configmap.yaml",
            "apiVersion: v1\n"
            "kind: ConfigMap\n"
            "metadata:\n"
            "  generateName: generated-\n",
        )

        self.assertEqual(
            validator.validate(path),
            [
                "generated-configmap.yaml: Kubernetes object v1/ConfigMap must set "
                "metadata.name for manifest filename validation"
            ],
        )

    def test_list_manifest_fails(self) -> None:
        path = self.write(
            "objects-list.yaml",
            "apiVersion: v1\n"
            "kind: List\n"
            "metadata:\n"
            "  name: objects\n"
            "items: []\n",
        )

        self.assertEqual(
            validator.validate(path),
            [
                "objects-list.yaml: authored kind: List manifests are not allowed; "
                "place each item in its own object file"
            ],
        )

    def test_non_object_yaml_is_ignored(self) -> None:
        path = self.write(
            "settings.yaml",
            "theme: dark\nfeatures:\n  - search\n",
        )

        self.assertEqual(validator.validate(path), [])

    def test_kustomization_configuration_is_ignored(self) -> None:
        path = self.write(
            "kustomization.yaml",
            "apiVersion: kustomize.config.k8s.io/v1beta1\n"
            "kind: Kustomization\n"
            "resources:\n"
            "  - example-configmap.yaml\n",
        )

        self.assertEqual(validator.validate(path), [])


if __name__ == "__main__":
    unittest.main()
