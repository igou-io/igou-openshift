---
name: scaffold-vm
description: Scaffold a KubeVirt VirtualMachine manifest under test-workloads/ with options for instance type, storage, networking (including Multus), and cloud-init SSH configuration.
argument-hint: <vm-name>
allowed-tools: Read, Write, Bash(kustomize build *), Bash(ls *), Bash(cat *), Bash(oc get *), Bash(oc explain *)
---

# Scaffold a KubeVirt VirtualMachine

Scaffold a VirtualMachine workload under `test-workloads/` following the conventions of this repo.

## VM name

The VM to scaffold is: **$ARGUMENTS**

If `$ARGUMENTS` is empty, ask the user for the VM name before proceeding.

## Step 1: Discover available instance types and preferences

Query the cluster for available instance types and OS preferences to offer the user informed defaults:

```bash
oc get virtualmachineclusterinstancetype -o custom-columns=NAME:.metadata.name --no-headers | head -20
```

```bash
oc get virtualmachineclusterpreference -o custom-columns=NAME:.metadata.name --no-headers | head -20
```

```bash
oc get datasource -n openshift-virtualization-os-images -o custom-columns=NAME:.metadata.name --no-headers
```

Report available options to the user alongside the fields to gather.

## Step 2: Gather information

Collect the following. If the user provided details inline, proceed directly. Otherwise ask in a single message.

| Field | Description | Default |
|-------|-------------|---------|
| `vm-name` | VM name and directory name under `test-workloads/virtualmachine-<vm-name>/` | from `$ARGUMENTS` |
| `namespace` | Kubernetes namespace | `<vm-name>` |
| `instance-type` | VirtualMachineClusterInstanceType name | `u1.medium` |
| `os-preference` | VirtualMachineClusterPreference name | `centos.stream10` |
| `os-datasource` | DataSource name for boot volume (from openshift-virtualization-os-images) | `centos-stream10` |
| `disk-size` | Root disk size | `30Gi` |
| `storage-class` | StorageClass for the DataVolume | `lvms-lvm-local-storage-immediate` |
| `run-strategy` | RunStrategy: `Always`, `Halted`, `Manual`, `RerunOnFailure` | `Always` |
| `network-mode` | `pod` (default pod network), `multus-only` (bridge to Multus, no pod network), `pod-and-multus` (both) | `pod` |
| `multus-nad` | Multus NetworkAttachmentDefinition name (required if network-mode includes multus) | — |
| `multus-mac` | Static MAC for Multus interface (optional) | — |
| `create-nad` | Whether to scaffold a NAD in this directory (`yes`/`no`) — only if network-mode includes multus | `no` |
| `nad-config` | If create-nad=yes: CNI type and config (same options as scaffold-test-workload: macvlan/ovn-k-localnet, IPAM, master interface, VLAN) | — |
| `ssh-key` | SSH public key for cloud-init | `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOWgNfV1zdod84sj28d+z7YBLkaD5ZImElWt8zHw+u7/` |
| `cloud-init-user` | Username for cloud-init | `igou` |
| `cloud-init-packages` | Extra packages to install via cloud-init (comma-separated) | `qemu-guest-agent` |

## Step 3: File generation

Create directory `test-workloads/virtualmachine-<vm-name>/` and generate files.

### Conventions
- 2-space indentation
- YAML 1.2 booleans: `true`/`false` only
- File names: `<metadata.name>-<kind>.yaml` (all lowercase, hyphens)
- No `---` prefix on kustomization.yaml

### 1. `<namespace>-namespace.yaml`

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: <namespace>
```

### 2. `<vm-name>-virtualmachine.yaml`

Generate based on network-mode:

#### Pod network only (network-mode=pod):
```yaml
---
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: <vm-name>
  namespace: <namespace>
spec:
  dataVolumeTemplates:
    - metadata:
        name: <vm-name>-volume
      spec:
        sourceRef:
          kind: DataSource
          name: <os-datasource>
          namespace: openshift-virtualization-os-images
        storage:
          resources:
            requests:
              storage: <disk-size>
          storageClassName: <storage-class>
  instancetype:
    kind: virtualmachineclusterinstancetype
    name: <instance-type>
  preference:
    kind: virtualmachineclusterpreference
    name: <os-preference>
  runStrategy: <run-strategy>
  template:
    spec:
      architecture: amd64
      domain:
        devices:
          disks:
            - bootOrder: 1
              name: rootdisk
        resources: {}
      volumes:
        - dataVolume:
            name: <vm-name>-volume
          name: rootdisk
        - cloudInitNoCloud:
            userData: |
              #cloud-config
              users:
                - default
                - name: <cloud-init-user>
                  lock_passwd: true
                  sudo: ALL=(ALL) NOPASSWD:ALL
                  ssh_authorized_keys:
                    - <ssh-key>
              runcmd:
                - ["sudo", "yum", "install", "-y", "<cloud-init-packages-space-separated>"]
                - ["sudo", "systemctl", "start", "qemu-guest-agent"]
          name: cloudinitdisk
```

#### Multus only (network-mode=multus-only):
Same as above but with these changes to `spec.template`:

Add annotations and labels to template metadata:
```yaml
    metadata:
      annotations:
        kubevirt.io/pci-topology-version: v3
      labels:
        network.kubevirt.io/headlessService: headless
```

Set `autoattachPodInterface: false` and add interfaces/networks:
```yaml
      domain:
        devices:
          autoattachPodInterface: false
          disks:
            - bootOrder: 1
              name: rootdisk
          interfaces:
            - bridge: {}
              macAddress: "<multus-mac>"  # omit line entirely if not set
              model: virtio
              name: nic-<vm-name>
              state: up
        machine:
          type: pc-q35-rhel9.6.0
        resources: {}
      networks:
        - multus:
            networkName: <multus-nad>
          name: nic-<vm-name>
      subdomain: headless
```

#### Pod and Multus (network-mode=pod-and-multus):
Keep `autoattachPodInterface` absent (defaults to true), and add both networks:
```yaml
      domain:
        devices:
          disks:
            - bootOrder: 1
              name: rootdisk
          interfaces:
            - masquerade: {}
              name: default
            - bridge: {}
              macAddress: "<multus-mac>"  # omit line entirely if not set
              model: virtio
              name: nic-<vm-name>
              state: up
        resources: {}
      networks:
        - name: default
          pod: {}
        - multus:
            networkName: <multus-nad>
          name: nic-<vm-name>
```

### 3. NAD file (only if create-nad=yes)

Generate the NAD following the same patterns as the scaffold-test-workload skill. File name: `nad-vlan45.yaml` (or `nad.yaml` if no VLAN).

### 4. `kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: <namespace>
resources:
  - <namespace>-namespace.yaml
  # - nad-vlan45.yaml  (if create-nad=yes, include uncommented)
  - <vm-name>-virtualmachine.yaml
```

## Validation

After writing all files, run:
```bash
kustomize build test-workloads/virtualmachine-<vm-name>/
```

If kustomize build fails, diagnose and fix the issue before reporting completion.

## Completion report

After successful validation, report:
1. Files created (list with paths)
2. Kustomize build result
3. How to apply: `oc apply -k test-workloads/virtualmachine-<vm-name>/`
4. How to access: `virtctl ssh <cloud-init-user>@<vm-name> -n <namespace>` (if SSH key configured)
5. How to check status: `oc get vmi -n <namespace>`
