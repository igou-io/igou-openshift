"""Check safe native task registration and fixed Slack reporting."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module("register_automations", ROOT / "scripts/register_automations.py")

    def test_new_tasks_are_parked_then_paused_before_real_schedule(self):
        calls = []
        tasks = self.module.load_definitions()[1]

        def fake_api(base, path, token, method="GET", body=None):
            calls.append((path, method, body))
            if path == "/auth/login":
                return {"token": "session-token"}
            if path.startswith("/v1/agents"):
                return {"data": [{"name": "igou-sre", "builtin": True, "id": "agent-1"}]}
            if path == "/v1/scheduled-tasks" and method == "GET":
                return {"scheduled_tasks": []}
            if path == "/v1/scheduled-tasks" and method == "POST":
                return {"id": "task-1"}
            if body and "rrule" in body:
                return {"state": "paused", "rrule": body["rrule"]}
            return {"state": "paused"}

        with mock.patch.object(self.module, "api", side_effect=fake_api), mock.patch.object(
            self.module.getpass, "getpass", return_value="password"
        ), mock.patch("builtins.print"):
            self.module.reconcile("https://example.invalid", "igou")
        creates = [i for i, (_, method, _) in enumerate(calls) if method == "POST" and i > 0]
        self.assertEqual(len(creates), 4)
        for index, task in zip(creates, tasks):
            self.assertEqual(calls[index][2]["rrule"], self.module.PARKED_RRULE)
            self.assertEqual(calls[index + 1][2], {"state": "paused"})
            self.assertEqual(calls[index + 2][2]["rrule"], task["rrule"])
            self.assertEqual(calls[index + 2][2]["state"], "paused")


class SlackToolTests(unittest.TestCase):
    def setUp(self):
        sys.modules["omnigent_client"] = types.SimpleNamespace(tool=lambda function: function)
        self.module = load_module("sre_slack", ROOT / "agents/igou-sre/tools/python/sre_slack.py")

    def test_one_line_and_multiline_digests_use_fixed_channel(self):
        class Response:
            def __enter__(self):
                return io.BytesIO(b'{"ok": true, "ts": "123.4"}')

            def __exit__(self, *args):
                return False

        with mock.patch.object(self.module.TOKEN_FILE.__class__, "read_text", return_value="secret"), mock.patch.object(
            self.module.urllib.request, "urlopen", return_value=Response()
        ) as send:
            for digest in (
                "SRESweepDailyHealth — all green: backups, CNPG, ArgoCD, certificates, rk8s.",
                "SRESweepDailyHealth\nFinding: backup age exceeds 26 hours.",
            ):
                result = self.module.post_sre_sweep_digest("SRESweepDailyHealth", digest)
                self.assertIn("123.4", result)
                self.assertEqual(json.loads(send.call_args.args[0].data)["channel"], "C0BTMS7AV34")
                self.assertEqual(json.loads(send.call_args.args[0].data)["text"], digest)
            self.assertIn("no message sent", self.module.post_sre_sweep_digest("other", "other"))
            self.assertIn("3000 characters", self.module.post_sre_sweep_digest("SRESweepDailyHealth", "SRESweepDailyHealth — " + "x" * 3000))
            self.assertIn("3000 characters", self.module.post_sre_sweep_digest("SRESweepDailyHealth", "SRESweepDailyHealth\n" + "finding\n" * 20))
            self.assertEqual(send.call_count, 2)


class RuntimeWiringTests(unittest.TestCase):
    def test_server_host_runner_env_chain(self):
        deployment = yaml.safe_load((ROOT / "omnigent-deployment.yaml").read_text())
        server_env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        server_path = next(entry["value"] for entry in server_env if entry["name"] == "PATH")
        self.assertTrue(server_path.startswith("/opt/venv/bin:"))
        config = yaml.safe_load((ROOT / "omnigent-config-configmap.yaml").read_text())["data"]
        passthrough = set(config["OMNIGENT_RUNNER_ENV_PASSTHROUGH"].split(","))
        sandbox_config = yaml.safe_load((ROOT / "omnigent-sandbox-config-configmap.yaml").read_text())
        host_env = set(yaml.safe_load(sandbox_config["data"]["config.yaml"])["sandbox"]["kubernetes"]["env"])
        required = {
            "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy",
            "GHAPP_BROKER_URL", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL",
        }
        self.assertIn("OMNIGENT_RUNNER_ENV_PASSTHROUGH", host_env)
        self.assertLessEqual(required, passthrough & host_env)

    def test_unclassified_runner_still_gets_default_deny(self):
        deny = yaml.safe_load((ROOT / "omnigent-sandboxes-default-deny-networkpolicy.yaml").read_text())
        allow = yaml.safe_load((ROOT / "omnigent-sre-runner-networkpolicy.yaml").read_text())
        self.assertEqual(deny["metadata"]["namespace"], "omnigent-sandboxes")
        self.assertEqual(deny["spec"]["podSelector"], {})
        self.assertEqual(set(deny["spec"]["policyTypes"]), {"Ingress", "Egress"})
        self.assertEqual(deny["spec"]["ingress"], [])
        self.assertEqual(deny["spec"]["egress"], [])
        self.assertEqual(allow["spec"]["podSelector"]["matchLabels"]["omnigent.ai/agent"], "igou-sre")


if __name__ == "__main__":
    unittest.main()
