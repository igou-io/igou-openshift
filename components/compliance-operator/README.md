# compliance-operator

Compliance Operator (stable channel) with weekly CIS scans — **observe-only**
(#550): `autoApplyRemediations: false` / `autoUpdateRemediations: false` are
non-negotiable here. CIS-node remediations are MachineConfigs that reboot
nodes, and this is a single-master cluster; any remediation goes through a PR
and a planned reboot window.

- `cis-weekly` ScanSetting: Sundays 09:00 UTC (05:00 ET quiet window), raw
  results 1Gi × 3 rotations on the default StorageClass.
- `cis-igou` TailoredProfile: `ocp4-cis` plus the accepted-risk exemptions
  below.
- `cis` ScanSettingBinding: `cis-igou` (platform, TailoredProfile) +
  `ocp4-cis-node` (master/worker, stock Profile). The binding also triggers an
  initial scan on creation.
- casval is scale-from-zero — node scans cover it only while it exists
  (acceptable; it is ephemeral by design).

Triage of FAILed `ComplianceCheckResult`s → #550: fix via GitOps, exclude via
the TailoredProfile with rationale, or record as accepted risk here.

Footprint: compare `openshift-compliance` p50/p95 against the RHACS #381
baseline after two weekly runs (scans are bursty DaemonSet pods).

## Object naming

Rule and Variable **objects** carry the ProfileBundle prefix — `ocp4-<id>` —
while `ComplianceCheckResult` objects carry the *scan* prefix. `disableRules`
and `setValues` reference the object name, so use `ocp4-…`:

| Object | Name |
|---|---|
| Rule CR | `ocp4-audit-log-forwarding-enabled` |
| Variable CR | `ocp4-var-sccs-with-allowed-capabilities-regex` |
| CheckResult (stock scan) | `ocp4-cis-audit-log-forwarding-enabled` |
| CheckResult (this tailored scan) | `cis-igou-audit-log-forwarding-enabled` |

Binding a TailoredProfile renames the platform scan from `ocp4-cis` to
`cis-igou`, so existing check-result names and scan history do not carry over.

## Tailored: accepted risk

Both are settled decisions from
[igou-inventory#283](https://github.com/igou-io/igou-inventory/issues/283) and
igou-docs `security/Compliance Operator CIS Scans.md` → "Deliberately not
remediated". Applied in `cis-igou-tailoredprofile.yaml`.

| Rule | Tailoring | Why accepted | Ref |
|---|---|---|---|
| `ocp4-scc-limit-container-allowed-capabilities` | `setValues` widens `ocp4-var-sccs-with-allowed-capabilities-regex` | The 12 flagged SCCs (`container-build`, `kubevirt-controller`, `netobserv-ebpf-agent`, 8× `nvidia-*`, `pipelines-scc`) are operator-created and operator-reconciled: edits revert, and narrowing them breaks GPU, virt, NetObserv and Pipelines workloads. Tailoring the variable is the rule's own remediation guidance. Cost: a future over-permissive SCC matching `^nvidia-` is silently accepted. | #283 item 5 |
| `ocp4-audit-log-forwarding-enabled` | `disableRules` | Audit **is** forwarded to Loki; the CLF uses a named `audit-api` input (kubeAPI + openshiftAPI) and the rule only matches the literal `audit` inputRef. The reserved names cannot be reused for a custom input, so scoping and the literal check are mutually exclusive. Reverting to the built-in input also collects auditd + ovn, which previously forced the collector to 8Gi and OOM-killed it. | #283 item 6 |

## Not tailored: still on the remediation plan

These FAIL today and are **deliberately left asserting** — they are pending
decisions with prerequisites, not accepted risk. Exempting them would hide
live findings. Suggested order is #283's 2026-08-25 status comment.

| Rule | Status | Blocker / prerequisite | Ref |
|---|---|---|---|
| `ocp4-ocp-allowed-registries-for-import` | do first | No MCO roll, no reboot. Inventory imagestream source domains first. | #283 item 4 |
| `ocp4-api-server-encryption-provider-cipher` | pending | etcd encryption at rest rewrites every secret and changes the backup/restore contract — confirm `project-etcd-backup-sno` captures `/etc/kubernetes/static-pod-resources/` keys first. | #283 item 2 |
| `ocp4-kubeadmin-removed` | pending | Irreversible. Verify the `igou` HTPasswd cluster-admin login and the `system:admin` fallback immediately before deleting the secret. | #283 item 1 |
| `ocp4-ocp-allowed-registries` | pending | Writes CRI-O policy through the MCO: **every node reboots**. An incomplete allowlist blackholes pulls, and the failure is delayed. Needs a maintenance window. | #283 item 3 |
| `ocp4-configure-network-policies-namespaces` | project | 22 namespaces without a NetworkPolicy, half operator-owned. All-or-nothing rule, so partial coverage does not clear it. To be split into its own issue. | #283 item 7 |

To exempt one later, add a `disableRules` entry (`name: ocp4-<rule-id>`, plus a
`rationale`) to `cis-igou-tailoredprofile.yaml` and record the decision in the
table above and in igou-docs.

## Why the `NonCompliant` alert still fires

The TailoredProfile clears two of the nine `ocp4-cis` FAILs. The suite reports
the worst result across all its scans, so
`compliance_operator_compliance_state{name="cis"} > 0` stays true while:

- the five rules above still FAIL on the platform scan, and
- `ocp4-cis-node-worker` reports **INCONSISTENT** — a single-master artifact.
  The control-plane node also carries the `worker` role, so it joins the worker
  scan pool and PASSes master-only file-ownership checks that the real workers
  mark NOT-APPLICABLE. Nothing is wrong on the nodes. Fixing it means either
  accepting it or excluding the control-plane node from the worker scan, which
  the `roles:` field of `ScanSetting` cannot express.

So closing igou-inventory#482 needs more than this component: finish the
remediation plan, or null-route the alert for `name="cis"` (pattern from #649).
