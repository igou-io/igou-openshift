# etcd backup & restore (single-node ocp)

How the nightly etcd backup works, how to restore it in place, and how to
mine a snapshot for cluster state when the cluster itself is gone.
Component: `clusters/ocp/etcd-backup/` (README there covers design
rationale). DR context: `docs/post-mortems/2026-07-31-dr-readiness-assessment.md`
gap #1.

## What exists

- **Nightly at 05:00 US-Eastern**, the `etcd-backup` CronJob on the master
  runs the host's `/usr/local/bin/cluster-backup.sh` and uploads the pair
  of artifacts to rustfs-cold:

  ```
  s3://etcd-backups/<z-stream>/<timestamp>/
    snapshot_<ts>.db                    # etcd snapshot (~1GB; ALL Secrets in plaintext)
    static_kuberesources_<ts>.tar.gz    # static-pod resources + encryption keys
    SHA256SUMS
    COMPLETE                            # provenance manifest; a set is valid iff this exists
  ```

- The newest **2** run dirs also stay on the master under
  `/var/backup/etcd/` — same-disk convenience for quick rollbacks, **not**
  a backup.
- Retention: strict 3-day cap, pruned by the job on successful nights.
- Alerts: `EtcdBackupFailed` (a run failed), `EtcdBackupStale` (no
  success in 36h) — both in the `etcd-backup-stale` AlertingRule in
  openshift-monitoring.
- **A snapshot contains every cluster Secret in plaintext.** Treat the
  bucket and any downloaded copy as secret material; delete local copies
  after use.

## Rule zero: same z-stream

A snapshot restores only onto the exact z-stream it was taken from
(4.21.21 backup → 4.21.21 cluster). Consequences:

- **Take a manual backup immediately after every cluster upgrade** —
  pre-upgrade sets become non-restorable-in-place the moment the upgrade
  completes:

  ```bash
  oc create job --from=cronjob/etcd-backup etcd-backup-post-upgrade-$(date +%Y%m%d) -n etcd-backup
  ```

- The bucket keys are prefixed with the z-stream so you can see at a
  glance which sets are restorable against the running cluster.

## Restore in place (node still boots) — ~15 min

Covers: mass accidental deletion, ArgoCD prune disaster, bad config
change, etcd corruption, z-stream rollback. Does NOT cover a reinstalled
node (see mining, below).

Prerequisites: the **cert-based** admin kubeconfig
(`op://lab_aap/ocp-kubeconfig`, `system:admin` — OAuth tokens die with
the control plane), SSH to the master (`core@ocp.igou.systems`, key via
`ssh-use`), and a backup set from the **same z-stream**.

1. Get a backup dir onto the master. Fast path — the local copy:

   ```bash
   ssh core@ocp.igou.systems 'ls /var/backup/etcd/'
   ```

   Otherwise pull the set from rustfs-cold (from the devcontainer) and
   copy it up:

   ```bash
   podman run --rm -v /tmp/etcd-restore:/out --entrypoint /bin/sh docker.io/rustfs/rc:v0.1.30 -c '
     rc alias set rustfs https://truenas.igou.systems:20292 "$AK" "$SK" >/dev/null
     rc get -r rustfs/etcd-backups/<z-stream>/<ts>/ /out/'   # creds: op://lab_s3/etcd-backups-rustfs-cold
   # verify integrity, then:
   scp -r /tmp/etcd-restore core@ocp.igou.systems:/home/core/backup
   ```

   Verify before restoring: `sha256sum -c SHA256SUMS`, and confirm
   `COMPLETE` exists and its `OCP_VERSION` matches
   `oc get clusterversion`.

2. On the master, run the SNO restore (single script — no quorum steps on
   single-node):

   ```bash
   sudo -E /usr/local/bin/cluster-restore.sh /home/core/backup
   ```

3. Exit SSH and watch recovery (up to ~15 min):

   ```bash
   KUBECONFIG=<cert-based-admin-kubeconfig> oc adm wait-for-stable-cluster
   ```

