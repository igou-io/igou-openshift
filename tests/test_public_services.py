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
        self.values = yaml.safe_load((CHART / "examples/web-test-values.yaml").read_text())

    def render(self, values: dict) -> subprocess.CompletedProcess:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as config:
            yaml.safe_dump(values, config)
            config.flush()
            return subprocess.run(
                ["helm", "template", "test", str(CHART), "-f", config.name],
                capture_output=True, text=True, check=False,
            )

    def test_defaults_create_guardrails_without_endpoints(self) -> None:
        result = self.render({})
        self.assertEqual(result.returncode, 0, result.stderr)
        objects = list(yaml.safe_load_all(result.stdout))
        self.assertEqual(len(objects), 8)
        self.assertNotIn("Service", {o["kind"] for o in objects})
        namespace = next(o for o in objects if o["kind"] == "Namespace")
        self.assertEqual(namespace["metadata"]["name"], "public-services")
        self.assertEqual(namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"], "restricted")
        for obj in objects:
            if obj["kind"] not in {"Namespace", "ValidatingAdmissionPolicy", "ValidatingAdmissionPolicyBinding"}:
                self.assertEqual(obj["metadata"]["namespace"], "public-services")
        account = next(o for o in objects if o["kind"] == "ServiceAccount")
        self.assertFalse(account["automountServiceAccountToken"])

    def test_example_publishes_only_requested_ports_without_nodeports(self) -> None:
        result = self.render(self.values)
        self.assertEqual(result.returncode, 0, result.stderr)
        objects = list(yaml.safe_load_all(result.stdout))
        self.assertEqual(len(objects), 10)
        service = next(o for o in objects if o["kind"] == "Service")
        self.assertEqual(service["metadata"]["namespace"], "public-services")
        spec = service["spec"]
        self.assertEqual(spec["loadBalancerClass"], "tailscale")
        self.assertFalse(spec["allocateLoadBalancerNodePorts"])
        self.assertEqual(
            {(p["port"], p["protocol"]) for p in spec["ports"]},
            {(8080, "TCP")},
        )
        self.assertEqual(spec["selector"], {"app.kubernetes.io/name": "public-web-test"})
        udp = yaml.safe_load((CHART / "examples/udp-values.yaml").read_text())
        result = self.render(udp)
        self.assertEqual(result.returncode, 0, result.stderr)
        service = next(o for o in yaml.safe_load_all(result.stdout) if o["kind"] == "Service")
        self.assertEqual(service["spec"]["ports"], [
            {"name": "udp", "port": 9000, "targetPort": 9000, "protocol": "UDP"},
        ])

    def test_policy_uses_target_ports_and_scopes_both_parent_labels(self) -> None:
        service = self.values["services"][0]
        service["ports"][0]["targetPort"] = "http"
        result = self.render(self.values)
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = next(o for o in yaml.safe_load_all(result.stdout) if o["kind"] == "NetworkPolicy" and o["metadata"]["name"] == "public-web-test-public")
        peer = policy["spec"]["ingress"][0]["from"][0]
        self.assertEqual(peer["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"], "tailscale")
        self.assertEqual(peer["podSelector"]["matchLabels"]["tailscale.com/parent-resource"], "public-web-test-public")
        self.assertEqual(peer["podSelector"]["matchLabels"]["tailscale.com/parent-resource-ns"], "public-services")
        self.assertEqual(peer["podSelector"]["matchLabels"]["tailscale.com/parent-resource-type"], "svc")
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

    def test_namespace_denies_all_other_traffic_and_only_allows_cluster_dns(self) -> None:
        result = self.render({})
        policies = {o["metadata"]["name"]: o["spec"] for o in yaml.safe_load_all(result.stdout) if o["kind"] == "NetworkPolicy"}
        deny = policies["default-deny"]
        self.assertEqual(set(deny["policyTypes"]), {"Ingress", "Egress"})
        self.assertEqual(deny["podSelector"], {})
        self.assertNotIn("ingress", deny)
        self.assertNotIn("egress", deny)
        dns = policies["allow-dns"]["egress"]
        self.assertEqual(len(dns), 1)
        self.assertEqual(dns[0]["to"], [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "openshift-dns"}}}])
        self.assertEqual({(p["port"], p["protocol"]) for p in dns[0]["ports"]}, {(53, "TCP"), (53, "UDP"), (5353, "TCP"), (5353, "UDP")})

    def test_rejects_per_service_namespace_and_optional_ingress_policy(self) -> None:
        for field, value in [("namespace", "another-namespace"), ("allowFromTailscale", False)]:
            with self.subTest(field=field):
                values = copy.deepcopy(self.values)
                values["services"][0][field] = value
                self.assertNotEqual(self.render(values).returncode, 0)

    def test_namespace_has_resource_budget_and_container_defaults(self) -> None:
        result = self.render({})
        objects = list(yaml.safe_load_all(result.stdout))
        quota = next(o for o in objects if o["kind"] == "ResourceQuota")
        self.assertEqual(quota["spec"]["hard"]["pods"], "20")
        self.assertEqual(quota["spec"]["hard"]["limits.memory"], "4Gi")
        limits = next(o for o in objects if o["kind"] == "LimitRange")
        self.assertEqual(limits["spec"]["limits"][0]["default"]["memory"], "512Mi")

    def test_secondary_network_guard_is_bound_only_to_public_namespace(self) -> None:
        objects = list(yaml.safe_load_all(self.render({}).stdout))
        policy = next(o for o in objects if o["kind"] == "ValidatingAdmissionPolicy")
        binding = next(o for o in objects if o["kind"] == "ValidatingAdmissionPolicyBinding")
        self.assertEqual(policy["spec"]["failurePolicy"], "Fail")
        self.assertEqual(policy["spec"]["matchConstraints"]["resourceRules"][0]["resources"], ["pods"])
        expression = policy["spec"]["validations"][0]["expression"]
        self.assertIn("k8s.v1.cni.cncf.io/networks", expression)
        self.assertIn("v1.multus-cni.io/default-network", expression)
        self.assertEqual(binding["spec"]["matchResources"]["namespaceSelector"]["matchLabels"], {"kubernetes.io/metadata.name": "public-services"})
        self.assertEqual(binding["spec"]["validationActions"], ["Deny"])
