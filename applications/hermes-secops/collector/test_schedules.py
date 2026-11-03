"""Exercise shared-evidence freshness, integrity and complete KEV comparison."""

from datetime import datetime, timedelta, timezone
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


source = Path(__file__).parents[1] / "schedules/secops_schedule.py"
spec = importlib.util.spec_from_file_location("secops_schedule", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def snapshot_files(root, age=0):
    summary = {"finished": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
               "status": "PARTIAL", "acs_integrity": "COMPLETE"}
    hashes = {}
    for name, content in (("summary.json", json.dumps(summary)), ("evidence.json", "{}"),
                          ("report.md", "coverage is partial"), ("requests.json", "[]")):
        (root / name).write_text(content)
        hashes[name] = hashlib.sha256(content.encode()).hexdigest()
    (root / "sha256.json").write_text(json.dumps(hashes))
    return summary


class SnapshotTests(unittest.TestCase):
    def test_partial_but_intact_fresh_evidence_is_reusable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = snapshot_files(root)
            self.assertEqual(module.verified_snapshot(root), expected)

    def test_stale_future_corrupt_and_incomplete_evidence_are_not_reused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for age in (3000, -300):
                snapshot_files(root, age)
                self.assertIsNone(module.verified_snapshot(root))
            snapshot_files(root)
            (root / "evidence.json").write_text("tampered")
            self.assertIsNone(module.verified_snapshot(root))
            snapshot_files(root)
            (root / "report.md").unlink()
            self.assertIsNone(module.verified_snapshot(root))

    def test_fresh_cache_avoids_terminal_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "output/run"
            directory.mkdir(parents=True)
            snapshot_files(directory)
            with patch.object(module, "HOME", root), patch.object(module, "OUTPUT", root / "output"):
                self.assertEqual(module.snapshot()[0], directory)


class KevTests(unittest.TestCase):
    def evidence(self):
        return {"acs_integrity": "COMPLETE", "enrichment": {"kev_complete": True,
                "kev": {"matched_cves": ["CVE-2026-1234"]}}, "images": [
                    {"digest": "digest", "findings": [{"cve": "CVE-2026-1234"}]}],
                "workloads": [{"cluster": "ocp", "namespace": "app", "name": "live",
                               "inactive": False, "replicas": 1, "ports": [],
                               "containers": [{"image": "digest"}]}]}

    def test_all_live_joins_are_compared_not_bounded_examples(self):
        evidence = self.evidence()
        evidence["workloads"] *= 30
        self.assertEqual(len(module.kev_state(evidence)["matches"]), 1)
        for replicas, inactive in ((0, False), (1, True), (1, None)):
            evidence = self.evidence()
            evidence["workloads"][0].update(replicas=replicas, inactive=inactive)
            self.assertFalse(module.kev_state(evidence)["matches"])

    def test_new_workload_exposure_or_lost_coverage_changes_monitor(self):
        evidence = self.evidence()
        baseline = module.kev_state(evidence)
        evidence["workloads"][0]["ports"] = [{"exposure": "EXTERNAL"}]
        self.assertNotEqual(module.kev_state(evidence), baseline)
        evidence = self.evidence()
        evidence["enrichment"]["kev_complete"] = False
        self.assertNotEqual(module.kev_state(evidence), baseline)
        evidence = self.evidence()
        evidence["scan_coverage"] = {"missing": ["digest"]}
        self.assertNotEqual(module.kev_state(evidence), baseline)

    def test_timestamps_and_duplicate_aliases_do_not_trigger_notifications(self):
        evidence = self.evidence()
        baseline = module.kev_state(evidence)
        evidence.update(started="later", finished="later")
        evidence["enrichment"]["kev"]["dateReleased"] = "later"
        evidence["images"] *= 2
        self.assertEqual(module.kev_state(evidence), baseline)


if __name__ == "__main__":
    unittest.main()
