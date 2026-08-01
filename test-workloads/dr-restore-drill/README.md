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

## Findings from the first full run (2026-08-01) — read before drilling

1. **`sync` before any manual snapshot.** Round 1 snapshotted seconds
   after unsynced writes: the blocks landed but ext4's metadata was still
   in the guest page cache — every restored file existed with ZERO bytes.
   Crash-consistency is real: for a meaningful manual backup run
   `sync` in the pod (or quiesce the app) before firing the snapshot
   task. The nightly 00:20 cycle mostly catches quiesced apps, but the
   same physics applies.
2. **Protected volumes are delete-blocked.** democratic-csi refuses
   `DeleteVolume` while snapshots exist (`filesystem has dependent
   snapshots`) — deleting a protected PVC leaves the PV `Released` and
   retrying until the snapshots age out (7d) or are destroyed by hand.
   Accidental extra safety; plan teardowns accordingly.
3. **Restored volumes carry the received snapshot** (`zfs recv`
   transfers it). Free local rollback point — and the same
   delete-block applies until it is removed.
4. **Stale replicas accumulate.** After a destroy+recreate cycle the old
   replica still self-describes under the same name; the restore play's
   ambiguity guard refuses (proven live) until the obsolete replica is
   pruned (`zfs destroy -r cold/backups/k8s/<old-uuid>`) or 30d retention
   removes it.
5. **TrueNAS auto-prunes snapshot tasks whose dataset is destroyed** —
   softer than feared; but the replication task's `source_datasets` still
   lists the dead volume until the next converge, which would fail the
   nightly replication ("no matching snapshots"). **Re-converge promptly
   after any allow-list change or protected-volume deletion** (the weekly
   Saturday converge also self-heals this).
6. While a destroyed volume's name is still in the allow-list, the
   converge FAILS its resolution assert (loud, intentional).

## VM-drill addendum (codex-desktop, 2026-08-01)

The same cycle was run against the production Windows 11 VM
(clean-shutdown backup → VM delete under Retain → manifest re-apply →
restore-by-name → bit-perfect boot disk + vTPM + EFI NVRAM → Windows
booted with agent + RDP). Extra findings:

7. **`zfs recv -F` erases the target's LOCAL identity properties** —
   only the stream's *received* (old-name) properties remain, which the
   converge's `-s local` resolution ignores: the restored volume silently
   drops out of protection until re-stamped. The restore play now
   captures and re-applies the target's local identity automatically
   (igou-ansible#471); older restores need a manual `zfs set`.
8. **Retain leaves the share plumbing live**: deleting a Retain PV never
   runs `DeleteVolume`, so the NVMe-oF namespace/subsystem (or NFS
   share) stays wired and `zfs destroy` reports `dataset is busy`.
   Teardown order: `nvmet.namespace.delete` → `nvmet.port_subsys.delete`
   → `nvmet.subsys.delete` (port-bound subsystems refuse deletion), or
   `sharing.nfs.delete`, then destroy.
9. **KubeVirt VMs**: the persistent-state PVC holds **vTPM state** +
   EFI NVRAM keyed by the firmware UUID — save the VM manifest (with
   `firmware.serial`/`uuid`) before deletion, and expect the PVC's name
   suffix to change on recreation (allow-list must follow). Restore
   resolves the *old* stamped name into the *new* PVC's dataset —
   cross-name restore is supported.
