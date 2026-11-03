---
name: security-brief
description: Summarize actionable changes in the environment since the last security brief.
---

1. Find the previous security-brief.md and its collection directory. If none exists, label this a baseline. Compare finding identities by digest and CVE, not raw totals or image tags.

2. Lead with five evidence-backed priorities. Distinguish new exposure, persistent findings, verified removals and loss of visibility. A missing image or source is not a resolved vulnerability without comparable coverage.

3. Separate fix availability from fix deployment. Include the affected workload, image digest, advisory, confidence and the operator's next decision.

Follow the assess skill's read-only boundaries and evidence rules. For a scheduled
run, use the verified preflight collection; do not start another collector.
Write security-brief.md in the supplied evidence directory and read it back before
claiming completion. A first run establishes a baseline. Keep source failures and
partial coverage explicit. The final response is the scheduler's Slack payload:
status, UTC collection time, key changes, coverage gaps, authenticated dashboard
URL and Files path. Do not send messages yourself or expose raw evidence.

