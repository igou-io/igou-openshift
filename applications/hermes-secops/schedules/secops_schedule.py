"""Native cron preflight: shared evidence and a stable KEV change detector.

Runs in the gateway; collection always runs in the existing isolated terminal.
Slack delivery and execution history belong to Hermes cron, not this script.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import uuid


HOME = Path(os.environ.get("HERMES_HOME", "/opt/data"))
OUTPUT = HOME / "cache/documents"
MAX_AGE = 45 * 60


def verified_snapshot(directory, max_age=MAX_AGE):
    try:
        summary = json.loads((directory / "summary.json").read_text())
        from datetime import datetime, timezone
        finished = datetime.fromisoformat(summary["finished"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - finished).total_seconds()
        if not 0 <= age <= max_age:
            return None
        hashes = json.loads((directory / "sha256.json").read_text())
        for name in ("summary.json", "evidence.json", "report.md", "requests.json"):
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != hashes[name]:
                return None
        return summary
    except (OSError, ValueError, KeyError, TypeError):
        return None


def snapshot():
    """Serialize collectors, reuse verified fresh evidence, and never background."""
    state = HOME / "secops"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state / "collection.lock").open("a") as lock:
        # Cron itself is serialized; this also protects manual preflight invocations.
        fcntl.flock(lock, fcntl.LOCK_EX)
        for directory in sorted(OUTPUT.glob("*/summary.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            if summary := verified_snapshot(directory.parent):
                return directory.parent, summary
        from tools.terminal_tool import terminal_tool, _atexit_cleanup
        task_id = "secops-collection-" + uuid.uuid4().hex[:12]
        try:
            result = json.loads(terminal_tool(
                "flock -n /output/.secops-collect.lock secops-collect --budget-seconds 540",
                timeout=600, background=False, task_id=task_id))
            if result.get("session_id") or result.get("exit_code") not in (0, 2):
                raise RuntimeError("SecOps collection failed or unexpectedly backgrounded; inspect the cron run")
            payload = json.loads(result["output"])
            run_id = Path(payload["report"]).parent.name
            if not run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in run_id):
                raise RuntimeError("Collector returned an invalid run identifier")
            directory = OUTPUT / run_id
            summary = verified_snapshot(directory)
            if summary is None:
                raise RuntimeError("Collector did not publish intact fresh evidence")
            return directory, summary
        finally:
            _atexit_cleanup()


def kev_state(evidence):
    """Inspect every live workload/image join, not the bounded triage examples."""
    kev = set(evidence.get("enrichment", {}).get("kev", {}).get("matched_cves", []))
    by_digest = {}
    for image in evidence.get("images", []):
        by_digest.setdefault(image["digest"], set()).update(
            finding["cve"] for finding in image.get("findings", []) if finding.get("cve") in kev)
    matches = set()
    for workload in evidence.get("workloads", []):
        if workload.get("inactive") is not False or int(workload.get("replicas") or 0) <= 0:
            continue
        for container in workload.get("containers", []):
            digest = container.get("image")
            for cve in by_digest.get(digest, ()):
                exposure = json.dumps(workload.get("ports", []), sort_keys=True)
                matches.add((workload.get("cluster") or "unknown", workload.get("namespace") or "unknown",
                             workload.get("name") or "unknown", digest, cve, exposure))
    return {"live_definition": "ACS inactive=false and replicas>0; not an independent pod check",
            "matches": sorted(matches), "acs_integrity": evidence.get("acs_integrity", "PARTIAL"),
            "kev_complete": evidence.get("enrichment", {}).get("kev_complete", False),
            "missing_scans": sorted(evidence.get("scan_coverage", {}).get("missing", [])),
            "stale_scans": sorted(evidence.get("scan_coverage", {}).get("older_than_seven_days", [])),
            "gaps": sorted(evidence.get("gaps", []))}


def prepare(mode, monitor=False):
    directory, summary = snapshot()
    if monitor:
        # No timestamps or run paths: unchanged exposure must have identical bytes.
        evidence = json.loads((directory / "evidence.json").read_text())
        print(json.dumps(kev_state(evidence), sort_keys=True))
        return
    print(json.dumps({"skill": mode, "evidence_directory": "/output/" + directory.name,
                      "report_path": "/output/" + directory.name + "/" + mode + ".md",
                      "collection_started": summary.get("started"), "collection_finished": summary["finished"],
                      "status": summary.get("status"), "acs_integrity": summary.get("acs_integrity"),
                      "gaps": summary.get("gaps", []),
                      "instructions": "Reuse this verified collection. Read summary.json and selected evidence; do not recollect. "
                      "Write the named report, read it back, then return a concise Slack brief and authenticated report location."}))
