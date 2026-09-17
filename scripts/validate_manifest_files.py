#!/usr/bin/env python3
"""Manually audit file boundaries and names for authored Kubernetes manifests."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_ROOTS = (
    "applications",
    "components",
    "clusters",
    "groups",
    "test-workloads",
)
EXCLUDED_PARTS = {"charts", "templates"}
EXCLUDED_PREFIXES = (
    Path("test-workloads/windows-vms/examples"),
)
EXCLUDED_FILENAMES = {
    "Chart.yaml",
    "Chart.yml",
    "kustomization.yaml",
    "kustomization.yml",
    "values.yaml",
    "values.yml",
}
KIND_ALIASES = {
    "PersistentVolume": "pv",
    "PersistentVolumeClaim": "pvc",
}


def is_excluded(path: Path) -> bool:
    relative = path.relative_to(REPO_ROOT)
    is_values_file = (
        path.name.startswith(("values-", "values."))
        or path.name.endswith(("-values.yaml", "-values.yml"))
    )
    return (
        path.name in EXCLUDED_FILENAMES
        or is_values_file
        or bool(EXCLUDED_PARTS.intersection(relative.parts))
        or any(relative.is_relative_to(prefix) for prefix in EXCLUDED_PREFIXES)
    )


def is_kubernetes_document(document: Any) -> bool:
    return (
        isinstance(document, dict)
        and isinstance(document.get("apiVersion"), str)
        and isinstance(document.get("kind"), str)
    )


def filename_name(name: str) -> str:
    """Make a deterministic filename token from metadata.name."""
    return re.sub(r"[^a-z0-9.-]+", "-", name.lower()).strip("-.")


def expected_filename(document: dict[str, Any]) -> str:
    kind = document["kind"]
    kind_token = KIND_ALIASES.get(kind, kind.lower())
    return f"{filename_name(document['metadata']['name'])}-{kind_token}.yaml"


def manifest_files() -> list[Path]:
    paths: list[Path] = []
    for root_name in MANIFEST_ROOTS:
        root = REPO_ROOT / root_name
        paths.extend(
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix in {".yaml", ".yml"}
            and not is_excluded(path)
        )
    return sorted(paths)


def validate(path: Path) -> list[str]:
    if is_excluded(path):
        return []

    relative = path.relative_to(REPO_ROOT)
    try:
        documents = [
            document
            for document in yaml.safe_load_all(path.read_text(encoding="utf-8"))
            if document is not None
        ]
    except yaml.YAMLError as error:
        return [f"{relative}: invalid YAML: {error}"]

    objects = [document for document in documents if is_kubernetes_document(document)]
    if not objects:
        return []

    errors: list[str] = []
    if len(documents) != 1 or len(objects) != 1:
        errors.append(
            f"{relative}: expected exactly one non-empty Kubernetes object; "
            f"found {len(objects)} object(s) in {len(documents)} document(s)"
        )
        return errors

    document = objects[0]
    if document["kind"] == "List":
        return [
            f"{relative}: authored kind: List manifests are not allowed; "
            "place each item in its own object file"
        ]

    metadata = document.get("metadata")
    name = metadata.get("name") if isinstance(metadata, dict) else None
    if not isinstance(name, str) or not name:
        return [
            f"{relative}: Kubernetes object {document['apiVersion']}/{document['kind']} "
            "must set metadata.name for manifest filename validation"
        ]

    expected = expected_filename(document)
    if path.suffix != ".yaml":
        errors.append(f"{relative}: object manifests must use .yaml (expected {expected})")
    if path.name != expected:
        errors.append(f"{relative}: expected filename {expected}")
    return errors


def main() -> int:
    errors = [error for path in manifest_files() for error in validate(path)]
    if errors:
        print("Manifest file convention violations:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("All authored Kubernetes manifest files follow the repository convention.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
