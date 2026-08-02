# Restore applications from OADP/Velero backups

## Purpose

Restore namespace objects + PV data from the OADP scheduled backups
(`clusters/ocp/oadp`, live since 2026-08-02) — the primary restore path
for every namespace in the `daily-apps` / `daily-platform` /
`weekly-heavy` schedules. Backups are self-contained kopia repos in
`s3://velero/ocp/` on rustfs-cold; restores work on the same cluster or a
freshly rebuilt one and depend on **no** surviving ZFS state.

All commands drill-verified 2026-08-02 (sands-of-time: backup → scratch-ns
restore → data intact).

> ⚠️ CLI trap: bare `oc get backup`/`restore` resolve to **CNPG's** CRDs.
> Always `backups.velero.io` / `restores.velero.io`.

## Inspect what exists

```sh
oc -n openshift-adp get backups.velero.io          # newest per schedule = your RPO
oc -n openshift-adp get backupstoragelocation      # must be Available
oc -n openshift-adp describe backups.velero.io <name>   # errors/warnings/items
```

RPO: daily schedules 08:00/08:30 UTC (30d retention), weekly Sat 06:00
UTC (90d). Backups with `PartiallyFailed` can still be restorable — check
whether the failure was a hook (e.g. hermes fsfreeze, #636 — data moved,
crash-consistent) or a failed DataUpload (volume data missing).

## Whole-namespace restore (app lost / namespace deleted)

```sh
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
oc -n openshift-adp get restores.velero.io -w
```

- Existing resources are **not overwritten** — for a clean restore of a
  half-broken namespace, delete the namespace first (or restore
  selectively with `labelSelector`/`includedResources`).
- PVC data comes back through the node-agent (`DataDownload` CRs, watch
  `oc -n openshift-adp get datadownloads.velero.io`).
- On a rebuilt cluster: ArgoCD owns the namespace manifests. Either let
  GitOps create the namespace/app first and restore only the PVCs + data
  (`includedResources: persistentvolumeclaims`), or restore first and let
  ArgoCD adopt — for apps whose Deployment mounts the PVC by name both
  orders work; prefer GitOps-first so labels/quotas match git.

## Drill / test restore (no impact on the live app)

```sh
cat <<EOF | oc create -f -
apiVersion: velero.io/v1
kind: Restore
metadata:
  generateName: drill-
  namespace: openshift-adp
spec:
  backupName: <backup>
  namespaceMapping:
    <ns>: oadp-drill
EOF
# verify, then: oc delete ns oadp-drill
```

Note the restored app RUNS (duplicate of production) — verify and delete
promptly.

## VMs (hermes, windows-images)

The kubevirt plugin restores VirtualMachine + DataVolume + PVC as a unit.
For a lost VM: restore the namespace; the VM comes back stopped or per
its runStrategy. Caveats:

- hermes backups are crash-consistent until #636 is fixed (guest fsfreeze
  fails); XFS/ext4 journal replay applies on first boot.
- A Velero VM restore has **not** been drilled yet. The proven VM
  restore path remains ZFS restore-by-name
  (`restore-pvc-from-truenas.md`) while pre-removal replicas last;
  vTPM/EFI (`persistent-state-*` PVC) restores were proven bit-perfect on
  the ZFS path, unproven on the Velero path.

## Databases (CNPG namespaces)

CNPG Barman (`s3://cnpg-backups/`) is the authoritative DB restore —
point-in-time, WAL-continuous (`cnpg-barman-recovery.md`). The OADP
backups of forgejo etc. include the PG PVCs only as a crash-consistent
second copy. Restoring a whole namespace that contains a CNPG `Cluster`
CR will start CNPG reconciliation against restored PVCs — prefer:
GitOps-recreate the app, Barman-recover the database, Velero-restore only
the non-DB PVCs.

## Troubleshooting

- **BSL not Available**: check `cloud-credentials` secret (ESO,
  `velero-user-rustfs-cold` in `lab_s3`), rustfs-cold reachable at
  `truenas.igou.systems:20292`, and that `checksumAlgorithm: ""` is still
  set (RustFS rejects AWS SDK checksum trailers).
- **Backup stuck `WaitingForPluginOperations`**: DataUploads in flight —
  large first-run moves are spinner-bound; check
  `datauploads.velero.io` progress.
- **Restore Completed with warnings**: usually already-exists on
  cluster-scoped resources — benign; read
  `oc -n openshift-adp describe restores.velero.io <name>`.
- **Velero internals**: `oc -n openshift-adp logs deploy/velero`; node
  agent: `oc -n openshift-adp logs ds/node-agent`.
- Alerts (`VeleroBackupFailed`/`PartiallyFailed`/`*Stale`) are defined in
  `clusters/ocp/oadp/oadp-backup-alerts-prometheusrule.yaml`; the
  staleness alerts use `absent()` and fire while OADP has never completed
  a scheduled run.

## Relation to the other layers

| Layer | Restores | Runbook |
|---|---|---|
| OADP (this) | app namespaces + PV data, scheduled | this file |
| etcd-backup | cluster/control-plane state | `etcd-backup-restore.md` |
| CNPG Barman | databases, point-in-time | `cnpg-barman-recovery.md` |
| ZFS restore-by-name | single volumes via `k8s:*` stamps (manual snapshot first) | `restore-pvc-from-truenas.md` |
| zvol archaeology | anything else that survived | `zfs-snapshot-rescue.md` |
