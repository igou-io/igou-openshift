"""Behavioral tests with fake credentials and fake Omnigent/Kubernetes APIs."""

from __future__ import annotations

import copy
import datetime as dt
import io
import pathlib
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import sweep_client as client  # noqa: E402


class FakeKubernetes:
    def __init__(self, *, expired: bool = False):
        renew = client.utc_now() - dt.timedelta(minutes=5 if expired else 0)
        self.value = {"metadata": {"resourceVersion": "1", "annotations": {}},
                      "spec": {"leaseDurationSeconds": 120,
                               "renewTime": client.timestamp(renew),
                               "holderIdentity": "other" if expired else None}}
        self.jobs = []
        self.deleted = []

    def lease(self):
        return copy.deepcopy(self.value)

    def put_lease(self, value):
        self.value = copy.deepcopy(value)
        self.value["metadata"]["resourceVersion"] = str(
            int(self.value["metadata"]["resourceVersion"]) + 1)
        return self.lease()

    def call(self, path, method="GET", data=None):
        if path.startswith("/apis/batch/v1/namespaces/omnigent-sandboxes/jobs?"):
            return {"items": copy.deepcopy(self.jobs)}
        if method == "DELETE":
            self.deleted.append(path)
            if "/jobs/" in path:
                self.jobs = [job for job in self.jobs
                             if job["metadata"]["name"] != path.rsplit("/", 1)[-1]]
            return {}
        if "/jobs/" in path:
            if any(job["metadata"]["name"] == path.rsplit("/", 1)[-1]
                   for job in self.jobs):
                return {}
            raise client.ApiError(404, path)
        raise AssertionError((path, method))


class FakeOmnigent:
    def __init__(self):
        self.row = {"id": "conv_test", "title": "igou-sre/daily-health/test",
                    "agent_name": "igou-sre", "host_id": "host_test",
                    "runner_id": "runner_test", "sandbox_status": None,
                    "status": "idle", "archived": False, "labels": {},
                    "pending_elicitations_count": 0}
        self.messages = []
        self.submissions = 0
        self.fail_submit = False
        self.fail_create = False
        self.fail_ready = False
        self.fail_model = False
        self.blocked = False
        self.fail_items_status = None
        self.produce_output = True

    def sessions(self, run_key):
        return [copy.deepcopy(self.row)] if self.row["title"] == run_key else []

    def call(self, path, method="GET", data=None):
        if path == "/v1/agents":
            return {"data": [{"id": "ag_sre", "name": "igou-sre"}]}
        if path == "/v1/sessions" and method == "POST":
            if self.fail_create:
                raise client.ApiError(504, path)
            self.row["title"] = data["title"]
            return {"id": self.row["id"]}
        if path.endswith("/permissions"):
            return {}
        if path.endswith("/events"):
            self.submissions += 1
            if self.fail_submit:
                raise client.ApiError(504, path)
            self.messages.append({"role": "user", "content": data["data"]["content"]})
            if self.produce_output:
                self.messages.append({"role": "assistant", "content": [
                    {"type": "output_text", "text": "SRESweepDailyHealth: all green. No live infrastructure changes occurred."}]})
            return {}
        raise AssertionError((path, method))

    def session(self, _session_id):
        row = copy.deepcopy(self.row)
        if self.fail_ready:
            row["sandbox_status"] = {"stage": "failed"}
        if self.fail_model and self.submissions:
            row["status"] = "failed"
        if self.blocked and self.submissions:
            row["pending_elicitations_count"] = 1
        return row

    def items(self, _session_id):
        if self.fail_items_status:
            raise client.ApiError(self.fail_items_status, "/v1/sessions/conv_test/items")
        return copy.deepcopy(self.messages)

    def patch(self, _session_id, fields):
        self.row.update(fields)
        return copy.deepcopy(self.row)

    def label(self, _session_id, labels):
        self.row["labels"].update(labels)
        return copy.deepcopy(self.row)

    def wait_event(self, _session_id):
        return None


