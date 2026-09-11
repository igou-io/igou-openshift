# OADP (Velero) — scheduled app backups to rustfs-cold

Closes the 2026-07-03 post-mortem P1 ("Enable OADP/Velero … targeting
RustFS/S3") and DR-assessment gaps #2/#5: scheduled backups of namespace
objects **and** PV data as one restorable set, stored off the source pools,
with staleness/failure alerting.

**Live since 2026-08-02**; the cluster currently runs OpenShift 4.22.10
with OADP 1.6.1. Drill-verified on 2026-08-02: a
sands-of-time backup (66 items, 1.3GB through the data mover) restored via
`namespaceMapping` into a scratch namespace with data intact. Restores:
see `docs/runbooks/oadp-restore.md`.

## Architecture

- **Operator**: `redhat-oadp-operator`, channel `stable` — the OpenShift
  4.22-aligned OADP 1.6 / Velero 1.18 track — namespace `openshift-adp`
  (`components/redhat-oadp-operator`).
- **Data flow**: CSI PVCs use a `VolumeSnapshot` (local ZFS snapshot via the
  `*-velero` VolumeSnapshotClasses) → node-agent **kopia data mover** →
  `s3://velero/ocp/` on rustfs-cold → snapshot deletion. The shared static
  NFS books volume is the exception: kopia reads it from the running Shelfmark
  pod through Velero file-system backup. Nothing long-lived stays on the
  source pool, and both paths produce self-contained kopia data in the backup
  repository (`defaultSnapshotMoveData: true` on the DPA).
- **Load control**: OADP 1.6 `nodeAgent.loadConcurrency` keeps one active
  load per node and only one unprocessed load in the global preparation
  queue. This bounds the snapshot-clone staging work admitted ahead of
  node-agent processing without serializing transfers already running on
  different nodes.
- **VM backups**: the `kubevirt` plugin coordinates VirtualMachine /
  DataVolume / PVC so each Hermes VM restores as a unit (guest-agent
  freeze when available, else crash-consistent).
- **Relation to existing layers**: etcd-backup covers cluster state; CNPG
  Barman covers databases point-in-time; the `-detached` snapshot classes
  and TrueNAS replication cover volumes at the ZFS layer. OADP is the
  app-level layer that ties Kubernetes objects + volume data together and
  is restorable onto a *rebuilt* cluster.

## Schedules (cron in UTC)

| Schedule | When | Namespaces | TTL |
|---|---|---|---|
| `daily-apps` | 08:00 (04:00 ET) | forgejo, gitea-mirror, grafana, hermes-sre, hermes-assistant, hermes-developer, sands-of-time, gotify, searxng, jellyfin, calibre-web, shelfmark | 30d |
| `daily-platform` | 08:30 | ansible-automation-platform (Fernet key!), stackrox | 30d |
| `weekly-heavy` | Sat 06:00 | comfyui, openshift-virtualization-os-images | 90d |

`jellyfin-media` (1Ti static NFS PV) and `comfyui-models` (200Gi of
re-downloadable weights) carry `velero.io/exclude-from-backup: "true"`.
The static NFS `books` export is intentionally included once through the
running Shelfmark pod's `backup.velero.io/backup-volumes` annotation. The
scaled-to-zero Calibre-Web Deployment mounts the same export but carries no
annotation. Both applications' dynamic config PVCs use CSI snapshot data
movement.
To add a namespace, extend the right Schedule; if its PVCs use a driver not
covered by the five existing `*-velero` VolumeSnapshotClasses, add one for
that driver (exactly one Velero-labeled class per driver may exist).

These schedules supersede the TrueNAS name-addressed snapshot/replication
schedules (`truenas_k8s_protected_volumes` in igou-inventory) — those are
removed in favor of OADP. ZFS identity stamping, the Retain patches, and
the `truenas_restore_volume` JT remain as the archaeology/prevention
layer.

## Prerequisites (cross-repo — all provisioned 2026-08-02)

Recorded for rebuilds; all in place today:

1. igou-inventory `host_vars/rustfs-cold.yml`: `velero` bucket + `velero`
   user + `velero_rw` policy → AAP `rustfs_state_converge` (JT 78).
2. 1Password item `velero-user-rustfs-cold` (username/password) in vault
   `lab_s3` — must exist **before** the converge (the role never generates
   secrets).
3. Sync this app. Verify: `oc -n openshift-adp get dpa oadp -o
   jsonpath='{.status.conditions}'` → Reconciled, and
   `backupstoragelocation default` reports `Available`.

## Restores

See `docs/runbooks/oadp-restore.md` (drill-verified commands: inspect
backups, whole-namespace restore, scratch-namespace drill via
`namespaceMapping`, VM notes, troubleshooting).

## Known issues

- **TrueNAS staging instability (2026-09-07 through 2026-09-10)**:
  `daily-apps` repeatedly completed `PartiallyFailed` when its large initial
  DataUpload burst hit TrueNAS API timeouts, democratic-csi operation locks,
  and occasional clone-size `AlreadyExists` conflicts. OADP then reported
  `timeout on preparing data upload`; only 4 of 14 volume uploads completed
  on the 2026-09-10 run. The explicit one-entry preparation queue is the
  declarative mitigation. Keep CSI snapshot data movement for its point-in-
  time semantics and validate the next scheduled run before treating the
  incident as resolved.
- A `PartiallyFailed` backup does not publish
  `velero_backup_last_successful_timestamp`, so the 36-hour stale alert also
  fires. Treat those two alerts as one backup failure, not separate incidents.

## Gotchas

- `oc get backup`/`restore` resolve to **CNPG's** CRDs — always use
  `backups.velero.io` / `restores.velero.io`.

- `checksumAlgorithm: ""` on the BSL is mandatory against RustFS (AWS SDK
  CRC32 trailer breaks non-AWS S3).
- The Velero-labeled VolumeSnapshotClasses are additional to the
  democratic-csi-managed ones; the is-default-class annotations there are
  unaffected. Never label a second class for the same driver.
- Schedules fire in UTC; keep clear of 09:00 UTC (etcd backup).
- First runs move full volume data (slow, spinner-bound); later runs are
  kopia-incremental.
- OADP 1.6 (OCP 4.22) drops restic — kopia here is forward-compatible.
