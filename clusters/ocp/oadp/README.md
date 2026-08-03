# OADP (Velero) — scheduled app backups to rustfs-cold

Closes the 2026-07-03 post-mortem P1 ("Enable OADP/Velero … targeting
RustFS/S3") and DR-assessment gaps #2/#5: scheduled, app-consistent
backups of namespace objects **and** PV data as one restorable set, stored
off the source pools, with staleness/failure alerting.

**Live since 2026-08-02** (OADP 1.5.7). Drill-verified same day: a
sands-of-time backup (66 items, 1.3GB through the data mover) restored via
`namespaceMapping` into a scratch namespace with data intact. Restores:
see `docs/runbooks/oadp-restore.md`.

## Architecture

- **Operator**: `redhat-oadp-operator`, channel `stable` — the 4.21
  catalog's only channel, pinned to the 4.21-aligned OADP 1.5.x / Velero
  1.16 track — namespace `openshift-adp`
  (`components/redhat-oadp-operator`).
- **Data flow**: backup → CSI `VolumeSnapshot` (local ZFS snapshot via the
  `*-velero` VolumeSnapshotClasses) → node-agent **kopia data mover**
  uploads the snapshot contents to `s3://velero/ocp/` on rustfs-cold →
  snapshot deleted. Nothing long-lived stays on the source pool, and the
  backup is a self-contained kopia repo on the cold spinners
  (`defaultSnapshotMoveData: true` on the DPA).
- **VM backups**: the `kubevirt` plugin coordinates VirtualMachine /
  DataVolume / PVC so the hermes VM restores as a unit (guest-agent
  freeze when available, else crash-consistent).
- **Relation to existing layers**: etcd-backup covers cluster state; CNPG
  Barman covers databases point-in-time; the `-detached` snapshot classes
  and TrueNAS replication cover volumes at the ZFS layer. OADP is the
  app-level layer that ties Kubernetes objects + volume data together and
  is restorable onto a *rebuilt* cluster.

## Schedules (cron in UTC)

| Schedule | When | Namespaces | TTL |
|---|---|---|---|
| `daily-apps` | 08:00 (04:00 ET) | forgejo, gitea-mirror, grafana, hermes, sands-of-time, ntfy, gotify, n8n, searxng, jellyfin | 30d |
| `daily-platform` | 08:30 | ansible-automation-platform (Fernet key!), stackrox | 30d |
| `weekly-heavy` | Sat 06:00 | windows-images, comfyui, openshift-virtualization-os-images | 90d |

`jellyfin-media` (1Ti static NFS PV) and `comfyui-models` (200Gi of
re-downloadable weights) carry `velero.io/exclude-from-backup: "true"`.
To add a namespace, extend the right Schedule; if its PVCs use a driver
other than nvmeof-{ssd,fast,cold}, also add a `*-velero`
VolumeSnapshotClass for that driver (exactly one Velero-labeled class per
driver may exist).

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

- **hermes fsfreeze (#636)**: KubeVirt stamps every virt-launcher pod with
  `pre.hook.backup.velero.io/command = virt-freezer --freeze` (in-tree,
  unconditional, not in git and not configurable), and Velero defaults an
  annotation hook to `onError: Fail`. On hermes that hook fails. `qemu-ga`
  runs as root but in SELinux domain `virt_qemu_ga_t`, which the targeted
  policy grants **no `capability` permissions at all**, so it cannot fall
  back on `dac_read_search` to open `/home/hermes/.hermes` — mode `0700`
  `hermes:hermes`, under a `/home/hermes` that is also `0700`
  (`hermes_home_mode` in igou-inventory `group_vars/hermes.yml`). `/`
  freezes fine because it is world-traversable, but
  `guest-fsfreeze-freeze` is all-or-nothing: one unopenable mount aborts
  the whole call, so nothing is frozen.
  Data movement still completes; the VM disks are crash-consistent (the
  same consistency the retired ZFS snapshot layer had), and hermes state
  additionally has an application-consistent tarball from igou-ansible
  `playbooks/hermes/backup.yml`. But a `PartiallyFailed` backup never
  publishes `velero_backup_last_successful_timestamp`, so with `hermes` in
  `daily-apps` both `VeleroBackupPartiallyFailed` **and**
  `VeleroDailyBackupStale` (via its `absent()` arm) fire permanently.
  The fix is guest-side, in igou-ansible `playbooks/hermes/setup-os.yml`
  (+ igou-inventory `group_vars/hermes.yml`): either ship a local SELinux
  module granting `virt_qemu_ga_t self:capability dac_read_search`, which
  keeps both directories at `0700`, or make the mount reachable by root —
  `/home/hermes` `0711` (traverse, still no listing) and
  `/home/hermes/.hermes` owned `root:hermes` mode `0770`.

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