class ClientTests(unittest.TestCase):
    def run_fake(self, k8s, omni):
        with mock.patch.object(client, "Kubernetes", return_value=k8s), \
             mock.patch.object(client, "Omnigent", return_value=omni), \
             mock.patch.object(pathlib.Path, "read_text", return_value="Prompt"), \
             mock.patch.dict(client.os.environ, {"OMNI_URL": "http://example",
                                              "OMNI_CLIENT_ID": "id",
                                              "OMNI_CLIENT_SECRET": "fake",
                                              "SLACK_BOT_TOKEN": "fake"}):
            client.run("daily-health", "test")

    def test_occurrence_uses_new_york_local_time(self):
        now = dt.datetime(2026, 11, 2, 14, 40, tzinfo=dt.timezone.utc)
        self.assertEqual(client.occurrence("hygiene", now), "2026-11-02T09:30-05:00")
        self.assertEqual(client.occurrence("pr-followup", now), "2026-10-29T10:30-04:00")

    def test_global_gate_fails_closed_on_expired_holder(self):
        k8s = FakeKubernetes(expired=True)
        with self.assertRaisesRegex(client.SweepError, "cleanup must verify"):
            client.acquire(k8s, "igou-sre/daily-health/test", 10**12)
        self.assertEqual(k8s.lease()["spec"]["holderIdentity"], "other")

    def test_machine_token_renews_before_expiry(self):
        omni = client.Omnigent("http://example", "id", "fake-secret")
        with mock.patch.object(omni, "_mint", side_effect=[
            {"access_token": "one", "expires_in": 300},
            {"access_token": "two", "expires_in": 300},
        ]) as mint, mock.patch.object(client.time, "monotonic", side_effect=[0, 1, 100, 250, 251]):
            self.assertEqual(omni.auth(), "one")
            self.assertEqual(omni.auth(), "one")
            self.assertEqual(omni.auth(), "two")
            self.assertEqual(mint.call_count, 2)

    def test_submitted_turn_needs_user_marker_and_final_assistant_output(self):
        marker = "[igou-sre-run:test]"
        self.assertFalse(client.has_prompt([], marker))
        self.assertFalse(client.assistant_output([], 0))
        items = [{"role": "user", "content": [{"type": "input_text", "text": marker}]},
                 {"role": "assistant", "content": [{"type": "output_text", "text": "finding"}]}]
        self.assertTrue(client.has_prompt(items, marker))
        self.assertEqual(client.assistant_output(items, 0), "finding")

    def test_ambiguous_create_is_not_retried(self):
        k8s = FakeKubernetes()
        omni = FakeOmnigent()
        omni.fail_create = True
        with mock.patch.object(client, "Kubernetes", return_value=k8s), \
             mock.patch.object(client, "Omnigent", return_value=omni), \
             mock.patch.dict(client.os.environ, {"OMNI_URL": "http://example",
                                              "OMNI_CLIENT_ID": "id", "OMNI_CLIENT_SECRET": "fake"}):
            with self.assertRaisesRegex(client.SweepError, "Ambiguous session creation"):
                client.run("daily-health", "unique-manual")
        self.assertEqual(omni.submissions, 0)

    def test_ambiguous_submit_is_not_retried(self):
        k8s = FakeKubernetes()
        omni = FakeOmnigent()
        omni.fail_submit = True
        with mock.patch.object(client, "Kubernetes", return_value=k8s), \
             mock.patch.object(client, "Omnigent", return_value=omni), \
             mock.patch.object(pathlib.Path, "read_text", return_value="Prompt"), \
             mock.patch.dict(client.os.environ, {"OMNI_URL": "http://example",
                                              "OMNI_CLIENT_ID": "id", "OMNI_CLIENT_SECRET": "fake"}):
            with self.assertRaisesRegex(client.SweepError, "Ambiguous prompt submission"):
                client.run("daily-health", "unique-manual")
        self.assertEqual(omni.submissions, 1)

    def test_readiness_failure_never_submits(self):
        omni = FakeOmnigent()
        omni.fail_ready = True
        with mock.patch.object(client, "slack_post", return_value="123.45"), \
             self.assertRaisesRegex(client.SweepError, "runner failed before prompt"):
            self.run_fake(FakeKubernetes(), omni)
        self.assertEqual(omni.submissions, 0)

    def test_model_failure_and_blocked_approval_fail_the_job(self):
        for flag, reason in (("fail_model", "Model or tool execution failed"),
                             ("blocked", "requested human approval")):
            omni = FakeOmnigent()
            setattr(omni, flag, True)
            with self.subTest(flag=flag), \
                 mock.patch.object(client, "slack_post", return_value="123.45"), \
                 self.assertRaisesRegex(client.SweepError, reason):
                self.run_fake(FakeKubernetes(), omni)
            self.assertEqual(omni.submissions, 1)

    def test_403_and_unusable_digest_cannot_be_all_green(self):
        omni = FakeOmnigent()
        omni.fail_items_status = 403
        with mock.patch.object(client, "slack_post", return_value="123.45"), \
             self.assertRaisesRegex(client.ApiError, "HTTP 403"):
            self.run_fake(FakeKubernetes(), omni)
        self.assertEqual(omni.submissions, 0)
        for output in ("all green", "all green. No live infrastructure changes occurred.\nFinding: 403",
                       "\n".join(["finding"] * 21)):
            with self.subTest(output=output), self.assertRaises(client.SweepError):
                client.validate_digest(output)

    def test_completed_run_releases_only_after_cleanup_ack_and_does_not_repost(self):
        omni = FakeOmnigent()
        k8s = FakeKubernetes()
        original_lease = k8s.lease

        def acknowledged_lease():
            value = original_lease()
            if omni.row["archived"]:
                value["metadata"]["annotations"]["sre.igou.systems/cleaned-session-id"] = omni.row["id"]
            return value

        k8s.lease = acknowledged_lease
        with mock.patch.object(client, "slack_post", return_value="123.45") as post:
            self.run_fake(k8s, omni)
            self.run_fake(k8s, omni)
        self.assertEqual(omni.submissions, 1)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(k8s.lease()["spec"]["holderIdentity"], None)

    def test_slack_rate_limit_and_api_error(self):
        rate_limit = urllib.error.HTTPError("https://slack.com/api/chat.postMessage", 429,
                                           "slow", {"Retry-After": "1"}, None)
        response = io.BytesIO(b'{"ok":true,"ts":"123.45"}')
        response.__enter__ = lambda value: value
        response.__exit__ = lambda *args: None
        with mock.patch.object(client.urllib.request, "urlopen", side_effect=[rate_limit, response]), \
             mock.patch.object(client.time, "sleep") as sleep:
            self.assertEqual(client.slack_post("fake", "finding", "run", 10**12), "123.45")
            sleep.assert_called_once_with(1)
        failure = io.BytesIO(b'{"ok":false,"error":"channel_not_found"}')
        failure.__enter__ = lambda value: value
        failure.__exit__ = lambda *args: None
        with mock.patch.object(client.urllib.request, "urlopen", return_value=failure):
            with self.assertRaisesRegex(client.SweepError, "channel_not_found"):
                client.slack_post("fake", "finding", "run", 10**12)

    def test_transcript_pagination_and_stalled_cursor(self):
        omni = client.Omnigent("http://example", "id", "fake-secret")
        pages = [{"data": [{"id": "one"}], "has_more": True, "last_id": "one"},
                 {"data": [{"id": "two"}], "has_more": False, "last_id": "two"}]
        with mock.patch.object(omni, "call", side_effect=pages) as call:
            self.assertEqual([item["id"] for item in omni.items("conv_test")], ["one", "two"])
            self.assertIn("after=one", call.call_args_list[1].args[0])
        with mock.patch.object(omni, "call", return_value={"data": [], "has_more": True}):
            with self.assertRaisesRegex(client.SweepError, "did not advance"):
                omni.items("conv_test")

    def test_turn_timeout_fails_and_keeps_lease_for_recovery(self):
        omni = FakeOmnigent()
        omni.produce_output = False
        clock = [0.0]

        def wait(_session_id):
            clock[0] += 700

        omni.wait_event = wait
        k8s = FakeKubernetes()
        with mock.patch.object(client.time, "monotonic", side_effect=lambda: clock[0]), \
             mock.patch.object(client, "slack_post", return_value="123.45"), \
             self.assertRaisesRegex(client.SweepError, "turn exceeded its deadline"):
            self.run_fake(k8s, omni)
        self.assertIsNotNone(k8s.lease()["spec"]["holderIdentity"])
        self.assertEqual(omni.submissions, 1)

    def test_cleanup_targets_only_recorded_sweep_host_and_retains_transcript(self):
        k8s = FakeKubernetes(expired=True)
        k8s.value["spec"]["holderIdentity"] = "igou-sre/daily-health/test:abc"
        k8s.value["metadata"]["annotations"] = {
            "sre.igou.systems/run-key": "igou-sre/daily-health/test",
            "sre.igou.systems/session-id": "conv_test",
        }
        def job(name, host):
            return {"metadata": {"name": name}, "spec": {"template": {"spec": {
                "containers": [{"env": [
                    {"name": "OMNIGENT_HOST_ID", "value": host},
                    {"name": "OMNIGENT_HOST_TOKEN", "valueFrom": {
                        "secretKeyRef": {"name": name + "-token"}}},
                ]}]
            }}}}
        k8s.jobs = [job("omnigent-managed-target", "host_test"),
                    job("omnigent-managed-other", "host_other")]
        omni = FakeOmnigent()
        with mock.patch.object(client, "Kubernetes", return_value=k8s), \
             mock.patch.object(client, "Omnigent", return_value=omni), \
             mock.patch.dict(client.os.environ, {"OMNI_URL": "http://example",
                                              "OMNI_CLIENT_ID": "id", "OMNI_CLIENT_SECRET": "fake"}):
            client.cleanup()
        self.assertTrue(omni.row["archived"])
        self.assertEqual(len(k8s.jobs), 1)
        self.assertEqual(k8s.jobs[0]["metadata"]["name"], "omnigent-managed-other")
        self.assertEqual(k8s.lease()["metadata"]["annotations"]["sre.igou.systems/cleaned-session-id"],
                         "conv_test")
        self.assertEqual(k8s.lease()["spec"]["holderIdentity"], None)


if __name__ == "__main__":
    unittest.main()
