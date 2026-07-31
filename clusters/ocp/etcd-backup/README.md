# etcd-backup

Nightly `cluster-backup.sh` on the single master (05:00 US-Eastern),
uploaded to the `etcd-backups` bucket on rustfs-cold, keyed
`<z-stream>/<timestamp>/`. Closes DR-assessment gap #1
(`docs/post-mortems/2026-07-31-dr-readiness-assessment.md`). Restore and
snapshot-mining procedures: `docs/runbooks/etcd-backup-restore.md`.

Design notes (the non-obvious bits):

- **hostNetwork + hostPID are required** — `cluster-backup.sh` targets
  `localhost:2379` and chroot does not change namespaces. The
  NetworkPolicies here are therefore *inert* (OVN-K does not enforce
  netpol on host-network pods) and exist as documented intent; the real
  controls are the SCC binding and the bucket-scoped `etcd-backups_rw`
  policy in igou-inventory `host_vars/rustfs-cold.yml`.
- **RHACS**: the privileged-container / sensitive-host-mount / secret-in-env
  SecurityPolicies are scoped to the `cluster-apps` project, so this
  namespace is intentionally out of their scope — no exclusion needed.
- **Retention is strict 3 days, job-side** (no bucket ILM — RustFS marks
  ILM enforcement "under testing"). The prune only runs on successful
  nights, so a failure streak leaves stale sets until the next success —
  and conversely, after a multi-day failure streak few sets survive the
  cap. A set is valid iff its `COMPLETE` marker exists (written last,
  deleted first).
- **The local copies under `/var/backup/etcd` on the master are a
  convenience** for "I fat-fingered a CRD", not a backup — they live on
  the exact disk whose destruction is the scenario this component exists
  for. Newest 2 run dirs are kept (~2GiB).
- **Alerting**: failures → platform `KubeJobFailed` (failed Jobs persist
  ~5 nights; no ttlSecondsAfterFinished, deliberately). Staleness →
  `EtcdBackupStale` AlertingRule in `openshift-monitoring` (>36h without
  a success).
- **Take a manual backup immediately after every cluster upgrade** —
  restores must be same-z-stream, so pre-upgrade sets become
  non-restorable-in-place the moment the upgrade completes:
  `oc create job --from=cronjob/etcd-backup etcd-backup-post-upgrade -n etcd-backup`
- **Known SPOF**: the backup lands on the same TrueNAS chassis that holds
  every zvol. It protects against cluster/etcd loss, not storage-box
  loss; a second off-box target is tracked follow-up work.
