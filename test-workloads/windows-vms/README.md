# Windows VMs on OpenShift Virtualization (testing)

Unattended install + verification of the full Microsoft Evaluation Center ISO
library on the `ocp` cluster (CNV 4.21.10). Design: igou-io/igou-openshift#380.

All seven editions were deployed and verified booting on OpenShift (each reached
`AgentConnected=True` with the guest OS reported by qemu-guest-agent):

| VM name              | Edition (install.wim index)                        | Preference   |
|----------------------|----------------------------------------------------|--------------|
| `winsrv2025`         | Server 2025 Standard Eval, Desktop Experience (2)  | windows.2k25 |
| `winsrv2022`         | Server 2022 Standard Eval, Desktop Experience (2)  | windows.2k22 |
| `winsrv2019`         | Server 2019 Standard Eval, Desktop Experience (2)  | windows.2k19 |
| `winsrv2016`         | Server 2016 Datacenter Eval, Desktop Experience (2)| windows.2k16 |
| `win11-25h2`         | Windows 11 Enterprise Eval 25H2 (1)                | windows.11   |
| `win11-ltsc2024`     | Windows 11 Enterprise LTSC 2024 (1)                | windows.11   |
| `win11-iot-ltsc2024` | Windows 11 IoT Enterprise LTSC 2024 (1)            | windows.11   |

Of these, only **`winsrv2025` (latest Server)** and **`win11-25h2` (latest
desktop)** are kept live on the cluster as GitOps-managed DataVolumes
(`datavolumes.yaml`). The rest were verified once and are re-imported on demand
for testing (see below).

