---
name: hardening-review
description: Review workload privilege and exposure using sanitized ACS metadata.
---

1. Select live workloads using ACS inactive=false and replicas>0, showing inactive workloads separately. Inspect privileged containers, host mounts, added capabilities, privilege escalation, writable roots, seccomp and service-account permission metadata.

2. Explain operator/CSI requirements and justified exceptions before calling access excessive. Configured UID 0 is not observed process identity, and configured routes or external ports do not establish public reachability.

3. Compare previous evidence by stable workload identity and container image digest. Recommend narrowly scoped changes with operational impact and verification steps; never apply them.

Follow the assess skill's read-only boundaries and evidence rules. For a scheduled
run, use the verified preflight collection; do not start another collector.
Write hardening-review.md in the supplied evidence directory and read it back before
claiming completion. A first run establishes a baseline. Keep source failures and
partial coverage explicit. The final response is the scheduler's Slack payload:
status, UTC collection time, key changes, coverage gaps, authenticated dashboard
URL and Files path. Do not send messages yourself or expose raw evidence.

