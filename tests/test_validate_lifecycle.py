from pathlib import Path
import sys
import tempfile
import unittest

import yaml
from yamllint.config import YamlLintConfig
from yamllint import linter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_lifecycle import Lifecycle


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.write("clusters/ocp/kustomization.yaml", "resources: []\n")

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, filename, content):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def app(self, path, repo="https://github.com/igou-io/igou-openshift.git", multiple=False):
        source = {"repoURL": repo, "path": path}
        spec = {"sources": [source]} if multiple else {"source": source}
        return yaml.safe_dump({"kind": "Application", "metadata": {"name": "example"}, "spec": spec})

    def check(self, rendered=""):
        inventory = Lifecycle(self.root)
        inventory.add_render(self.root / "clusters/ocp", rendered)
        return inventory.validate()

    def test_missing_local_source_fails_but_external_source_is_ignored(self):
        for repo in ("https://github.com/igou-io/igou-openshift.git", "ssh://git@github.com/igou-io/igou-openshift.git", "git@github.com:igou-io/igou-openshift.git"):
            with self.subTest(repo=repo):
                self.assertTrue(any("missing source path" in error for error in self.check(self.app("applications/missing", repo))))
        self.assertEqual(self.check(self.app("harness", "https://forgejo.igou.systems/lab/pipeline.git")), [])

    def test_multisource_and_normalized_paths_cannot_activate_inactive(self):
        self.write("inactive/applications/example/kustomization.yaml", "resources: []\n")
        errors = self.check(self.app("applications/../inactive/applications/example", repo="git@github.com:igou-io/igou-openshift.git", multiple=True))
        self.assertTrue(any("active source points into inactive/" in error for error in errors))

    def test_active_transitive_resource_patch_and_generator_references_cannot_use_inactive(self):
        self.write("applications/example/kustomization.yaml", "resources:\n  - ../../components/shared\n")
        self.write("inactive/settings.yaml", "value: example\n")
        for config in (
            "resources:\n  - ../../inactive/settings.yaml\n",
            "patches:\n  - path: ../../inactive/settings.yaml\n",
            "configMapGenerator:\n  - name: example\n    files:\n      - config=../../inactive/settings.yaml\n",
        ):
            with self.subTest(config=config):
                self.write("components/shared/kustomization.yaml", config)
                self.assertTrue(any("active reference to inactive/" in error for error in self.check(self.app("applications/example"))))

    def test_component_reachable_through_application_does_not_need_own_registration(self):
        self.write("applications/example/kustomization.yml", "resources:\n  - ../../components/shared\n")
        self.write("components/shared/Kustomization", "resources: []\n")
        self.assertEqual(self.check(self.app("applications/example")), [])
        self.assertTrue(any("unregistered workload" in error for error in self.check()))

    def test_nested_application_source_is_checked(self):
        self.write("applications/example/kustomization.yaml", "resources: []\n")
        inventory = Lifecycle(self.root)
        inventory.add_render(self.root / "clusters/ocp", self.app("applications/example"))
        inventory.add_render(self.root / "applications/example", self.app("components/missing"))
        self.assertTrue(any("missing source path" in error for error in inventory.validate()))

    def test_orphan_manifest_requires_specific_reason_and_stale_exception_fails(self):
        filename = "inactive/applications/example/manual-configmap.yaml"
        self.write(filename, "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: manual\n")
        self.assertTrue(any("orphaned manifest" in error for error in self.check()))
        self.write("scripts/lifecycle-exceptions.yaml", yaml.safe_dump({filename: "Manual helper documented in the runbook."}))
        self.assertEqual(self.check(), [])
        self.write("inactive/applications/example/kustomization.yaml", "resources:\n  - manual-configmap.yaml\n")
        self.assertTrue(any("stale exception" in error for error in self.check()))

    def test_missing_reference_and_repository_escape_fail(self):
        for path, message in (("missing.yaml", "missing reference"), ("../../../outside.yaml", "escapes repository")):
            with self.subTest(path=path):
                self.write("clusters/ocp/kustomization.yaml", yaml.safe_dump({"resources": [path]}))
                self.assertTrue(any(message in error for error in self.check()))

    def test_generator_manifests_and_documented_manual_helpers_are_not_orphans(self):
        self.write("applications/example/kustomization.yaml", "configMapGenerator:\n  - name: bundle\n    files:\n      - job=manual-job.yaml\n")
        self.write("applications/example/manual-job.yaml", "apiVersion: batch/v1\nkind: Job\nmetadata:\n  name: manual\n")
        self.assertEqual(self.check(self.app("applications/example")), [])


class BlockStyleTests(unittest.TestCase):
    def test_lint_rejects_nonempty_flow_collections_and_accepts_empty_and_scalar_contents(self):
        config = YamlLintConfig(file=str(Path(__file__).resolve().parents[1] / ".yamllint"))
        for content, expected in (
            ("args: [serve]\n", "brackets"),
            ("labels: {app: test}\n", "braces"),
            ("args: []\nlabels: {}\nscript: |\n  echo '[serve] {app: test}'\n", None),
        ):
            with self.subTest(content=content):
                rules = {problem.rule for problem in linter.run(content, config)}
                if expected:
                    self.assertIn(expected, rules)
                else:
                    self.assertEqual(rules, set())


if __name__ == "__main__":
    unittest.main()