> **Reviewer note — this is not (yet) a hands-free `oc apply -k`.** The install is
> partly imperative and hit several issues during the first run. The
> [Gaps & known issues](#gaps--known-issues) section below documents every one and
> **distinguishes issues that were transient to the storage backend at the time
> (now resolved) from issues native to Windows-on-KubeVirt that will recur** on
> any run. Read that before reproducing.

## What's git-managed here

- `namespace.yaml` — the `windows-images` namespace.
- `datavolumes.yaml` — **only two** CDI DataVolumes, the standing library kept
  live on the cluster: the **latest Server** (`iso-winserver2025-eval-noprompt`)
  and the **latest desktop** (`iso-win11-25h2-enterprise-eval-noprompt`). Both
  point at the **`-noprompt` remastered media** — the "Press any key to boot from
  CD" prompt is compiled into the shipped `cdboot.efi`, so the remaster swaps in
  Microsoft's shipped-but-undocumented `efisys_noprompt.bin`/`cdboot_noprompt.efi`
  so EFI VMs enter Setup hands-free (feedstock for igou-ansible's declarative
  `build_windows_golden.yml`; produced by
  `playbooks/truenas/publish_windows_isos.yml`). Each imports over HTTP from
  `public.igou.systems` onto the **cold pool over NFS** (`freenas-nfs-cold-csi`) —
  bulk read-mostly ISOs belong on cold RAIDZ2, and NFS gives RWX so several test
  VMs can share one ISO cdrom. Applied via `kustomization.yaml`:
  `oc apply -k test-workloads/windows-vms/`. The ISOs are published on
  `public.igou.systems` (hydrated from the igounas archive), so these imports
  resolve as-is.

Deliberately **not** GitOps-managed:
- The other five editions (older Server, Win11 LTSC/IoT). They were all verified
  (table above) but are not kept live. To work with one, publish it to
  `public.igou.systems` and `virtctl image-upload` / add a throwaway DataVolume on
  demand — see the repro and `examples/`.
- Installer/build VMs — inherently imperative (they need the CD-boot prompt caught
  on first boot), so they live in `examples/`, not the kustomization. Those
  scripts (`vm-template.yaml`, `autounattend.*.xml`, `autoboot.py`, `boot-vm.sh`)
  are kept on purpose: they are the hands-on debugging/testing kit for any edition.

## The install pattern (`examples/`)

- **`vm-template.yaml`** — parameterized VM (`@@NAME@@`, `@@PREFERENCE@@`,
  `@@ISOPVC@@`). Key choices:
  - Applies the `windows.*` ClusterPreference for hyper-v enlightenment, q35,
    clock, disk/NIC model — but sets `tpm: {}` and `firmware.bootloader.efi`
    explicitly so vTPM/EFI state is **non-persistent**. Non-persistent NVRAM
    lives in the virt-launcher for the life of the VMI and survives guest
    reboots, so the install completes; only a full VM stop/start resets it (which
    then leaves the disk un-bootable — see Gaps). For durable state, merge #417
    (`HyperConverged.spec.vmStateStorageClass`) and switch the preference's
    persistent defaults back on.
  - `cpu: {sockets: 2, cores: 1}` — the `windows.11` client preference *requires*
    the 2 vCPUs presented as sockets; `sockets:1/cores:2` fails admission.
  - `nodeAffinity NotIn truenas-w1` — keeps VMs off the TrueNAS-hosted worker.
    Note this uses the **short hostname** `truenas-w1` (its `kubernetes.io/hostname`
    label), not the FQDN — see #420.
  - rootdisk uses the cluster default StorageClass (`freenas-nvmeof-ssd-csi`).
- **`autounattend.server.xml` / `autounattend.client.xml`** — fully unattended:
  wipes disk 0, GPT EFI+MSR+Windows partitions, selects the edition by
  `/IMAGE/INDEX`, skips OOBE, auto-logon, and a FirstLogonCommand that installs
  the virtio-win guest tools (drivers + qemu-ga) so KubeVirt reports
  `AgentConnected` + `guestOSInfo` — the verification signal. The client variant
  creates a local admin account and adds the Win11 NRO / hardware-check bypasses.
  No `<ProductKey>` element (see Gaps). Sentinels `@@INDEX@@`, `@@HOSTNAME@@`, and
  `@@ADMINPW@@` are substituted at apply time — the admin/auto-logon password is
  **not** committed (injected via `sed` in step 2, see repro). Delivered as a
  KubeVirt `sysprep` volume from a ConfigMap keyed `autounattend.xml`.
- **`autoboot.py`** — presses Enter while the guest framebuffer is dark to catch
  the "Press any key to boot from CD" prompt, stops when the blue Setup screen
  appears (exit 0), or gives up on the gray UEFI Front Page (exit 1).
- **`boot-vm.sh`** — **the reliable driver.** `autoboot.py` alone is a timing
  gamble; this wrapper force power-cycles the VM and retries `autoboot.py` until
  Setup appears. Use this, not bare `autoboot.py`.

> **`-noprompt` media makes the keypress dance unnecessary.** The standing
> DataVolumes (`iso-*-noprompt`) boot straight into Setup with no "Press any key"
> prompt, so `autoboot.py`/`boot-vm.sh` are **not needed** when a VM attaches one
> of them. The keypress kit is kept only for **pristine** (un-remastered) ISOs —
> e.g. an on-demand edition uploaded straight from the Evaluation Center that
> still carries the prompt-compiled `cdboot.efi`.

### Reproduce one edition (hands-free path, works today)

```sh
cd test-workloads/windows-vms

# 1. ISO PVC. datavolumes.yaml (HTTP import) needs #333 first; until then upload:
virtctl image-upload dv iso-winserver2025-eval -n windows-images --size 9Gi \
  --image-path winserver2025-eval-en-us.iso \
  --uploadproxy-url https://cdi-uploadproxy-openshift-cnv.apps.ocp.igou.systems --insecure

# 2. autounattend ConfigMap (INDEX per the table above; 2 = Server Std Desktop,
#    1 = the Win11 client editions). Use autounattend.client.xml for win11-*.
#    @@ADMINPW@@ is the local admin/auto-logon password — injected here so it is
#    never committed to git (keeps GitGuardian green). Supply your own:
read -rsp 'VM admin password: ' ADMINPW; echo
sed -e 's/@@INDEX@@/2/' -e 's/@@HOSTNAME@@/winsrv2025/' -e "s/@@ADMINPW@@/$ADMINPW/g" \
    examples/autounattend.server.xml > /tmp/au.xml
oc create configmap winsrv2025-unattend -n windows-images --from-file=autounattend.xml=/tmp/au.xml
rm -f /tmp/au.xml   # scrub the rendered file; the password lived in it

# 3. VM
sed -e 's/@@NAME@@/winsrv2025/g' -e 's/@@PREFERENCE@@/windows.2k25/g' \
    -e 's/@@ISOPVC@@/iso-winserver2025-eval/g' examples/vm-template.yaml | oc apply -f -

# 4. catch the CD-boot prompt (retries until Setup — do NOT use bare autoboot.py)
examples/boot-vm.sh winsrv2025 5901

# 5. verify (after install + first logon + guest-tools install, ~15-20 min)
oc get vmi winsrv2025 -n windows-images \
  -o jsonpath='{.status.conditions[?(@.type=="AgentConnected")].status} {.status.guestOSInfo.prettyName}'
```

For `win11-iot-ltsc2024` there is one extra **manual** step during OOBE — see the
IoT entry in Gaps.

## Gaps & known issues

Everything below was hit during the first end-to-end run. Grouped by whether it
is **native to Windows-on-KubeVirt** (expect it every time) or was **transient to
the degraded TrueNAS storage backend at the time** (fixed; won't recur on a
healthy pool — confirmed by a later full Server 2025 install that provisioned +
installed + verified cleanly on `freenas-nvmeof-ssd-csi`).

### A. Native to Windows / KubeVirt — will recur, handled by this PR

1. **CD-boot prompt must be caught per install.** Windows install media prints
   "Press any key to boot from CD or DVD"; headless, it times out and the VM
   drops to no-boot. Needs `boot-vm.sh` (power-cycle + retry `autoboot.py`).
   Inherent to the media on any UEFI VM; unrelated to storage. *Handled:*
   `boot-vm.sh` committed.
2. **Empty `<ProductKey>` breaks older Server eval Setup.** With
   `<ProductKey><Key></Key></ProductKey>`, Server 2016/2019/2022 eval Setup fails
   with *"Windows cannot find the Microsoft Software License Terms."* Eval media
   uses `ei.cfg`, so no key is needed — the element must be **absent**.
   *Handled:* removed from both autounattend files.
3. **`windows.11` preference requires 2 vCPUs as sockets.** `sockets:1/cores:2`
   fails admission (`insufficient CPU resources of 1 vCPU provided as sockets`).
   *Handled:* `sockets:2/cores:1` in the template.
4. **Non-persistent EFI/vTPM survives guest reboots but not VM stop/start.** The
   install (many guest reboots) completes fine, but a full stop/start resets
   NVRAM and the installed disk becomes un-bootable. This is the deliberate
   trade-off to avoid depending on #417; documented so nobody stops a verified
   VM expecting it to come back. Real fix: #417 + persistent EFI/TPM.
5. **Client OOBE bypass is required for Win11.** Local admin account +
   `HideOnlineAccountScreens` + `BypassNRO` + LabConfig hardware-check bypasses,
   or 24H2/25H2 OOBE demands a network/Microsoft account. *Handled:*
   `autounattend.client.xml`.
6. **Guest agent needs the virtio-win guest tools installed in-guest.** Without
   the FirstLogonCommand that runs `virtio-win-guest-tools.exe`, qemu-ga never
   starts and `AgentConnected` stays false — i.e. no verification signal.
   *Handled:* FirstLogonCommand in both autounattend files.
7. **`win11-iot-ltsc2024` needs a manual OOBE fix (edition-specific).** IoT
   Enterprise LTSC — and only that edition; 25h2 and ltsc2024 with the identical
   autounattend did not — fails OOBE with *"The computer restarted unexpectedly
   or encountered an unexpected error."* This reproduced on healthy local
   storage, so it is **not** a storage issue; it is an IoT-edition/OOBE quirk.
   **Manual recovery** (done over VNC): at the error dialog press **Shift+F10**,
   then in the cmd window run
   `reg add HKLM\SYSTEM\Setup\Status\ChildCompletion /v setup.exe /t REG_DWORD /d 3 /f`,
   `exit`, then click **OK** to reboot — OOBE then resumes and the VM verifies.
   *Not yet automated* (would need an autounattend/SetupComplete change to avoid
   the error, or a scripted VNC keystroke recovery). Reviewer TODO if IoT LTSC is
   a recurring target.

### B. Transient to the storage backend at the time — resolved, won't recur

These stemmed from the TrueNAS/democratic-csi backend being driven into a
degraded state by ~a day of heavy concurrent volume create/delete churn during
the first run. After a change to the ssd pool they no longer occur; a subsequent
full Server 2025 install on `freenas-nvmeof-ssd-csi` provisioned in ~56s and
installed cleanly with zero CSI errors.

1. **nvme-oF `CreateVolume` wedged** — `AxiosError` / `operation locked` /
   `DeadlineExceeded`; PVCs never bound. Root contributor is almost certainly the
   **duplicate NVMe host NQN across nodes** that igou-io/igou-openshift **#409**
   fixes. *Resolved by the ssd-pool change; #409 still recommended.*
2. **democratic-csi controllers OOM-killed (27×)** under concurrent provisioning.
   Restarting the controller pods cleared stuck locks/backoff (temporary relief).
3. **Stale RWO `VolumeAttachment`s / multi-attach** after force power-cycling or
   force-deleting VMs — the degraded CSI failed to detach, blocking the next
   launcher. On a healthy backend, force ops detach cleanly.
4. **NFS-backed install crawl / qemu monitor lock** — installing to an NFS
   rootdisk on the degraded pool caused I/O timeouts and libvirt monitor-lock
   warnings; installs crawled (>1 hr). *Note:* NFS is inherently slower than
   block for install write I/O, but the **timeouts** were storage degradation.
   Prefer a block SC (`freenas-nvmeof-ssd-csi`, the default here) for rootdisks.
5. **`casval-worker` autoscaled 0→1** — the cluster-autoscaler read the
   storage-blocked `cdi-upload-prime` pods as needing compute. It scaled back to
   0 once the stuck pods were cleared. Downstream of the storage wedge.
6. **LVMS local-storage fallback.** While TrueNAS was degraded, the last VMs were
   installed with rootdisk + ISO on **`lvms-lvm-local-storage`** (topolvm, local
   NVMe on `ocp`) to bypass TrueNAS entirely — fast and reliable. Not needed now
   that the pool is fixed, but it is a good fallback when the shared backend is
   unhealthy. (Local storage is `ocp`-only and node-pins the VM.)

### C. Prerequisites (cluster config, not this workload)

1. **#420 — MERGED, required.** The `truenas-w1` node exclusion in the HCO used
   the FQDN `truenas-w1.igou.systems`, but the node's `kubernetes.io/hostname`
   label is the short name `truenas-w1`, so the exclusion never matched. This let
   virt-handler *and CDI importer/uploader pods* schedule onto that flaky node,
   where the CDI pods failed their readiness probe and **stalled ISO uploads**.
   HCO propagates placement to CDI, so this one-line fix corrects it. Must be
   present to reproduce.
2. **#409 — open, recommended.** Unique NVMe host NQN per node; likely the root
   of the nvme-oF `CreateVolume` wedging under load (B.1).
3. **#417 — open, optional.** `HyperConverged.spec.vmStateStorageClass`; only
   needed if you want persistent EFI/vTPM (durable across VM stop/start).
