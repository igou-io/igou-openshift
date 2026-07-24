# compliance-operator

Compliance Operator (stable channel) with weekly CIS scans — **observe-only**
(#550): `autoApplyRemediations: false` / `autoUpdateRemediations: false` are
non-negotiable here. CIS-node remediations are MachineConfigs that reboot
nodes, and this is a single-master cluster; any remediation goes through a PR
and a planned reboot window.

- `cis-weekly` ScanSetting: Sundays 09:00 UTC (05:00 ET quiet window), raw
  results 1Gi × 3 rotations on the default StorageClass.
- `cis` ScanSettingBinding: `ocp4-cis` (platform) + `ocp4-cis-node`
  (master/worker). The binding also triggers an initial scan on creation.
- casval is scale-from-zero — node scans cover it only while it exists
  (acceptable; it is ephemeral by design).

Triage of FAILed `ComplianceCheckResult`s → #550: fix via GitOps, exclude via
`TailoredProfile` with rationale, or record as accepted risk here.

Footprint: compare `openshift-compliance` p50/p95 against the RHACS #381
baseline after two weekly runs (scans are bursty DaemonSet pods).
