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
