---
name: scan-coverage
description: Assess freshness, integrity and blind spots in ACS and repository security evidence.
---

1. Check acs_integrity and each source's completeness, reconciled before/after counts, duplicate rows, missing details and cluster last-contact times. Compare sources with the previous scan-coverage report.

2. List missing scan timestamps separately from scans beyond the seven-day heuristic. Group affected workloads by digest where possible; configured scan age is not proof that an image is unsafe.

3. Report unavailable SBOM generation, disabled alert APIs, denied repositories and unknown credential expiry explicitly. Do not launch scans, exports requiring writes, ACS report generation or credential changes.

Follow the assess skill's read-only boundaries and evidence rules. For a scheduled
run, use the verified preflight collection; do not start another collector.
Write scan-coverage.md in the supplied evidence directory and read it back before
claiming completion. A first run establishes a baseline. Keep source failures and
partial coverage explicit. The final response is the scheduler's Slack payload:
status, UTC collection time, key changes, coverage gaps, authenticated dashboard
URL and Files path. Do not send messages yourself or expose raw evidence.

