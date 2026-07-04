## Agent-based reinstall, netboot pin safety & worker re-join

Operational runbook derived verbatim from the 2026-07-03 `ocp.igou.systems` cluster-destruction incident and its recovery. Every command, host, and path below is what was actually used (or, where noted, the durable fix that replaced it). Cluster is a **single control-plane OpenShift 4.21.9** cluster: control plane `ocp.igou.systems` (MS-01, `10.10.9.10`); workers `hpg5.igou.systems` (`10.10.9.240`, bare metal) and `truenas-w1` (`10.10.9.21`, a KubeVirt/KVM VM on TrueNAS, VM id `5` / `5_truenasw1`); `p330` is permanently dark (no BMC — excluded from all rejoin).

---

### Purpose

Reinstall the MS-01 control plane from agent-based PXE artifacts after a catastrophic wipe, **without falling into the reinstall loop** that the netboot infrastructure creates, and re-join the two workers. It documents the exact failure mode (a stale rb5009 per-host netboot pin defaulting to `install-openshift`), how to regenerate the agent-install PXE assets and publish them to the public nginx, how to flip the per-host pin to `default local` mid-install to break the loop, and the two distinct worker re-join methods (bare-metal PXE vs. KubeVirt-VM node-image ISO) plus correct CSR approval.

---

### When to use

- The MS-01 control-plane disk has been wiped / the cluster is unrecoverable (etcd overwritten) and you must reinstall RHCOS + OpenShift from scratch via the agent-based PXE flow.
- You need to re-join `hpg5` and/or `truenas-w1` to a freshly reinstalled cluster.
- **Preventatively**: after ANY agent-based install, to confirm the per-host pin default is `local` (not `install-openshift`/`ocp-node`) so an unattended reboot can never re-trigger an install.

Do NOT use this to rebuild GitOps, restore PVs, or restore databases — those are separate runbooks. This one stops at "all 3 nodes `Ready`".

---

### Prerequisites

- Ansible control node with the two repos checked out: `/workspace/igou-ansible` and `/workspace/igou-inventory`. Both local checkouts may be STALE — reconcile with `git fetch origin main` and read canonical files via `git show origin/main:<path>`.
- The agent-install role `david-igou.openshift_agent_install` is available to `playbooks/openshift/agent-install/deploy_pxe_assets.yml`.
- **Pull secret**, recovered out-of-band. During the incident it was pulled off the live installer host into the scratchpad before the wipe completed; it also lands inside the freshly generated `cluster-manifests/`. You need it as a literal because 1Password/Connect/ESO all ran ON the destroyed cluster and were dead.
- SSH to rb5009 (RouterOS): `ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes igou@rb5009.igou.systems -p 3480`. File push for pins used `scp -O igou+cet1024w@rb5009.igou.systems:netboot/per-host/<file>`.
- SSH to nodes/TrueNAS for read-only inspection (agent SSH cannot sign here — use the local key with `SSH_AUTH_SOCK=` unset):
  - `SSH_AUTH_SOCK= ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=accept-new core@10.10.9.10` (or `core@hpg5.igou.systems`, `core@10.10.9.21`)
  - `SSH_AUTH_SOCK= ssh -i ~/.ssh/id_ed25519 truenas_admin@truenas.igou.systems`
- `KUBECONFIG` — once the install produces one, use ONLY the file the install wrote:
  `export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig` (never anything under `~/.kube`, all stale).

---

### Root cause — how the stale rb5009 netboot pin caused the disaster

Understand this before touching anything; the whole runbook is shaped around not repeating it.

- MS-01 is **netboot-first by firmware**: UEFI BootOrder is `PXE I226-V → PXE I226-LM → disk LAST`, with a 3-second timeout. Every power event tries PXE first.
- rb5009 owns DHCP+TFTP. Its per-host pin `flash:/netboot/per-host/MAC-5847ca77098a.ipxe` (MS-01 NIC MAC `58:47:ca:77:09:8a`) presented an iPXE menu whose **default-on-timeout was `install-openshift` on a 30-second timer** (`choose --timeout 30000 --default install-openshift target`). That pin had been armed since the 2026-05-11 netboot migration and simply never disarmed.
- On an unattended reboot (~17:00 UTC), MS-01 PXE-booted, hit its pin, the 30s timer expired to `install-openshift`, and the agent-based installer **auto-wiped the 990 PRO NVMe** and started a fresh install. etcd/cluster state was overwritten → old cluster unrecoverable. (PV zvols on TrueNAS were untouched.)
- **The loop**: agent-based install itself reboots mid-flight. With the pin still defaulting to `install-openshift` and firmware still netboot-first, each mid-install reboot re-PXEs, re-hits the pin, times out to `install-openshift` again, and **restarts the install** — forever. The install can never reach "boot from disk."

