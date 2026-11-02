"""Transport fixtures exercise evidence correctness without cluster credentials."""

import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


loader = importlib.machinery.SourceFileLoader("collector", str(Path(__file__).with_name("secops-collect")))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


def fixture_collector():
    with patch.dict(module.os.environ, {}, clear=True):
        return module.Collector(page_size=2)


class InventoryTests(unittest.TestCase):
    def test_distinct_image_references_with_same_digest_are_not_duplicate_rows(self):
        collector = fixture_collector()
        collector.acs = unittest.mock.Mock(side_effect=[
            (200, {"count": 2}),
            (200, {"images": [{"id": "sha256:a", "name": "image:tag"}, {"id": "sha256:a", "name": "image@sha256:a"}]}),
            (200, {"images": []}), (200, {"count": 2}),
        ])
        result = collector.inventory("images")
        self.assertTrue(result["complete"])
        self.assertEqual(result["unique"], 2)
        self.assertEqual(result["unique_digests"], 1)
        self.assertEqual(result["alias_references"], 1)
        self.assertEqual(result["duplicates"], 0)

    def test_duplicate_boundary_retries_and_reconciles(self):
        collector = fixture_collector()
        collector.acs = unittest.mock.Mock(side_effect=[
            (200, {"count": 3}), (200, {"images": [{"id": "a"}, {"id": "b"}]}),
            (200, {"images": [{"id": "b"}]}), (200, {"count": 3}),
            (200, {"count": 3}), (200, {"images": [{"id": "a"}, {"id": "b"}]}),
            (200, {"images": [{"id": "c"}]}), (200, {"count": 3}),
        ])
        result = collector.inventory("images")
        self.assertTrue(result["complete"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual({x["id"] for x in result["items"]}, {"a", "b", "c"})

    def test_persistent_duplicates_cannot_claim_complete(self):
        collector = fixture_collector()
        collector.acs = unittest.mock.Mock(side_effect=[
            (200, {"count": 3}), (200, {"images": [{"id": "a"}, {"id": "b"}]}),
            (200, {"images": [{"id": "b"}]}), (200, {"count": 3}),
        ] * 2)
        result = collector.inventory("images")
        self.assertFalse(result["complete"])
        self.assertEqual(result["duplicates"], 1)
        self.assertTrue(collector.gaps)

    def test_count_churn_cannot_claim_complete(self):
        collector = fixture_collector()
        collector.acs = unittest.mock.Mock(side_effect=[
            (200, {"count": 1}), (200, {"images": [{"id": "a"}]}), (200, {"count": 2}),
        ] * 2)
        self.assertFalse(collector.inventory("images")["complete"])

    def test_denied_api_is_not_empty_success(self):
        collector = fixture_collector()
        collector.acs = unittest.mock.Mock(return_value=(403, None))
        self.assertFalse(collector.inventory("deployments")["complete"])

    def test_empty_valid_inventory(self):
        collector = fixture_collector()
        collector.acs = unittest.mock.Mock(side_effect=[
            (200, {"count": 0}), (200, {"images": []}), (200, {"count": 0}),
        ])
        self.assertTrue(collector.inventory("images")["complete"])


class TransportTests(unittest.TestCase):
    def test_redirect_never_forwards_authorization(self):
        collector = fixture_collector()
        collector.github = unittest.mock.Mock(side_effect=[
            (201, {"sbom_url": "https://api.github.com/repos/igou-io/igou-docs/dependency-graph/sbom/fetch-report/id"}, {}),
            (202, None, {}),
            (302, None, {"Location": "https://storage.example/export?signed=private"}),
        ])
        collector.request = unittest.mock.Mock(return_value=(200, {"packages": []}, {}))
        with patch.object(module.time, "sleep"):
            self.assertEqual(collector.sbom("igou-io/igou-docs", "secret-token"), {"packages": []})
        self.assertNotIn("headers", collector.request.call_args.kwargs)
        self.assertEqual(collector.request.call_args.args[0], "github:sbom-download")

    def test_fetch_report_must_match_repository_and_api_host(self):
        for url in ("https://evil.example/export", "https://api.github.com/repos/other/repo/dependency-graph/sbom/fetch-report/id"):
            collector = fixture_collector()
            collector.github = unittest.mock.Mock(return_value=(201, {"sbom_url": url}, {}))
            with self.assertRaises(module.CollectionError):
                collector.sbom("igou-io/igou-docs", "secret-token")

    def test_download_rejects_insecure_or_private_origin(self):
        for url in ("http://storage.example/file", "https://127.0.0.1/file", "https://central.stackrox.svc/file", "https://user:pass@storage.example/file"):
            with self.assertRaises(module.CollectionError):
                module.public_https(url)

    def test_rate_limit_retry_is_bounded_and_log_excludes_url_and_token(self):
        collector = fixture_collector()
        from urllib.error import HTTPError
        collector.public.open = unittest.mock.Mock(side_effect=lambda *a, **kw: (_ for _ in ()).throw(
            HTTPError("https://storage.example/?signature=secret", 429, "secret", {}, None)))
        with patch.object(module.time, "sleep"):
            status, _, _ = collector.request("download", "https://storage.example/?signature=secret",
                                             headers={"Authorization": "secret-token"})
        self.assertEqual(status, 429)
        self.assertEqual(collector.public.open.call_count, 3)
        self.assertNotIn("secret", json.dumps(collector.requests))


class EvidenceTests(unittest.TestCase):
    def test_summary_counts_cve_and_workload_once_per_digest(self):
        finding = {"cve": "CVE-2026-1", "severity": "CRITICAL_VULNERABILITY_SEVERITY", "fixed_by": "2"}
        container = {"image": "digest", "security_context": {"privileged": True}, "volumes": []}
        result = module.summarize({"status": "PARTIAL", "started": "start", "finished": "end", "gaps": [],
                                   "images": [{"digest": "digest", "scan_time": None, "findings": [finding, finding]}],
                                   "workloads": [{"id": "one", "ports": [{"exposure": "ROUTE"}], "containers": [container, container]}]})
        example = result["triage_image_examples"][0]
        self.assertEqual((example["unique_cves"], example["critical_cves"], example["fixable_cves"], example["workload_count"]), (1, 1, 1, 1))
        self.assertEqual(result["hardening"]["privileged_workloads"], 1)

    def test_alias_details_fetched_once_and_names_preserved(self):
        collector = fixture_collector()
        collector.acs = unittest.mock.Mock(return_value=(200, {"id": "digest", "name": {"fullName": "image:tag"}}))
        result = collector.details("images", [{"id": "digest", "name": "image:tag"}, {"id": "digest", "name": "image@digest"}])
        self.assertEqual(collector.acs.call_count, 1)
        self.assertEqual(result[0]["references"], ["image:tag", "image@digest"])

    def test_vanished_workload_is_an_explicit_gap(self):
        collector = fixture_collector()
        collector.acs = unittest.mock.Mock(return_value=(404, None))
        self.assertEqual(collector.details("deployments", [{"id": "gone"}]), [])
        self.assertIn("ACS deployments detail reads incomplete", collector.gaps)

    def test_no_environment_values_or_alert_messages_in_workload_evidence(self):
        data = {"id": "workload", "containers": [{"name": "app", "config": {"env": [{"value": "private-token"}], "uid": "0"},
                "securityContext": {"privileged": True}}]}
        result = module.Collector.workload(data)
        self.assertNotIn("private-token", json.dumps(result))
        self.assertEqual(result["containers"][0]["configured_uid"], "0")

    def test_missing_scan_is_preserved(self):
        result = module.Collector.image({"id": "digest", "name": {"fullName": "image"}})
        self.assertIsNone(result["scan_time"])
        self.assertEqual(result["findings"], [])

    def test_osv_uses_only_versioned_coordinates_and_keeps_positional_mapping(self):
        collector = fixture_collector()
        collector.request = unittest.mock.Mock(side_effect=[
            (200, {"results": [{}, {"vulns": [{"id": "GHSA-test"}], "next_page_token": "next"}]}, {}),
            (200, {"results": [{"vulns": [{"id": "GHSA-next"}]}]}, {}),
            (200, {"id": "GHSA-next", "aliases": []}, {}),
            (200, {"id": "GHSA-test", "aliases": []}, {}),
        ])
        result = collector.osv([{"purls": ["pkg:pypi/a@1", "pkg:pypi/b@2", "pkg:rpm/openssl@1", "pkg:npm/no-version"]}])
        self.assertTrue(result["complete"])
        self.assertEqual(result["matches"], [{"purl": "pkg:pypi/b@2", "advisory_ids": ["GHSA-next", "GHSA-test"]}])
        request = collector.request.call_args_list[0].kwargs["data"]
        self.assertEqual(request, {"queries": [{"package": {"purl": "pkg:pypi/a@1"}}, {"package": {"purl": "pkg:pypi/b@2"}}]})

    def test_bad_osv_result_count_is_incomplete(self):
        collector = fixture_collector()
        collector.request = unittest.mock.Mock(return_value=(200, {"results": []}, {}))
        self.assertFalse(collector.osv([{"purls": ["pkg:pypi/a@1"]}])["complete"])

    def test_artifacts_are_private_and_existing_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            evidence = {"status": "PARTIAL", "started": "start", "finished": "end", "gaps": ["source denied"]}
            module.write_artifacts(directory, evidence, [])
            for target in directory.iterdir():
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                module.write_artifacts(directory, evidence, [])


if __name__ == "__main__":
    unittest.main()
