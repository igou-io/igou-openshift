#!/usr/bin/env python3
"""Finite Omnigent SRE sweep client and scoped orphan collector.

Only the cleanup identity can delete Kubernetes Jobs and their launch Secrets.
The normal identity can update one predeclared Lease. Both identities use the
same nonadmin Omnigent machine client; all run state is durable on the session
and Lease, so a process restart cannot silently resubmit a model turn.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

NAMESPACE = "omnigent"
RUNNER_NAMESPACE = "omnigent-sandboxes"
LEASE_NAME = "omnigent-sre-sweeps"
LEASE_PATH = f"/apis/coordination.k8s.io/v1/namespaces/{NAMESPACE}/leases/{LEASE_NAME}"
SESSION_PREFIX = "igou-sre/"
LEASE_SECONDS = 120
POLL_SECONDS = 10
SLACK_CHANNEL = "C0BTMS7AV34"
SWEEPS = {
    "daily-health": ("SRESweepDailyHealth", 7, 0, (0, 1, 2, 3, 4, 5, 6)),
    "hygiene": ("SRESweepHygiene", 9, 30, (0,)),
    "capacity": ("SRESweepCapacity", 9, 0, (1,)),
    "pr-followup": ("SRESweepPRFollowup", 10, 30, (0, 3)),
}


class SweepError(Exception):
    pass


class ApiError(SweepError):
    def __init__(self, status: int, endpoint: str):
        super().__init__(f"HTTP {status} from {endpoint}")
        self.status = status


def request_json(url: str, method: str = "GET", data: object | None = None,
                 headers: dict[str, str] | None = None, timeout: int = 30) -> dict:
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(url, data=body, method=method,
                                     headers=headers or {})
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        # Never include response bodies or headers: they can contain tokens.
        raise ApiError(error.code, urllib.parse.urlparse(url).path) from error


class Omnigent:
    def __init__(self, base_url: str, client_id: str, client_secret: str):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token = ""
        self.token_until = 0.0

    def auth(self) -> str:
        if time.monotonic() >= self.token_until:
            basic = base64.b64encode(
                f"{self.client_id}:{self.client_secret}".encode()
            ).decode()
            result = self._mint(basic)
            self.token = result["access_token"]
            self.token_until = time.monotonic() + min(int(result.get("expires_in", 300)), 300) - 60
        return self.token

    def _mint(self, basic: str) -> dict:
        request = urllib.request.Request(
            self.base_url + "/oauth/token",
            data=b"grant_type=client_credentials",
            headers={"Authorization": "Basic " + basic,
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise ApiError(error.code, "/oauth/token") from error

    def call(self, path: str, method: str = "GET", data: object | None = None) -> dict:
        return request_json(self.base_url + path, method, data,
                            {"Authorization": "Bearer " + self.auth()}, timeout=45)

    def sessions(self, run_key: str) -> list[dict]:
        query = urllib.parse.urlencode({"agent_name": "igou-sre",
                                         "search_query": run_key,
                                         "include_archived": "true", "limit": "100"})
        rows = self.call("/v1/sessions?" + query).get("data", [])
        return [row for row in rows if row.get("title") == run_key
                and row.get("agent_name") == "igou-sre"]

    def session(self, session_id: str) -> dict:
        return self.call("/v1/sessions/" + urllib.parse.quote(session_id))

    def items(self, session_id: str) -> list[dict]:
        path = "/v1/sessions/" + urllib.parse.quote(session_id) + "/items"
        items: list[dict] = []
        cursor = ""
        while True:
            query = urllib.parse.urlencode({"limit": 1000, "after": cursor})
            page = self.call(path + "?" + query)
            items.extend(page.get("data", []))
            if not page.get("has_more"):
                return items
            next_cursor = page.get("last_id")
            if not next_cursor or next_cursor == cursor:
                raise SweepError("Transcript pagination did not advance")
            cursor = next_cursor

    def wait_event(self, session_id: str) -> None:
        """Use the live stream as a wake-up hint; snapshots remain authoritative."""
        path = "/v1/sessions/" + urllib.parse.quote(session_id) + "/stream"
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Authorization": "Bearer " + self.auth(),
                     "Accept": "text/event-stream"},
        )
        try:
            with urllib.request.urlopen(request, timeout=POLL_SECONDS) as response:
                for line in response:
                    if line.startswith(b"data:"):
                        return
        except (TimeoutError, urllib.error.URLError):
            # Stream disconnects are expected. Reconcile the next snapshot
            # and transcript page before reconnecting; never resubmit input.
            return

    def patch(self, session_id: str, fields: dict) -> dict:
        return self.call("/v1/sessions/" + urllib.parse.quote(session_id), "PATCH", fields)

    def label(self, session_id: str, labels: dict[str, str]) -> dict:
        current = self.session(session_id).get("labels") or {}
        return self.patch(session_id, {"labels": {**current, **labels}})


class Kubernetes:
    def __init__(self) -> None:
        root = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount")
        self.token = (root / "token").read_text().strip()
        self.ca = str(root / "ca.crt")
        self.base = "https://kubernetes.default.svc"

    def call(self, path: str, method: str = "GET", data: object | None = None) -> dict:
        import ssl
        body = None if data is None else json.dumps(data).encode()
        request = urllib.request.Request(
            self.base + path, data=body, method=method,
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, context=ssl.create_default_context(cafile=self.ca),
                                        timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            raise ApiError(error.code, path) from error

    def lease(self) -> dict:
        return self.call(LEASE_PATH)

    def put_lease(self, lease: dict) -> dict:
        return self.call(LEASE_PATH, "PUT", lease)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def timestamp(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_timestamp(value: str | None) -> dt.datetime:
    if not value:
        return dt.datetime.fromtimestamp(0, dt.timezone.utc)
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def lease_expired(lease: dict, now: dt.datetime) -> bool:
    spec = lease.get("spec") or {}
    if not spec.get("holderIdentity"):
        return False
    renew = parse_timestamp(spec.get("renewTime"))
    return now >= renew + dt.timedelta(seconds=int(spec.get("leaseDurationSeconds") or LEASE_SECONDS))


def occurrence(sweep: str, now: dt.datetime) -> str:
    _, hour, minute, weekdays = SWEEPS[sweep]
    local = now.astimezone(ZoneInfo("America/New_York"))
    for days_back in range(8):
        date = local.date() - dt.timedelta(days=days_back)
        if date.weekday() not in weekdays:
            continue
        scheduled = dt.datetime.combine(date, dt.time(hour, minute),
                                        ZoneInfo("America/New_York"))
        if scheduled <= local:
            return scheduled.isoformat(timespec="minutes")
    raise SweepError("No scheduled occurrence in the past week")


def update_lease(k8s: Kubernetes, holder: str, annotations: dict[str, str] | None = None,
                 release: bool = False) -> dict:
    for _ in range(5):
        lease = k8s.lease()
        if (lease.get("spec") or {}).get("holderIdentity") != holder:
            raise SweepError("Global sweep lease ownership changed")
        spec = lease["spec"]
        spec["renewTime"] = timestamp(utc_now())
        if release:
            spec["holderIdentity"] = None
        lease.setdefault("metadata", {}).setdefault("annotations", {}).update(annotations or {})
        try:
            return k8s.put_lease(lease)
        except ApiError as error:
            if error.status != 409:
                raise
    raise SweepError("Lease update conflicted repeatedly")


def acquire(k8s: Kubernetes, run_key: str, deadline: float) -> str:
    holder = run_key + ":" + uuid.uuid4().hex[:12]
    while time.monotonic() < deadline:
        lease = k8s.lease()
        spec = lease.setdefault("spec", {})
        existing = spec.get("holderIdentity")
        if existing:
            if lease_expired(lease, utc_now()):
                raise SweepError("Previous sweep lease expired; cleanup must verify the remote run")
            if existing.startswith(run_key + ":"):
                raise SweepError("This occurrence is already running")
            time.sleep(POLL_SECONDS)
            continue
        spec.update({"holderIdentity": holder, "leaseDurationSeconds": LEASE_SECONDS,
                     "acquireTime": timestamp(utc_now()), "renewTime": timestamp(utc_now())})
        lease.setdefault("metadata", {})["annotations"] = {
            "sre.igou.systems/run-key": run_key,
            "sre.igou.systems/session-id": "",
            "sre.igou.systems/cleaned-session-id": "",
        }
        try:
            k8s.put_lease(lease)
            return holder
        except ApiError as error:
            if error.status != 409:
                raise
    raise SweepError("Global sweep gate did not become free before starting deadline")


def assistant_output(items: list[dict], baseline: int) -> str:
    texts = []
    for item in items[baseline:]:
        if item.get("role") != "assistant":
            continue
        for part in item.get("content") or []:
            if part.get("type") == "output_text" and part.get("text"):
                texts.append(part["text"])
    return texts[-1].strip() if texts else ""


def validate_digest(output: str) -> None:
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines or len(lines) > 20:
        raise SweepError("Final digest is empty or exceeds 20 lines")
    if "No live infrastructure changes occurred" not in output:
        raise SweepError("Final digest omits the live-change statement")
    if "all green" in output.lower() and len(lines) != 1:
        raise SweepError("All-green digest must be one line")


def has_prompt(items: list[dict], marker: str) -> bool:
    return any(item.get("role") == "user" and any(
        part.get("type") == "input_text" and marker in part.get("text", "")
        for part in (item.get("content") or [])) for item in items)


def slack_post(token: str, message: str, run_key: str, deadline: float) -> str:
    while time.monotonic() < deadline:
        payload = json.dumps({"channel": SLACK_CHANNEL, "text": message,
                              "client_msg_id": str(uuid.uuid5(uuid.NAMESPACE_URL, run_key))}).encode()
        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage", data=payload, method="POST",
            headers={"Authorization": "Bearer " + token,
                     "Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.load(response)
                if not result.get("ok"):
                    raise SweepError("Slack API rejected the report: " + str(result.get("error", "unknown")))
                return str(result["ts"])
        except urllib.error.HTTPError as error:
            if error.code == 429:
                delay = min(int(error.headers.get("Retry-After", "5")), 60)
                if time.monotonic() + delay < deadline:
                    time.sleep(delay)
                    continue
            raise ApiError(error.code, "/api/chat.postMessage") from error
    raise SweepError("Slack rate limit exceeded report deadline")


def run(sweep: str, manual_id: str | None) -> None:
    omni = Omnigent(os.environ["OMNI_URL"], os.environ["OMNI_CLIENT_ID"],
                    os.environ["OMNI_CLIENT_SECRET"])
    k8s = Kubernetes()
    now = utc_now()
    run_key = SESSION_PREFIX + sweep + "/" + (manual_id or occurrence(sweep, now))
    holder = acquire(k8s, run_key, time.monotonic() + 300)
    session_id = ""
    try:
        found = omni.sessions(run_key)
        if len(found) > 1:
            raise SweepError("Multiple sessions have the same run key")
        if found:
            session_id = found[0]["id"]
            if (found[0].get("labels") or {}).get("sre.run.delivery") == "delivered":
                update_lease(k8s, holder, release=True)
                print(json.dumps({"run": run_key, "session_id": session_id,
                                  "status": "already-delivered"}))
                return
        else:
            agents = omni.call("/v1/agents").get("data", [])
            ids = [agent["id"] for agent in agents if agent.get("name") == "igou-sre"]
            if len(ids) != 1:
                raise SweepError("Exactly one seeded igou-sre agent is required")
            # Creation is non-idempotent. On a transport error, inspect by exact
            # title and fail visibly rather than blindly posting again.
            try:
                created = omni.call("/v1/sessions", "POST", {
                    "agent_id": ids[0], "host_type": "managed",
                    "sandbox_provider": "kubernetes", "title": run_key,
                })
                session_id = created["id"]
            except (ApiError, urllib.error.URLError):
                found = omni.sessions(run_key)
                if len(found) == 1:
                    session_id = found[0]["id"]
                else:
                    raise SweepError("Ambiguous session creation; no retry performed")
        update_lease(k8s, holder, {"sre.igou.systems/session-id": session_id})
        omni.label(session_id, {"sre.run.key": run_key, "sre.run.sweep": sweep})
        # Read-only sharing makes the durable transcript visible to igou.
        omni.call(f"/v1/sessions/{session_id}/permissions", "PUT",
                  {"user_id": "igou", "level": 1})
        ready_until = time.monotonic() + 300
        while time.monotonic() < ready_until:
            snapshot = omni.session(session_id)
            stage = (snapshot.get("sandbox_status") or {}).get("stage")
            if stage == "failed" or snapshot.get("status") == "failed":
                raise SweepError("Managed runner failed before prompt")
            if snapshot.get("sandbox_status") is None and snapshot.get("host_id") and snapshot.get("runner_id"):
                break
            update_lease(k8s, holder)
            time.sleep(POLL_SECONDS)
        else:
            raise SweepError("Managed runner readiness timeout")
        marker = "[igou-sre-run:" + run_key + "]"
        items = omni.items(session_id)
        baseline = next((i for i, item in enumerate(items)
                         if has_prompt([item], marker)), len(items))
        if not has_prompt(items, marker):
            prompt = pathlib.Path("/opt/igou-sre/sweeps", sweep + ".md").read_text()
            prompt = marker + "\n" + prompt
            try:
                omni.call(f"/v1/sessions/{session_id}/events", "POST", {
                    "type": "message", "data": {"role": "user", "content": [
                        {"type": "input_text", "text": prompt}
                    ]},
                })
            except (ApiError, urllib.error.URLError):
                if not has_prompt(omni.items(session_id), marker):
                    raise SweepError("Ambiguous prompt submission; no retry performed")
        turn_until = time.monotonic() + 2100
        while time.monotonic() < turn_until:
            update_lease(k8s, holder)
            snapshot = omni.session(session_id)
            items = omni.items(session_id)
            if snapshot.get("status") == "failed":
                raise SweepError("Model or tool execution failed")
            if snapshot.get("pending_elicitations_count", 0):
                raise SweepError("Agent requested human approval")
            output = assistant_output(items, baseline)
            if has_prompt(items, marker) and output and snapshot.get("status") == "idle":
                break
            omni.wait_event(session_id)
        else:
            raise SweepError("Model turn exceeded its deadline")
        validate_digest(output)
        labels = omni.session(session_id).get("labels") or {}
        if labels.get("sre.run.delivery") == "delivered":
            raise SweepError("Report already delivered")
        if labels.get("sre.run.delivery") == "attempting":
            raise SweepError("Prior Slack delivery is ambiguous; no repost performed")
        omni.label(session_id, {"sre.run.delivery": "attempting"})
        ts = slack_post(os.environ["SLACK_BOT_TOKEN"], output, run_key,
                        time.monotonic() + 180)
        omni.label(session_id, {"sre.run.delivery": "delivered", "sre.run.slack-ts": ts,
                                "sre.run.finished-at": timestamp(utc_now())})
        omni.patch(session_id, {"archived": True})
        # The cleanup-only CronJob verifies the transcript, deletes this host's
        # Job and launch Secret, and acknowledges on the Lease. Do not release
        # the global gate while compute remains.
        cleanup_until = time.monotonic() + 480
        while time.monotonic() < cleanup_until:
            lease = k8s.lease()
            if (lease.get("metadata", {}).get("annotations") or {}).get("sre.igou.systems/cleaned-session-id") == session_id:
                update_lease(k8s, holder, release=True)
                print(json.dumps({"run": run_key, "session_id": session_id,
                                  "slack_ts": ts, "status": "completed"}))
                return
            update_lease(k8s, holder)
            time.sleep(POLL_SECONDS)
        raise SweepError("Managed host cleanup did not finish before deadline")
    except Exception:
        # Leave the Lease held for the cleanup-only Job. It can recover a
        # killed client or failed turn after expiration and keeps new sweeps
        # from starting before the old runner has been inspected.
        if session_id:
            try:
                omni.label(session_id, {"sre.run.failure-at": timestamp(utc_now())})
            except Exception:
                pass
            try:
                delivery = (omni.session(session_id).get("labels") or {}).get("sre.run.delivery")
                if delivery not in ("attempting", "delivered", "failure-attempting"):
                    omni.label(session_id, {"sre.run.delivery": "failure-attempting"})
                    # Failure text is deliberately generic: an API exception
                    # can carry sensitive context, and the transcript has
                    # the detailed evidence for the human reader.
                    slack_post(os.environ["SLACK_BOT_TOKEN"],
                               f"{run_key}: sweep execution failed; inspect Omnigent session {session_id}. No live infrastructure changes occurred.",
                               run_key + ":failure", time.monotonic() + 60)
            except Exception:
                pass
        raise


def cleanup() -> None:
    omni = Omnigent(os.environ["OMNI_URL"], os.environ["OMNI_CLIENT_ID"],
                    os.environ["OMNI_CLIENT_SECRET"])
    k8s = Kubernetes()
    lease = k8s.lease()
    spec = lease.get("spec") or {}
    holder = spec.get("holderIdentity")
    if not holder:
        return
    annotations = lease.get("metadata", {}).get("annotations") or {}
    run_key = annotations.get("sre.igou.systems/run-key", "")
    if not run_key.startswith(SESSION_PREFIX):
        raise SweepError("Lease has an unrecognized run key")
    session_id = annotations.get("sre.igou.systems/session-id") or ""
    if not session_id:
        found = omni.sessions(run_key)
        if len(found) != 1:
            raise SweepError("Cannot prove whether an unrecorded session exists")
        session_id = found[0]["id"]
        update_lease(k8s, holder, {"sre.igou.systems/session-id": session_id})
    snapshot = omni.session(session_id)
    if snapshot.get("title") != run_key or snapshot.get("agent_name") != "igou-sre":
        raise SweepError("Session identity does not match the Lease")
    if not snapshot.get("archived"):
        if not lease_expired(lease, utc_now()):
            return
        omni.patch(session_id, {"archived": True})
    # An archive has a short undo grace and stops the runner, but the direct
    # Kubernetes host remains. Read the transcript before and after reclaim.
    omni.items(session_id)
    host_id = snapshot.get("host_id")
    if not host_id:
        raise SweepError("Session has no managed host ID yet; cleanup will retry")
    path = f"/apis/batch/v1/namespaces/{RUNNER_NAMESPACE}/jobs?" + urllib.parse.urlencode({
        "labelSelector": "omnigent.ai/agent=igou-sre",
    })
    jobs = k8s.call(path).get("items", [])
    matches = []
    for job in jobs:
        containers = job.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        if any(env.get("name") == "OMNIGENT_HOST_ID" and env.get("value") == host_id
               for container in containers for env in container.get("env", [])):
            matches.append(job)
    if len(matches) > 1:
        raise SweepError("More than one Job matches the managed host")
    recorded_job = annotations.get("sre.igou.systems/job-name", "")
    recorded_secret = annotations.get("sre.igou.systems/token-secret", "")
    if matches:
        job = matches[0]
        name = job["metadata"]["name"]
        # The launch token name is from this exact Job's secretKeyRef, never
        # from a wildcard delete or a broad label selector.
        refs = [env["valueFrom"]["secretKeyRef"]["name"]
                for container in job["spec"]["template"]["spec"]["containers"]
                for env in container.get("env", [])
                if env.get("name") == "OMNIGENT_HOST_TOKEN"
                and env.get("valueFrom", {}).get("secretKeyRef")]
        if refs != [name + "-token"]:
            raise SweepError("Job launch-token reference is unexpected")
        if recorded_job and recorded_job != name:
            raise SweepError("Recorded Job identity changed")
        recorded_job, recorded_secret = name, refs[0]
        update_lease(k8s, holder, {"sre.igou.systems/job-name": name,
                                   "sre.igou.systems/token-secret": refs[0]})
    if not recorded_job or recorded_secret != recorded_job + "-token":
        raise SweepError("Cannot identify this host's Job and launch Secret")
    job_path = f"/apis/batch/v1/namespaces/{RUNNER_NAMESPACE}/jobs/{recorded_job}"
    secret_path = f"/api/v1/namespaces/{RUNNER_NAMESPACE}/secrets/{recorded_secret}"
    for resource in (job_path, secret_path):
        try:
            k8s.call(resource, "DELETE", {"propagationPolicy": "Foreground"})
        except ApiError as error:
            if error.status != 404:
                raise
    for _ in range(24):
        try:
            k8s.call(job_path)
        except ApiError as error:
            if error.status == 404:
                break
            raise
        time.sleep(5)
    else:
        raise SweepError("Managed Job did not disappear after deletion")
    omni.items(session_id)
    fresh = omni.session(session_id)
    if not fresh.get("archived"):
        raise SweepError("Conversation was not retained as archived")
    update_lease(k8s, holder, {"sre.igou.systems/cleaned-session-id": session_id},
                 release=lease_expired(lease, utc_now()))
    print(json.dumps({"session_id": session_id, "status": "cleaned"}))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", choices=SWEEPS)
    parser.add_argument("--manual-id")
    parser.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()
    if args.cleanup_only == bool(args.sweep):
        parser.error("pass exactly one of --sweep or --cleanup-only")
    try:
        if args.cleanup_only:
            cleanup()
        else:
            run(args.sweep, args.manual_id)
        return 0
    except (SweepError, KeyError, OSError, urllib.error.URLError) as error:
        print(f"sweep client failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
