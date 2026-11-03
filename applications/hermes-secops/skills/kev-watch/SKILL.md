---
name: kev-watch
description: Watch for changed known-exploited CVE exposure in live workloads.
---

1. The native monitor compares all image/workload joins and coverage, using ACS inactive=false and replicas>0 as its live heuristic. Read the supplied baseline/diff. Initial execution establishes a baseline; unchanged later ticks skip the model and Slack delivery.

2. Verify the relevant CISA/vendor advisory and distinguish newly affected workloads, changed digests, removals and degraded scan coverage. Inspect exposure and vendor backports before asserting applicability.

3. Do not claim a KEV match proves this workload is exploitable. Preserve unknowns and report when the KEV feed or ACS inventory is incomplete.

Follow the assess skill's read-only boundaries and evidence rules. For a scheduled
run, use the verified preflight collection; do not start another collector.
Write kev-watch.md in the supplied evidence directory and read it back before
claiming completion. A first run establishes a baseline. Keep source failures and
partial coverage explicit. The final response is the scheduler's Slack payload:
status, UTC collection time, key changes, coverage gaps, authenticated dashboard
URL and Files path. Do not send messages yourself or expose raw evidence.