4. Aftermath: everything created after the snapshot is gone — expect
   ArgoCD to reconverge GitOps-managed state, and check CSI storage:
   VolumeSnapshots/PVs born after the snapshot now have no cluster
   objects (orphaned zvols — see `restore-pvc-from-truenas.md` before
   deleting anything on TrueNAS). CNPG databases keep their own
   Barman timeline; verify cluster health and WAL archiving after
   restore.

## Mining a snapshot when the cluster is gone (total loss)

A fresh install has a new identity — you cannot restore an old snapshot
into it. But the snapshot is still a complete, queryable archive of every
object the dead cluster had: the PV→zvol map for
`restore-pvc-from-truenas.md`, Secrets that never lived in 1Password,
VolumeSnapshotContents pointing at cold-pool datasets, etc.

On the devcontainer (rehearsed for real 2026-07-31 — extracted 55 PVs
from a live snapshot, exactly matching `oc get pv`; the resulting catalog
is at `s3://etcd-backups/catalogs/pv-zvol-catalog-20260731.tsv`, a prefix
the retention prune never touches):

```bash
# 0. download a COMPLETE set (rc runs as non-root by default — --user 0
#    for volume writes) and verify SHA256SUMS before trusting it.

# 1. materialize the snapshot into a local etcd data dir.
#    IMAGE VERSION MATTERS: match the snapshot's etcd major.minor —
#    OCP 4.21 runs etcd 3.6 (backup.env/COMPLETE records it; the job log
#    prints "Server version 3.6.0").
podman run --rm --user 0 -v "$PWD":/w:z --entrypoint /usr/local/bin/etcdutl \
  quay.io/coreos/etcd:v3.6.5 snapshot restore /w/snapshot.db --data-dir /w/etcd-data

# 2. serve it locally
podman run -d --name mine --user 0 -v "$PWD/etcd-data":/etcd-data:z \
  quay.io/coreos/etcd:v3.6.5 etcd --data-dir /etcd-data \
  --listen-client-urls http://127.0.0.1:2379 --advertise-client-urls http://127.0.0.1:2379

# 3. auger (protobuf decoder) — release binaries exist; no Go needed:
curl -sL https://github.com/etcd-io/auger/releases/download/v1.0.3/auger_1.0.3_linux_amd64.tar.gz \
  | tar -xz auger

# 4. the PV→zvol catalog in one pass (PV name, namespace/PVC, SC, zvol):
for k in $(podman exec mine etcdctl get /kubernetes.io/persistentvolumes --prefix --keys-only | grep .); do
  podman exec mine etcdctl get "$k" --print-value-only | ./auger decode | python3 -c "
import sys, yaml
pv = yaml.safe_load(sys.stdin)
c = pv['spec'].get('claimRef') or {}; csi = pv['spec'].get('csi') or {}
print('\t'.join([pv['metadata']['name'], f\"{c.get('namespace','-')}/{c.get('name','-')}\",
                 pv['spec'].get('storageClassName','-'),
                 csi.get('volumeHandle', pv['spec'].get('nfs',{}).get('path','non-csi'))]))"
done > pv-zvol-catalog.tsv

# 5. clean up — the data dir contains every Secret in plaintext
podman rm -f mine && rm -rf etcd-data snapshot.db
```

Key prefixes worth knowing: `/kubernetes.io/persistentvolumes/`,
`/kubernetes.io/persistentvolumeclaims/<ns>/`,
`/kubernetes.io/secrets/<ns>/`,
`/kubernetes.io/snapshot.storage.k8s.io/volumesnapshotcontents/`.

## What this does NOT protect against

- **Reinstalled/wiped node**: restore-in-place is impossible; total-loss
  recovery remains reinstall + GitOps + data reattach
  (`gitops-bootstrap-from-scratch.md`), with this snapshot as the object
  catalog.
- **TrueNAS loss**: the bucket lives on the same chassis as every zvol.
  Off-box replication is tracked follow-up work.
