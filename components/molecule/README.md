# Molecule image cache

This component owns the `molecule` test namespace and three shared image feeds
in `openshift-virtualization-os-images`. Disposable VMs belong to their Molecule
run; shared seeds belong to GitOps and survive `molecule destroy`.

| DataSource | Seed input | Local disk |
| --- | --- | --- |
| `centos-stream10-casval` | CentOS Stream 10 container disk registry | 30 GiB |
| `win11-casval` | Existing TrueNAS `win11` golden PVC | 50 GiB |
| `win2k25-casval` | Existing TrueNAS `win2k25` golden PVC | 50 GiB |

Each DataImportCron stores RWO Block data on `lvms-casval`, retains one current
import and updates its stable DataSource after import succeeds. CentOS polls
the registry digest hourly. Windows polls the source PVC **UID** hourly: replace
the golden PVC when publishing a new image; edits to disk bytes in place do not
trigger refresh. Existing TrueNAS goldens and their consumers are preserved.

CDI adds immediate binding to **seed imports**, which have no VM consumer.
The class remains WaitForFirstConsumer; its allowed topology and CDI burst
toleration place these imports on Casval. Test VM DataVolumes use ordinary
consumer binding. Their source and target class/modes match, allowing the
existing `lvms-casval` StorageProfile to choose snapshot clones. Keep seed PVCs
unmounted after import; mounting a source can block snapshot cloning.

The three seeds request 130 GiB of logical space, excluding test writes and
temporary refresh overlap. Thin-pool data and metadata consumption determine
actual headroom. Cache imports wait while Casval is unavailable. A destructive
reprovision loses local data; existing Bound objects are not proof that the
underlying disk survived. Rebuild stale cache imports after reprovisioning.

The `ansible-molecule` service account can inspect the source DataSources/PVCs
and authorize cloning, but cannot mutate shared seeds. No new credential or
Secret store is introduced. Seed DataVolumes are excluded from Velero backups;
the authoritative Windows goldens retain their existing backup policy.

Implementation: [igou-ansible#587](https://github.com/igou-io/igou-ansible/pull/587).
Operational checks, lease handling and reseeding belong in
`igou-docs/ansible-aap/Running, Testing, and Building Ansible Execution Environments.md`.

Primary references: [CDI smart cloning](https://github.com/kubevirt/containerized-data-importer/blob/main/doc/smart-clone.md)
and [DataImportCron controller](https://github.com/kubevirt/containerized-data-importer/blob/main/pkg/controller/dataimportcron-controller.go).
