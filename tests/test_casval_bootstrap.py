"""Exercise the bootstrap transformation with synthetic data and Sprig via Helm."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.parse import unquote

import yaml


CLUSTER_API = Path(__file__).resolve().parents[1] / "clusters/ocp/cluster-api"
MACHINECONFIGS = CLUSTER_API.parent / "machineconfigs"


class CasvalBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = yaml.safe_load(
            (CLUSTER_API / "casval-worker-user-data-externalsecret.yaml").read_text()
        )
        self.bootstrap = {
            "ignition": {
                "version": "3.4.0",
                "config": {
                    "merge": [
                        {
                            "source": "https://example.invalid:22623/config/worker",
                            "httpHeaders": [{"name": "X-Fixture", "value": "synthetic"}],
                        },
                        {"source": "https://example.invalid/extra.ign"},
                    ]
                },
                "security": {
                    "tls": {
                        "certificateAuthorities": [
                            {"source": "https://example.invalid/ca.pem"}
                        ]
                    }
                },
            },
            "storage": {
                "files": [{"path": "/etc/bootstrap-fixture", "mode": 420}]
            },
        }

    def render(self, user_data: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as directory:
            chart = Path(directory)
            (chart / "templates").mkdir()
            (chart / "Chart.yaml").write_text(
                "apiVersion: v2\nname: casval-bootstrap-test\nversion: 0.1.0\n"
            )
            (chart / "values.yaml").write_text(yaml.safe_dump({
                "template": self.manifest["spec"]["target"]["template"]["data"]["userData"],
                "fixture": {"userData": user_data},
            }, default_flow_style=False))
            (chart / "templates/ignition.yaml").write_text(
                '{{ tpl .Values.template .Values.fixture }}\n'
            )
            return subprocess.run(
                ["helm", "template", "casval-test", str(chart)],
                capture_output=True, text=True, check=False,
            )

    def test_selects_casval_pool_and_preserves_managed_bootstrap(self) -> None:
        result = self.render(json.dumps(self.bootstrap))
        self.assertEqual(result.returncode, 0, result.stderr)
        config = yaml.safe_load(result.stdout)
        expected = copy.deepcopy(self.bootstrap)
        expected["ignition"]["config"]["merge"][0]["source"] = (
            "https://example.invalid:22623/config/casval"
        )
        self.assertEqual(config, expected)

    def test_machineconfig_reserves_unformatted_space(self) -> None:
        mc = yaml.safe_load(
            (MACHINECONFIGS / "98-casval-data-partition-machineconfig.yaml").read_text()
        )
        storage = mc["spec"]["config"]["storage"]
        self.assertNotIn("filesystems", storage)
        disk, = storage["disks"]
        self.assertEqual(
            disk["device"],
            "/dev/disk/by-id/nvme-Samsung_SSD_990_PRO_2TB_S7KHNU0Y110642R",
        )
        self.assertFalse(disk["wipeTable"])
        partition, = disk["partitions"]
        self.assertEqual(partition["number"], 5)
        self.assertEqual(partition["label"], "casval-lvm")
        self.assertEqual(partition["startMiB"], 300 * 1024)
        self.assertEqual(partition["sizeMiB"], 0)
        self.assertEqual(partition["typeGuid"], "E6D6D379-F507-44C2-A23C-238F2A3DF928")
        self.assertNotIn("wipePartitionEntry", partition)

    def test_worker_stub_without_storage_is_supported(self) -> None:
        del self.bootstrap["storage"]
        result = self.render(json.dumps(self.bootstrap))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("storage", yaml.safe_load(result.stdout))

    def test_node_registers_in_the_same_pool_that_supplies_ignition(self) -> None:
        mc = yaml.safe_load(
            (MACHINECONFIGS / "98-casval-data-partition-machineconfig.yaml").read_text()
        )
        pool = yaml.safe_load((MACHINECONFIGS / "casval-machineconfigpool.yaml").read_text())
        result = self.render(json.dumps(self.bootstrap))
        self.assertEqual(result.returncode, 0, result.stderr)
        source = yaml.safe_load(result.stdout)["ignition"]["config"]["merge"][0]["source"]
        self.assertEqual(source.rsplit("/", 1)[1], pool["metadata"]["name"])

        config = mc["spec"]["config"]
        env_file, = config["storage"]["files"]
        environment = unquote(env_file["contents"]["source"].split(",", 1)[1])
        variable, labels = environment.strip().split("=", 1)
        self.assertEqual(variable, "CUSTOM_KUBELET_LABELS")
        registration_labels = dict(label.split("=", 1) for label in labels.split(","))
        machineset = yaml.safe_load((CLUSTER_API / "casval-worker-machineset.yaml").read_text())
        capi_labels = machineset["spec"]["template"]["metadata"]["labels"]
        for key, value in pool["spec"]["nodeSelector"]["matchLabels"].items():
            self.assertEqual(registration_labels[key], value)
            # MachineSet labels propagate to existing Machines: the pool role
            # must come only from installation, after the disk was partitioned.
            self.assertNotIn(key, capi_labels)
            self.assertNotEqual(key, "node-role.kubernetes.io/worker")
            self.assertNotEqual(key, "node-role.kubernetes.io/burst")

        kubelet, = config["systemd"]["units"]
        self.assertEqual(kubelet["name"], "kubelet.service")
        dropin, = kubelet["dropins"]
        self.assertIn(f"EnvironmentFile={env_file['path']}\n", dropin["contents"])
        selector, = pool["spec"]["machineConfigSelector"]["matchExpressions"]
        self.assertEqual(selector["key"], "machineconfiguration.openshift.io/role")
        self.assertEqual(selector["operator"], "In")
        self.assertEqual(set(selector["values"]), {"worker", "casval"})
        self.assertEqual(mc["metadata"]["labels"][selector["key"]], "casval")
        self.assertLess(
            int(mc["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]),
            int(pool["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"]),
        )

    def test_unsafe_bootstrap_fails_before_a_secret_can_be_generated(self) -> None:
        invalid = copy.deepcopy(self.bootstrap)
        del invalid["ignition"]["version"]
        replaced = copy.deepcopy(self.bootstrap)
        replaced["ignition"]["config"]["replace"] = {
            "source": "https://example.invalid/replacement.ign"
        }
        disks = copy.deepcopy(self.bootstrap)
        disks["storage"]["disks"] = [{"device": "/dev/sda"}]
        missing = copy.deepcopy(self.bootstrap)
        del missing["ignition"]["config"]["merge"]
        wrong_pool = copy.deepcopy(self.bootstrap)
        wrong_pool["ignition"]["config"]["merge"][0]["source"] = (
            "https://example.invalid:22623/config/master"
        )
        insecure = copy.deepcopy(self.bootstrap)
        insecure["ignition"]["config"]["merge"][0]["source"] = (
            "http://example.invalid:22623/config/worker"
        )
        duplicate = copy.deepcopy(self.bootstrap)
        duplicate["ignition"]["config"]["merge"].append(
            copy.deepcopy(duplicate["ignition"]["config"]["merge"][0])
        )
        for fixture in ("invalid JSON", *(json.dumps(item) for item in (
            invalid, replaced, disks, missing, wrong_pool, insecure, duplicate,
        ))):
            with self.subTest(fixture=fixture):
                self.assertNotEqual(self.render(fixture).returncode, 0)

    def test_capi_and_metal3_use_the_same_generated_bootstrap(self) -> None:
        machineset = yaml.safe_load((CLUSTER_API / "casval-worker-machineset.yaml").read_text())
        machine = machineset["spec"]["template"]["spec"]
        template_name = machine["infrastructureRef"]["name"]
        metal3 = yaml.safe_load((CLUSTER_API / f"{template_name}-metal3machinetemplate.yaml").read_text())
        secret = self.manifest["spec"]["target"]["name"]
        self.assertEqual(machine["bootstrap"]["dataSecretName"], secret)
        self.assertEqual(metal3["spec"]["template"]["spec"]["userData"]["name"], secret)
        self.assertEqual(metal3["metadata"]["name"], template_name)


if __name__ == "__main__":
    unittest.main()
