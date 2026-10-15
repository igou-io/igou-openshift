# Molecule image cache

This component owns the `molecule` test namespace and the `casval-image-cache`
ConfigMap in `openshift-virtualization-os-images`. The ConfigMap declares three
local seeds; `igou-ansible/playbooks/openshift/casval_scale.yaml` creates or
refreshes them during lease acquisition. Molecule runs only consume them.

| Stable DataSource | Authoritative shared DataSource | Local disk |
| --- | --- | --- |
| `centos-stream10-casval` | `centos-stream10` | 30 GiB |
| `win11-casval` | `win11` | 50 GiB |
| `win2k25-casval` | `win2k25` | 50 GiB |

No Casval DataImportCron polls while the node is offline. Shared goldens can
continue updating independently; Casval checks their backing PVC UIDs on each
acquisition or renewal. Replacing a shared PVC publishes a new revision; edits
to its bytes in place do not. The local DataVolume name includes a hash of that
UID, so unchanged revisions reuse their completed copies. A new copy must
succeed before acquisition repoints its stable DataSource and collects the old
revision. Refresh failure preserves the last completed revision and removes
unfinished copies. Release removes unfinished cache work before scaling down.

Seeds use RWO Block `lvms-casval` storage with CDI immediate binding, since they
have no VM consumer. The StorageClass stays WaitForFirstConsumer and Casval-only.
Test VM DataVolumes retain ordinary consumer binding and use the existing local
snapshot clone strategy. Keep seed PVCs unmounted after import.

The three seeds request 130 GiB of logical space, excluding test writes and
refresh overlap. A destructive reinstall loses local data: acquisition waits
for LVMS, removes cache metadata predating the new node and recopies the seeds.
It marks the current node UID in `molecule.igou.systems/cache-node-uid` only after
all seeds are ready. Molecule requires this marker before cloning.

Generated DataVolumes, PVCs and DataSources carry
`molecule.igou.systems/image-cache: casval` and a per-seed label. The monthly
Windows-goldens backup excludes this disposable cache while retaining its
existing policy for authoritative Windows images. The `ansible-molecule`
identity can inspect/clone seeds, but cannot mutate them.

## Migration from scheduled feeds

Deploy the companion Ansible change first, then sync this component **without
pruning**. The application's existing auto-prune setting is disabled. Keep it
that way until migration finishes; manually pruning the old DataImportCrons
with `retentionPolicy: None` can delete their seeds and DataSources.

On the next managed acquisition or release, Ansible removes the three legacy
feeds' persisted CDI cleanup and feed labels from seed objects, verifies that
their cleanup selectors are empty, then deletes the feeds with UID and resource
version preconditions. The installed CDI webhook makes the entire cron spec
immutable, including retention and schedule; migration only changes metadata.
Completed seeds survive
migration; acquisition replaces them only after a successful current-source
copy. A release can retire the old feeds and remove pending imports while
Casval remains offline. Do not roll back to the old Ansible implementation or
reintroduce scheduled feeds after migration without restoring their lifecycle.

Operational rollout, lease handling and validation evidence belong in
`igou-docs/ansible-aap/Running, Testing, and Building Ansible Execution Environments.md`.