The two independent controls that must both be respected: (1) firmware is netboot-first and won't be changed, so (2) the **pin default is the safety interlock** — it must be `local` at all times except during a deliberate install, and must be flipped back to `local` the instant the install is underway.

---

### Step-by-step

All Ansible invocations use the dual-inventory form (localhost is in inventory, so it must be passed explicitly):

```
-i 'localhost ansible_connection=local,' -i igou-inventory/inventory.yaml
```

#### Phase 1 — Regenerate agent-install PXE artifacts

Work dir the role uses: `~/openshift-agent-install/ocp/`. Play 1 wipes it fresh, renders manifests, produces `cluster-manifests/auth/{kubeconfig,kubeadmin-password}` and `cluster-manifests/boot-artifacts/`. Play 2 publishes boot-artifacts to the public nginx.

1. Put the recovered pull secret (and any other normally-1Password-sourced vars) into a literal override file, e.g. `~/scratchpad/override.yml`, so no live `op` lookups are attempted.

2. Run the deploy, **skipping the `op-save` tag** (the 1Password item-create + kubeconfig-CA-strip block) because Connect was on the dead cluster:

```
cd /workspace/igou-ansible
ansible-playbook playbooks/openshift/agent-install/deploy_pxe_assets.yml \
  -i 'localhost ansible_connection=local,' \
  -i igou-inventory/inventory.yaml \
  -e target_cluster=ocp \
  -e @~/scratchpad/override.yml \
  --skip-tags op-save
```

3. Play 2 (`hosts: truenas`, `become: true`) syncs `cluster-manifests/boot-artifacts/` → `/mnt/ssd/public/boot-files/ocp/` and is served at `https://public.igou.systems/boot-files/ocp/`. It creates the dir `mode: "0755"` and syncs with `--chmod=D0755,F0644`, then HEAD-probes the three files. **The perms matter**: a plain `rsync -a` leaves the dir `0750`, which the public-nginx worker (different UID) cannot traverse → HTTP 403 → the pin's initrd fetch fails and the boot silently exits. Confirm reachability:

```
curl -sI https://public.igou.systems/boot-files/ocp/agent.x86_64-vmlinuz
curl -sI https://public.igou.systems/boot-files/ocp/agent.x86_64-initrd.img
curl -sI https://public.igou.systems/boot-files/ocp/agent.x86_64-rootfs.img
```

All three must return `200`. The MS-01 pin's `install-openshift` entry sets `base {{ netboot_public_url }}/ocp` and pulls exactly these three filenames.

> The `.ipxe` script is intentionally NOT published (`--exclude=*.ipxe`); the boot flow is the rb5009 per-host pin, which carries its own kernel/initrd/rootfs URLs. Do not reference any retired netbootxyz container path (`10.10.45.242`, `/mnt/ssd/containers/netbootxyz/...`, `10.10.45.240/hub/`).

#### Phase 2 — Stage the safe pin (default `local`) ready to fire

Prepare the disarmed version of `MAC-5847ca77098a.ipxe` (identical menu, but `choose --timeout 30000 --default local target`) so you can push it the moment install starts. Two ways:

- **Canonical (preferred)**: edit the `58:47:ca:77:09:8a` pin fragment in `igou-inventory/group_vars/all/netboot.yml` to `--default local`, then push it with `deploy_assets.yml` (Phase 3, step 3). This is what PR **inventory#120** made the durable git default.
- **Fast manual (what broke the live loop)**: keep the disarmed pin file in the scratchpad and `scp -O` it straight onto rb5009 flash:

```
scp -O ~/scratchpad/MAC-5847ca77098a.ipxe \
  igou+cet1024w@rb5009.igou.systems:netboot/per-host/MAC-5847ca77098a.ipxe
```

Have this ready to execute; timing in Phase 3 is the whole game.

#### Phase 3 — Trigger the install and flip the pin mid-install to BREAK the loop

