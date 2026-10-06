#!/usr/bin/env python3
"""Build each Kustomization once, optionally validating the rendered schemas."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml


def kustomizations(root: Path) -> list[Path]:
    paths = []
    for directory, children, files in os.walk(root):
        children[:] = sorted(
            name for name in children
            if name not in {".git", ".venv", ".cache", "charts", "archive", "__pycache__"}
        )
        if "kustomization.yaml" in files:
            path = Path(directory)
            config = yaml.safe_load((path / "kustomization.yaml").read_text())
            # Components are validated through their consuming Kustomizations.
            if config.get("kind") != "Component":
                paths.append(path)
    return sorted(paths)


def validate(root: Path, schemas: bool, schema_flags: list[str]) -> int:
    directories = kustomizations(root)
    if not directories:
        print("No Kustomizations found.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="gitops-validation-") as temporary:
        rendered = Path(temporary) / "rendered.yaml"
        for directory in directories:
            label = directory.relative_to(root)
            with rendered.open("w") as output:
                build = subprocess.run(
                    ["kustomize", "build", "--enable-helm", str(directory)],
                    stdout=output, stderr=subprocess.PIPE, text=True, check=False,
                )
            if build.returncode:
                print(f"FAIL build: {label}\n{build.stderr}", file=sys.stderr)
                return 1
            print(f"PASS build: {label}", flush=True)
            if schemas:
                result = subprocess.run(
                    ["kubeconform", *schema_flags, str(rendered)], check=False,
                )
                if result.returncode:
                    print(f"FAIL schemas: {label}", file=sys.stderr)
                    return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schemas", action="store_true")
    args, schema_flags = parser.parse_known_args()
    if schema_flags and not args.schemas:
        parser.error("schema flags require --schemas")
    return validate(Path.cwd(), args.schemas, schema_flags)


if __name__ == "__main__":
    raise SystemExit(main())
