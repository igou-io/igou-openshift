"""Exercise the bootstrap transformation with synthetic data and Sprig via Helm."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


CLUSTER_API = Path(__file__).resolve().parents[1] / "clusters/ocp/cluster-api"


class CasvalBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = yaml.safe_load(
            (CLUSTER_API / "casval-worker-user-data-externalsecret.yaml").read_text()
        )
        self.bootstrap = {
            "ignition": {
                "version": "3.4.0",
                "config": {
                    "merge": [{"source": "https://example.invalid:22623/config/worker"}]
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

    def test_reserves_unformatted_space_and_preserves_worker_bootstrap(self) -> None:
        result = self.render(json.dumps(self.bootstrap))
        self.assertEqual(result.returncode, 0, result.stderr)
        config = yaml.safe_load(result.stdout)
        self.assertEqual(config["ignition"], self.bootstrap["ignition"])
        self.assertEqual(config["storage"]["files"], self.bootstrap["storage"]["files"])
        self.assertNotIn("filesystems", config["storage"])
        disk, = config["storage"]["disks"]
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
        self.assertNotIn("wipePartitionEntry", partition)

    def test_worker_stub_without_storage_is_supported(self) -> None:
        del self.bootstrap["storage"]
        self.assertEqual(self.render(json.dumps(self.bootstrap)).returncode, 0)

    def test_unsafe_bootstrap_fails_before_a_secret_can_be_generated(self) -> None:
        invalid = copy.deepcopy(self.bootstrap)
        del invalid["ignition"]["version"]
        replaced = copy.deepcopy(self.bootstrap)
        replaced["ignition"]["config"]["replace"] = {
            "source": "https://example.invalid/replacement.ign"
        }
        disks = copy.deepcopy(self.bootstrap)
        disks["storage"]["disks"] = [{"device": "/dev/sda"}]
        for fixture in ("invalid JSON", json.dumps(invalid), json.dumps(replaced), json.dumps(disks)):
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