1. With Phase-1 artifacts live at 200, boot MS-01 into the installer (the pin's `install-openshift` default handles it on the 30s timeout, or select it at console).
2. Watch the install progress until status is **`installing`** (agent installer is writing to disk / has begun bootstrap). The critical window is *after* the installer has committed to disk but *before* the first mid-install reboot.
3. **Flip the pin to `default local` NOW** (Phase-2 scp, or `deploy_assets.yml --tags render,push,verify`). In the incident the flip landed at status=installing ~18:24 UTC.
4. The mid-install reboot then PXEs, hits the now-`local`-default pin, times out to `sanboot` local disk, and **boots FROM DISK** (~18:31) — loop broken. Node reached `Ready` ~18:38; CVO rolled to 4.21.9.

`deploy_assets.yml` pin push, for reference:

```
ansible-playbook playbooks/netboot/deploy_assets.yml \
  -i 'localhost ansible_connection=local,' \
  -i igou-inventory/inventory.yaml \
  --tags render,push,verify
```

#### Phase 4 — Fix the kubeconfig cert after MCO settles

Use the install's kubeconfig immediately:

```
export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig
```

After the MCO settles, the API serving cert rotates to a new CA and `oc` starts failing with `x509`. **Fix**: back up the kubeconfig, then strip the embedded CA so `oc` falls back to the system trust store (public LE cert on the API route is trusted):

```
cp "$KUBECONFIG" "${KUBECONFIG}_self_signed"
# remove the certificate-authority-data: line from $KUBECONFIG
```

(This is exactly what the playbook's `op-save` block does automatically — `kubeconfig_self_signed` backup + `lineinfile` removing `certificate-authority-data`. Because Phase 1 skips `op-save`, do it by hand.)

#### Phase 5a — Re-join `hpg5` (bare-metal PXE)

1. Refresh the add-node boot artifacts (token in the initrd rotates; artifacts land in `/mnt/ssd/public/boot-files/ocp-add-node/`):

```
export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig
ansible-playbook playbooks/openshift/add_node_iso.yml \
  -i 'localhost ansible_connection=local,' \
  -i igou-inventory/inventory.yaml \
  -e target_cluster=ocp
```

`add_node_iso.yml` runs `oc adm node-image create --pxe`, publishes `node.x86_64-{vmlinuz,initrd.img,rootfs.img}` to the `ocp-add-node/` subdir with `--chmod=F0644,D0755` (same 403-avoidance as above), and preflights out any host already a node.

2. **Arm** the hpg5 pin (`MAC-f8b46aab55c7.ipxe`, MAC `f8:b4:6a:ab:55:c7`) to default `ocp-node` instead of `local`, then push it (`deploy_assets.yml --tags render,push,verify`). Its `ocp-node` entry chains the `ocp-add-node/` artifacts. **Verify the pin content actually landed on rb5009 flash** before rebooting — a prior deploy silently ran from the wrong cwd and pushed nothing.
3. Reboot hpg5 (route is via `eno1`). It PXE-boots, picks `ocp-node`, boots the add-node image, and installs RHCOS to disk. Bare-metal RTC is correct, so there is no clock/x509 problem here.
4. Once it has written the disk, **revert the pin to default `local`** and push again, so every subsequent netboot falls through to the installed disk.
5. Approve CSRs (Phase 6).

> hpg5's host SSH key changes at each boot phase (live installer vs installed RHCOS) — clear it with `ssh-keygen -R hpg5.igou.systems` (and the IP) between phases or SSH will refuse.

#### Phase 5b — Re-join `truenas-w1` (KubeVirt VM, node-image ISO)

The `--pxe` / RAW-`.dsk` netboot fallback is **broken for this VM** (a raw `.efi` written to a disk is not a valid ESP → OVMF drops to the EFI shell). Use the full ISO instead.

1. Generate a per-host node-image **ISO** (not `--pxe`), with a nodes-config pinned to the VM's identity (MAC `52:54:00:0a:09:15`, hostname `truenas-w1`):

```
export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig
oc adm node-image create --dir ~/openshift-add-node/ocp-iso
# produces a ~1.4G node.<arch>.iso
```

2. Upload the ISO to TrueNAS: `/mnt/ssd/vms/images/`.
3. **Fix the VM clock to UTC before booting** (critical — see gotchas). RHCOS expects `hwclock=UTC`; the VM was set to `LOCAL`, putting the guest RTC ~4h behind, which makes Ignition's `GET https://api-int:22623/config/worker` fail `x509: certificate not yet valid` (the MCS cert's valid-from is the reinstall time, e.g. 18:23):

```
SSH_AUTH_SOCK= ssh -i ~/.ssh/id_ed25519 truenas_admin@truenas.igou.systems \
  "midclt call vm.update 5 '{\"time\":\"UTC\"}'"
```

4. Attach the ISO as a **CDROM** device ordered FIRST so it boots the installer:

```
midclt call vm.device.create '{"vm":5,"attributes":{"dtype":"CDROM","path":"/mnt/ssd/vms/images/node.x86_64.iso","order":1000}}'
```

5. Device changes require a **full QEMU restart** (a soft reboot won't pick up the new device). Hard-destroy via the TrueNAS libvirt socket, then start:

```
sudo virsh -c "qemu+unix:///system?socket=/run/truenas_libvirt/libvirt-sock" destroy 5_truenasw1
midclt call vm.start 5
```

6. It boots the ISO and installs RHCOS to the zvol. Watch the console via screenshot (TrueNAS 25.10 is libvirt/incus, not plain virsh):

```
sudo virsh -c "qemu+unix:///system?socket=/run/truenas_libvirt/libvirt-sock" \
  screenshot 5_truenasw1 /tmp/x.png
```

7. After the disk is written (verify RHCOS partitions exist, e.g. `sgdisk`/`lsblk` shows the RHCOS layout on the zvol), **reorder the CDROM AFTER the disk** (`order: 1010`) and restart QEMU again, so it boots the installed disk and not the ISO in a loop:

```
midclt call vm.device.update <cdrom_device_id> '{"order":1010}'
sudo virsh -c "qemu+unix:///system?socket=/run/truenas_libvirt/libvirt-sock" destroy 5_truenasw1
midclt call vm.start 5
```

8. Approve CSRs (Phase 6).

#### Phase 6 — CSR approval (the ~40-minute gotcha)

Each joining node emits **two rounds** of CSRs: a kubelet **client** CSR (node-bootstrapper), then a kubelet **serving** CSR after the client one is approved. Both must be approved within ~1h or the join stalls.

**Do NOT filter `oc get csr` on `$5`.** In `oc get csr` the `CONDITION` column is **column 6**, not 5 (`NAME AGE SIGNERNAME REQUESTOR REQUESTEDDURATION CONDITION`). A monitor's `awk '$5=="Pending"'` silently matched nothing while **9 node-bootstrapper CSRs piled up unapproved for ~40 min**. Use the status-based go-template instead of column arithmetic:

```
oc get csr -o go-template='{{range .items}}{{if not .status}}{{.metadata.name}}{{"\n"}}{{end}}{{end}}' \
  | xargs --no-run-if-empty oc adm certificate approve
```

Run it repeatedly (both nodes, both rounds) until `oc get nodes` shows both workers `Ready`.

> If a node still won't produce a client CSR, its kubelet may need a clean bootstrap: `systemctl stop kubelet`, `rm /var/lib/kubelet/kubeconfig /var/lib/kubelet/pki/*`, `systemctl start kubelet`. In this incident the real blocker was always just unapproved CSRs, not the kubelet.

---

### Verification

```
export KUBECONFIG=$HOME/openshift-agent-install/ocp/cluster-manifests/auth/kubeconfig

# 1. All three nodes Ready (control plane + both workers)
oc get nodes -o wide
#   ocp.igou.systems   Ready control-plane,master,worker
#   hpg5.igou.systems  Ready worker
#   truenas-w1         Ready worker

# 2. Cluster version reconciled
oc get clusterversion
#   version 4.21.9 True(Available) False(Progressing) — "Cluster version is 4.21.9"

# 3. No CSRs left pending (correct selector)
oc get csr -o go-template='{{range .items}}{{if not .status}}{{.metadata.name}}{{"\n"}}{{end}}{{end}}'
#   (empty)

# 4. Pin safety — MS-01 pin default is `local`, so an unattended reboot can never reinstall
SSH_AUTH_SOCK= ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes igou@rb5009.igou.systems -p 3480 \
  "/file print value-list where name=\"netboot/per-host/MAC-5847ca77098a.ipxe\""
#   must contain:  choose --timeout 30000 --default local target
# Repeat for MAC-f8b46aab55c7.ipxe (hpg5) and MAC-52540...915.ipxe (truenas-w1): all `--default local`.

# 5. Boot artifacts still served (perms not silently regressed to 403)
curl -sI https://public.igou.systems/boot-files/ocp/agent.x86_64-vmlinuz          # 200
curl -sI https://public.igou.systems/boot-files/ocp-add-node/node.x86_64-vmlinuz  # 200
```

Live state at close of the incident confirmed all of the above: 3 nodes `Ready` (v1.34.6), `clusterversion 4.21.9 Available`, zero pending CSRs.

---

### Rollback

There is no "rollback" of a reinstall — the old etcd is gone. What you can roll back is the **install trigger**, and that IS the core safety action:

- **Abort an in-progress reinstall loop**: push the `default local` pin (`scp -O … MAC-<hex>.ipxe`, or `deploy_assets.yml --tags render,push,verify`). The very next reboot then boots local disk instead of re-installing. This is the same flip used in Phase 3 — flipping to `local` at any time stops the loop.
- **Disarm a worker mid-attempt**: flip its pin default back to `local` and push; the node stops PXE-installing on reboot. No node ever needs firmware changes.
- **Leave the boot artifacts in place** — they are harmless when no pin defaults to installing them. The interlock is entirely the pin default.
- Old PV zvols on TrueNAS were never touched; nothing here deletes data. `p330` stays excluded (dark, no BMC).

Durable fixes merged so this can't recur silently: **inventory#120** (MS-01 pin default → `local` in git), **ansible#311** (deploy_pxe_assets publish-path fix). Still-open follow-ups from the incident: PR the `default local` for all worker pins, remove the stale `bootArtifactsBaseURL 10.10.45.242` in `host_vars/ocp.yml`, and fold the manual kubeconfig-CA-strip into the non-op path.

---

### Gotchas & pitfalls (all observed this incident)

- **Netboot-first firmware + install-defaulting pin = auto-wipe.** MS-01 BootOrder is PXE→PXE→disk(3s). The pin default is the ONLY interlock; it must be `local` except during a deliberate install. A pin left defaulting to `install-openshift` since a months-old migration is what destroyed the cluster on an unattended reboot.
- **The reinstall loop is real and self-sustaining.** Agent install reboots mid-flight; if the pin still defaults to install, every reboot restarts the install forever. You MUST flip the pin to `local` while status is `installing` (before the first in-install reboot) — timing is the whole trick.
- **nginx 403 from perms, not from missing files.** `rsync -a` / a bare mkdir leaves `0750`; the public-nginx worker runs as a different UID and can't traverse → 403 → iPXE's initrd fetch fails → the boot menu silently exits with no obvious error. Always force `D0755,F0644` (the playbooks do; verify with `curl -sI … 200`).
- **`oc get csr` CONDITION is column 6, not 5.** A `awk '$5=="Pending"'` monitor silently approved nothing while 9 CSRs stacked up for ~40 min. Use `-o go-template='{{if not .status}}…'` — it keys on the actual empty-status field, immune to column drift.
- **Two CSR rounds per node** (kubelet client, then serving). Keep approving until `Ready`; approving once is not enough.
- **truenas-w1 VM clock defaulted to LOCAL → x509 "certificate not yet valid."** RHCOS needs `hwclock=UTC`; a ~4h-behind guest RTC makes Ignition's MCS fetch fail because the MCS cert's valid-from is the (later) reinstall time. `midclt call vm.update 5 '{"time":"UTC"}'` + restart. This bites only the VM worker, not bare metal.
- **TrueNAS VM device changes need a full QEMU restart**, not a guest reboot. Use `virsh -c "qemu+unix:///system?socket=/run/truenas_libvirt/libvirt-sock" destroy 5_truenasw1` then `midclt call vm.start 5`. TrueNAS 25.10 is libvirt/incus — the socket path is `/run/truenas_libvirt/libvirt-sock`, not the default virsh socket; console screenshots go through the same `-c` URI.
- **The VM's RAW `.dsk` / `--pxe` netboot fallback does NOT work for an OCP install** — a raw `.efi` on a disk isn't a valid ESP and OVMF drops to a shell. Use the full `oc adm node-image create --dir` ISO attached as a CDROM.
- **CDROM must be reordered after install** (order 1000 to boot installer → 1010 after disk write) or the VM boots the ISO in a loop — the VM analogue of the MS-01 pin loop. Verify the disk actually has RHCOS partitions before reordering.
- **Verify pin content actually landed on rb5009.** One `deploy_assets` run silently executed from the wrong cwd and pushed nothing; always read back the flash file (`/file print value-list where name="…"`).
- **hpg5 host key rotates per boot phase** — `ssh-keygen -R` between phases or SSH refuses to connect.
- **Everything 1Password is dead during recovery.** Connect/ESO/AAP all ran on the destroyed cluster, so `op` lookups fail. Regenerate PXE assets with `--skip-tags op-save -e @override.yml` carrying a literal pull secret, and do the kubeconfig-CA strip by hand.
- **Local repo checkouts are STALE.** `git fetch origin main` first; read canonical files via `git show origin/main:<path>` rather than trusting the working tree.
