---
name: hardening-review
description: Review workload privileges and exposure from ACS metadata and propose fixes.
---

1. Focus on running workloads (ACS inactive=false and replicas>0); list idle ones separately. Look at privileged containers, host mounts, added capabilities, privilege escalation, writable root filesystems, seccomp and service-account permissions.

2. Operators and CSI drivers often need elevated privileges; say when that is the case before calling access excessive. UID 0 in a spec is not the user a process actually runs as, and a route or external port does not mean the service is reachable from the Internet.

3. Compare with the previous report by workload and image. Propose narrow changes with their likely impact and how to verify them; never apply them.

For a scheduled run, use the preflight evidence you were given; do not collect
again. Follow the assess skill's read-only and evidence rules, and write the report and Slack reply as
its "Writing reports" section describes. If no earlier report exists, say this
run sets the baseline. Save hardening-review.md in the evidence directory and read it back
before saying it is done. Your final response is the Slack message; do not send
messages yourself or paste raw evidence.
