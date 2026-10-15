from __future__ import annotations

import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


CHART = Path(__file__).resolve().parents[1] / ".helm/charts/tailscale-public-services"


class PublicServicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = yaml.safe_load((CHART / "examples/arena-values.yaml").read_text())

    def render(self, values: dict) -> subprocess.CompletedProcess:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as config:
            yaml.safe_dump(values, config)
            config.flush()
            return subprocess.run(
                ["helm", "template", "test", str(CHART), "-f", config.name],
                capture_output=True, text=True, check=False,
            )

    def test_defaults_create_no_endpoints(self) -> None:
        result = self.render({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(yaml.safe_load_all(result.stdout)), [])

    def test_example_publishes_only_requested_ports_without_nodeports(self) -> None:
        result = self.render(self.values)
        self.assertEqual(result.returncode, 0, result.stderr)
        objects = list(yaml.safe_load_all(result.stdout))
        self.assertEqual(len(objects), 1)
        spec = objects[0]["spec"]
        self.assertEqual(spec["loadBalancerClass"], "tailscale")
        self.assertFalse(spec["allocateLoadBalancerNodePorts"])
        self.assertEqual(
            {(p["port"], p["protocol"]) for p in spec["ports"]},
            {(8080, "TCP"), (27015, "TCP"), (27016, "UDP")},
        )

    def test_policy_uses_target_ports_and_scopes_both_parent_labels(self) -> None:
        service = self.values["services"][0]
        service["allowFromTailscale"] = True
        service["ports"][0]["targetPort"] = "http"
        result = self.render(self.values)
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = next(o for o in yaml.safe_load_all(result.stdout) if o["kind"] == "NetworkPolicy")
        peer = policy["spec"]["ingress"][0]["from"][0]
        self.assertEqual(peer["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"], "tailscale")
        self.assertEqual(peer["podSelector"]["matchLabels"]["tailscale.com/parent-resource"], "arena-public")
        self.assertEqual(peer["podSelector"]["matchLabels"]["tailscale.com/parent-resource-ns"], "games")
        self.assertEqual(policy["spec"]["ingress"][0]["ports"][0]["port"], "http")

    def test_rejects_empty_selectors_and_duplicate_tailnet_identities(self) -> None:
        for field, value in [("selector", {}), ("tag", "tag:k8s")]:
            with self.subTest(field=field):
                values = copy.deepcopy(self.values)
                values["services"][0][field] = value
                self.assertNotEqual(self.render(values).returncode, 0)
        duplicate = copy.deepcopy(self.values["services"][0])
        duplicate["name"] = "another-service"
        self.values["services"].append(duplicate)
        self.assertIn("duplicate tailnet hostname", self.render(self.values).stderr)

    def test_rejects_duplicate_ports(self) -> None:
        duplicate = copy.deepcopy(self.values["services"][0]["ports"][0])
        duplicate["name"] = "duplicate"
        self.values["services"][0]["ports"].append(duplicate)
        self.assertIn("duplicate port", self.render(self.values).stderr)
