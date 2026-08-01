# OADP (Velero) — scheduled app backups to rustfs-cold

Closes the 2026-07-03 post-mortem P1 ("Enable OADP/Velero … targeting
RustFS/S3") and DR-assessment gaps #2/#5: scheduled, app-consistent
backups of namespace objects **and** PV data as one restorable set, stored
off the source pools, with staleness/failure alerting.

## Architecture

- **Operator**: `redhat-oadp-operator`, channel `stable-1.5` (the OCP
  4.21-aligned track, Velero 1.16), namespace `openshift-adp`
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
| `weekly-heavy` | Sat 06:00 | windows-images | 90d |

`jellyfin-media` (1Ti static NFS PV) carries
`velero.io/exclude-from-backup: "true"` — media is not backed up, config
is. To add a namespace, extend the right Schedule; if its PVCs use a
driver other than nvmeof-{ssd,fast,cold}, also add a `*-velero`
VolumeSnapshotClass for that driver (exactly one Velero-labeled class per
driver may exist). comfyui (500Gi, mostly re-downloadable models) is
deliberately out for v1.

## Prerequisites (cross-repo, in order)

1. igou-inventory `host_vars/rustfs-cold.yml`: `velero` bucket + `velero`
   user + `velero_rw` policy → AAP `rustfs_state_converge`.
2. 1Password item `velero-user-rustfs-cold` (username/password) in vault
   `lab_s3`.
3. Merge this app. Verify: `oc -n openshift-adp get dpa oadp -o
   jsonpath='{.status.conditions}'` → Reconciled, and the BSL reports
   `Available`.

## Restore quickstart

```sh
# What exists?
oc -n openshift-adp get backup
# Whole-namespace restore (existing resources are not overwritten):
cat <<EOF | oc create -f -
apiVersion: velero.io/v1
kind: Restore
metadata:
  generateName: restore-
  namespace: openshift-adp
spec:
  backupName: <backup>
  includedNamespaces: ["<ns>"]
EOF
oc -n openshift-adp get restore -w
```

Restored PVCs are recreated from the kopia data via the data mover —
independent of any surviving ZFS state. For selective restores add
`labelSelector`/`includedResources`. Test restores go to a scratch
namespace via `namespaceMapping`.

## Gotchas

- `checksumAlgorithm: ""` on the BSL is mandatory against RustFS (AWS SDK
  CRC32 trailer breaks non-AWS S3).
- The Velero-labeled VolumeSnapshotClasses are additional to the
  democratic-csi-managed ones; the is-default-class annotations there are
  unaffected. Never label a second class for the same driver.
- Schedules fire in UTC; keep clear of 09:00 UTC (etcd backup).
- First runs move full volume data (slow, spinner-bound); later runs are
  kopia-incremental.
- OADP 1.6 (OCP 4.22) drops restic — kopia here is forward-compatible.
