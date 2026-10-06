"""Check active GitOps paths and account for authored object manifests."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import yaml

from validate_manifest_files import is_kubernetes_document, manifest_files


KUSTOMIZATION_NAMES = ("kustomization.yaml", "kustomization.yml", "Kustomization")
LOCAL_REPOSITORY = "igou-io/igou-openshift"


def kustomization_file(directory: Path) -> Path | None:
    return next((directory / name for name in KUSTOMIZATION_NAMES if (directory / name).is_file()), None)


def local_repository(url: str) -> bool:
    # HTTPS and SSH spellings identify the same Git repository.
    parsed = urlparse(url.replace("git@github.com:", "ssh://git@github.com/"))
    return parsed.hostname == "github.com" and parsed.path.strip("/").removesuffix(".git") == LOCAL_REPOSITORY


def references(config: dict) -> list[str]:
    paths = []
    for key in ("resources", "bases", "components", "crds", "configurations", "generators", "transformers", "patchesStrategicMerge"):
        paths.extend(value for value in config.get(key, []) if isinstance(value, str))
    for key in ("patches", "patchesJson6902"):
        paths.extend(value["path"] for value in config.get(key, []) if isinstance(value, dict) and "path" in value)
    for key in ("configMapGenerator", "secretGenerator"):
        for generator in config.get(key, []):
            paths.extend(value.split("=", 1)[-1] for value in generator.get("files", []))
            paths.extend(generator.get("envs", []))
            if generator.get("env"):
                paths.append(generator["env"])
    for chart in config.get("helmCharts", []):
        if chart.get("valuesFile"):
            paths.append(chart["valuesFile"])
        paths.extend(chart.get("additionalValuesFiles", []))
    if config.get("openapi", {}).get("path"):
        paths.append(config["openapi"]["path"])
    return paths


class Lifecycle:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.configs = {}
        self.applications = {}
        for directory, children, _ in os.walk(self.root):
            children[:] = sorted(name for name in children if name not in {".git", ".venv", ".cache", "charts", "templates", "__pycache__"})
            path = Path(directory)
            config_file = kustomization_file(path)
            if config_file:
                self.configs[path] = yaml.safe_load(config_file.read_text()) or {}

    def add_render(self, directory: Path, rendered: str) -> None:
        # Retain only Application sources, never rendered Secret values.
        self.applications[directory.resolve()] = [
            (doc.get("metadata", {}).get("name", "<unnamed>"), doc.get("spec", {}))
            for doc in yaml.safe_load_all(rendered)
            if isinstance(doc, dict) and doc.get("kind") == "Application"
        ]

    def validate(self) -> list[str]:
        errors = []
        edges = {}
        referenced = set()
        for directory, config in self.configs.items():
            paths = []
            for value in references(config):
                # Remote Kustomize resources are validated by the build itself.
                if urlparse(value).scheme or value.startswith("git@") or "github.com/" in value:
                    continue
                path = (directory / value).resolve()
                if not path.is_relative_to(self.root):
                    errors.append(f"{directory.relative_to(self.root)}: reference escapes repository: {value}")
                elif not path.exists():
                    errors.append(f"{directory.relative_to(self.root)}: missing reference: {value}")
                else:
                    paths.append(path)
                    referenced.add(path)
            edges[directory] = paths

        active = set()
        pending = [path for path in self.configs if path.parent == self.root / "clusters"]
        while pending:
            directory = pending.pop()
            if directory in active:
                continue
            active.add(directory)
            for path in edges.get(directory, []):
                if path.is_relative_to(self.root / "inactive"):
                    errors.append(f"{directory.relative_to(self.root)}: active reference to inactive/: {path.relative_to(self.root)}")
                elif path in self.configs:
                    pending.append(path)
            for name, spec in self.applications.get(directory, []):
                sources = spec.get("sources", [])
                if spec.get("source"):
                    sources = [*sources, spec["source"]]
                for source in sources:
                    if not local_repository(source.get("repoURL", "")) or not source.get("path"):
                        continue
                    path = (self.root / source["path"]).resolve()
                    if not path.is_relative_to(self.root):
                        errors.append(f"Application {name}: source path escapes repository: {source['path']}")
                    elif path.is_relative_to(self.root / "inactive"):
                        errors.append(f"Application {name}: active source points into inactive/: {source['path']}")
                    elif not path.is_dir():
                        errors.append(f"Application {name}: missing source path: {source['path']}")
                    else:
                        pending.append(path)
                        # Argo directory sources can deploy raw manifests without Kustomize.
                        if path not in self.configs:
                            referenced.update(path.glob("*.yaml"))
                            referenced.update(path.glob("*.yml"))

        for parent in ("applications", "components"):
            for path in sorted(self.configs):
                if path.parent == self.root / parent and path not in active:
                    errors.append(f"{path.relative_to(self.root)}: unregistered workload; register it or move it to inactive/")

        exceptions_path = self.root / "scripts/lifecycle-exceptions.yaml"
        exceptions = yaml.safe_load(exceptions_path.read_text()) if exceptions_path.exists() else {}
        objects = set()
        for path in manifest_files(self.root):
            if any(is_kubernetes_document(doc) for doc in yaml.safe_load_all(path.read_text())):
                objects.add(path)
        for value, reason in (exceptions or {}).items():
            path = (self.root / value).resolve()
            if not isinstance(reason, str) or not reason.strip():
                errors.append(f"Lifecycle exception {value}: a documented reason is required")
            elif path not in objects or path in referenced:
                errors.append(f"Lifecycle exception {value}: stale exception; remove it")
        for path in sorted(objects - referenced):
            if str(path.relative_to(self.root)) not in (exceptions or {}):
                errors.append(f"{path.relative_to(self.root)}: orphaned manifest; wire it into Kustomize or document its manual use in scripts/lifecycle-exceptions.yaml")
        return sorted(set(errors))
