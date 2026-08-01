# dr-restore-drill

A repeatable disaster-recovery drill for the name-addressed volume
protection stack (`docs/runbooks/restore-pvc-from-truenas.md`, "Restore by
NAME first"). A trivial stateful app (HTTP server over a PVC) is deployed,
protected, destroyed, and restored from its cold replica — proving the
whole chain an operator would rely on after real data loss.

First executed end-to-end 2026-08-01.

## Procedure

1. **Deploy**: `oc apply -k test-workloads/dr-restore-drill` and wait for
   the rollout. The PVC's zvol is auto-stamped with `k8s:*` identity
   properties by democratic-csi.
2. **Protect**: add to `igou-inventory group_vars/truenas.yml` →
   `truenas_k8s_protected_volumes`:
   `{cluster: ocp, namespace: dr-restore-drill, pvc: drill-data}`,
   merge, then launch AAP JT `truenas_configure_snapshots`.
3. **Seed + back up**: write checksummed data into `/data` via the app
   pod; record the sha256. Fire the volume's snapshot task
   (`midclt call pool.snapshottask.run <id>`) and the replication
   (`midclt call --job replication.run <k8s-valuable-to-cold id>`), or
   wait for the nightly 00:20 cycle. Verify the replica under
   `cold/backups/k8s/<pvc-uuid>` carries the identity properties.
4. **Destroy**: `oc delete namespace dr-restore-drill`. The PVC is
   Delete-reclaimed → the source zvol is destroyed. The cold replica
   survives (that is the point).
5. **Restore** (the runbook's flow): re-apply step 1 (fresh PVC, new
   UUID, auto-stamped with the same name) → scale `drill-app` to 0 →
   launch AAP JT `truenas_restore_volume` with
   `volume_cluster=ocp volume_namespace=dr-restore-drill
   volume_pvc=drill-data target_dataset=ssd/k8s/vols/<new pvc-uuid>` —
   with the source gone it resolves to the cold replica → scale to 1 →
   the app serves the pre-destruction data; verify the sha256.
6. **Clean up**: remove the allow-list entry + re-converge, then delete
   the stale per-volume snapshot task for the destroyed dataset
   (`midclt call pool.snapshottask.delete <id>` — the converge play
   creates/updates but does not prune), destroy the drill replica under
   `cold/backups/k8s/`, and `oc delete -k` the workload.

## Known sharp edges (by design / discovered in the first run)

- While the destroyed volume's name is still in the allow-list, the
  weekly converge FAILS its resolution assert (loud, intentional) —
  do step 6's allow-list removal promptly.
- Allow-list removals do not prune the per-volume snapshot task on
  TrueNAS; delete it manually (step 6).
- If the old PV lingers `Released` (destroy retry), the restore play
  refuses the ambiguous name until the zvol clears.
