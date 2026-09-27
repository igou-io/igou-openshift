# Storage: democratic-csi + TrueNAS

Layout: TrueNAS pools `fast` (NVMe mirrors) / `ssd` (SATA mirrors,
default SC freenas-nvmeof-ssd-csi) / `cold` (RAIDZ2), each exposed via
iSCSI, NFS and NVMe-oF as separate democratic-csi releases.

1. Controller side first:
   ```bash
   oc get pods -n democratic-csi | grep -v Running
   oc logs -n democratic-csi -l app.kubernetes.io/csi-role=controller --since 1h --tail 100 | grep -i error
   ```
   Known: zvol create intermittently 504s on the TrueNAS API — the
   provisioner retries and succeeds; a single 504 is noise, repeated
   ones for one PVC are not.
2. Object side: `oc describe pvc -n NS NAME | sed -n '/Events:/,$p'`,
   `oc get volumeattachment | grep <pv>`, and the pod's mount events.
3. TrueNAS side: `truenas-ro alert.list`, `truenas-ro pool.query`
   (degraded vdev? capacity?). "dataset is busy" on delete usually means
   a leftover snapshot or an attached initiator; say which and stop.
4. Snapshots: native `freenas-<proto>-<pool>-csi` classes live in the
   source pool (die with it); `-detached` classes are full send/receive
   copies onto `cold` (minutes-per-GiB, not instant — slow is expected).
5. Retain-policy PVs and name-addressed restore paths are documented in
   igou-openshift `docs/runbooks/restore-pvc-from-truenas.md`; link it
   instead of restating it.
