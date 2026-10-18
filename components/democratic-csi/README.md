# democratic-csi

Nine Helm releases expose iSCSI, NFS, and NVMe-oF over the fast, ssd, and cold
pools. The cluster overlay adds each release's ExternalSecret driver config.

`values-common.yaml` holds controller and node settings shared by every release:
image pins, log levels, tolerations, controller placement, networking, and
OpenShift privileges. Each chart entry loads it with `valuesFile`; the release's
`valuesInline` holds its driver name, config Secret reference, StorageClass, and
VolumeSnapshotClasses. Lists stay explicit per release because Helm replaces
lists rather than merging individual entries.

Keep chart 0.15.1 and the validated `next@sha256:0f308ae6…` driver pin until a
compatible upgrade is tested. The `c6d7414` image requires TrueNAS 26; the lab
runs 25.10. Renovate's regex manager tracks the two pins in the shared values
file, with image updates disabled by the existing compatibility rule.

The controller liveness patch remains in `kustomization.yaml`. When changing
shared settings, compare renders for both the component and cluster overlay:

```bash
kustomize build --enable-helm components/democratic-csi
kustomize build --enable-helm clusters/ocp/democratic-csi
make test
```

Operational procedures live in [the storage runbook](https://github.com/igou-io/igou-docs/blob/main/storage/Cluster%20Storage%20with%20democratic-csi%20and%20Volume%20Recovery.md).

## NVMe host identities

The three NVMe-oF releases mount separate node-local directories
(`/var/lib/democratic-csi/nvmeof-fast`, `nvmeof-ssd`, and `nvmeof-cold`) at the
driver container's `/etc/nvme`. `DirectoryOrCreate` hides the image's baked-in
`hostnqn` and `hostid`; the pinned driver generates missing files on first
startup and reuses them afterward. The directories persist across pod restarts
and node reboots. Each node and pool has its own identity, and separate pool
directories avoid concurrent initialization by three plugins on a new node.
Do not copy these directories into another node's provisioning image.

This fixes the shared-image identity in
[issue #404](https://github.com/igou-io/igou-openshift/issues/404), also tracked by
[upstream #451](https://github.com/democratic-csi/democratic-csi/issues/451).
It needs no TrueNAS, chart, or driver upgrade and does not use the duplicated
host `/etc/nvme` files. Unique identities alone do not provide exclusive-access
fencing or fix missing-device teardown errors.

The NVMe DaemonSets use `OnDelete`: syncing updates their templates but keeps
existing plugins running. Apply the templates during explicitly authorized
node maintenance, one node at a time. Quiesce storage clients and disconnect
their old TrueNAS controllers before restarting the three plugins; a plugin
restart alone does not change existing kernel connections. Preserve the
generated files on subsequent restarts. Future NVMe plugin updates also require
manual pod replacement while this strategy is configured.

After reconnecting volumes, verify distinct `hostnqn` and `hostid` values across
nodes, agreement between each plugin's files and its active TrueNAS connections,
and healthy consumers. Check iSCSI initiator uniqueness before closing #404.
The full rollout and verification procedure is in the storage runbook linked
above. This is separate from the existing `ctrl-loss-tmo=-1` reconnect mitigation.
