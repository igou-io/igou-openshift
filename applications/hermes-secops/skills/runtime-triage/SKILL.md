---
name: runtime-triage
description: Separate source dependency alerts from evidence in deployed container digests.
---

1. Correlate CVE/advisory aliases, package versions, repository SBOMs and deployed image findings. Record the source commit, snapshot time, image digest and scan time. Similar package names alone do not establish a source-to-runtime relationship.

2. Classify findings as confirmed runtime match, repository-only alert or unknown attribution. Separate embedded tools and base-image packages from application dependencies, and respect vendor backports.

3. Verify recommendations against primary advisories. Classify each action as dependency update, tool/vendor update, image rebuild, rollout of a verified rebuilt digest, upstream blocked or investigation. Do not invent fixed tags or open remediation PRs.

Follow the assess skill's read-only boundaries and evidence rules. For a scheduled
run, use the verified preflight collection; do not start another collector.
Write runtime-triage.md in the supplied evidence directory and read it back before
claiming completion. A first run establishes a baseline. Keep source failures and
partial coverage explicit. The final response is the scheduler's Slack payload:
status, UTC collection time, key changes, coverage gaps, authenticated dashboard
URL and Files path. Do not send messages yourself or expose raw evidence.

