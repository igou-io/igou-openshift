# Runbook: NVMe-oF RWO volume stuck in `Multi-Attach`

**Applies to:** any RWO PVC on a `freenas-nvmeof-*` StorageClass (democratic-csi).
**Symptom:** a pod is stuck `Pending` / `ContainerCreating` after rescheduling to another node, with a `Multi-Attach` error. Often cascades (e.g. a stuck Postgres takes down every app in its namespace).

See [issue #295](https://github.com/igou-io/igou-openshift/issues/295) for the root cause and the permanent fix. This runbook is the **manual remediation** for an active incident.

---

## 1. Confirm it's this failure mode

The pod's events show:

```
FailedAttachVolume  Multi-Attach error for volume "pvc-XXXX"
                    Volume is already exclusively attached to one node and can't be attached to another
```

Identify the PV and the node it's stuck on:

```bash
NS=<namespace>; POD=<pod>
# PV behind the pod's stuck PVC
PVC=$(oc get pod "$POD" -n "$NS" -o jsonpath='{.spec.volumes[*].persistentVolumeClaim.claimName}')
PV=$(oc get pvc "$PVC" -n "$NS" -o jsonpath='{.spec.volumeName}')
echo "PV=$PV"

# which node still holds it (this is the HOLDING node)
oc get volumeattachment -o json \
  | jq -r --arg pv "$PV" '.items[] | select(.spec.source.persistentVolumeName==$pv)
      | "VA \(.metadata.name)  node=\(.spec.nodeName)  attached=\(.status.attached)"'

# confirm it's wedged: the PV is still in the holding node's volumesInUse with no consuming pod there
HOLDER=<node-from-above>
oc get node "$HOLDER" -o json | jq -r --arg pv "$PV" '[.status.volumesInUse[]|select(contains($pv))]'
```

**Signature of the bug:** the PV appears in `<holder>.status.volumesInUse`, but no pod on `<holder>` consumes it, and the democratic-csi node plugin on `<holder>` is failing `NodeUnstageVolume` in a loop:

```bash
oc -n democratic-csi logs <democratic-csi-nvmeof-*-node-pod-on-holder> -c csi-driver --tail=200 \
  | grep -iE 'NodeUnstageVolume|not a block device'
# -> "lsblk: /dev/nvmeXn1: not a block device"  (the NVMe controller renumbered after a transport drop)
```

This does **not** self-heal: deleting the VolumeAttachment, restarting kube-controller-manager, etc. all fail because kubelet keeps the volume in `volumesInUse`.

---

## 2A. Remediation — holding node is HEALTHY (the common case)

> This is the case when only the storage connection blipped; the node itself is `Ready` and running other workloads.
> There is no native auto-force-detach for a healthy node (by design — data safety), so restart kubelet to make it rebuild its volume state.

```bash
oc debug node/<holder> --quiet -- chroot /host systemctl restart kubelet
```

Restarting kubelet rebuilds its actual-state-of-world from the real mount table; since the stale device is gone, the volume drops out of `volumesInUse`, the attach-detach controller detaches the old VolumeAttachment, and the volume re-attaches on the new node.

**Verify recovery (within ~1-2 min):**

```bash
oc get node <holder> -o json | jq -r --arg pv "$PV" '[.status.volumesInUse[]|select(contains($pv))] | if length>0 then "still stuck" else "cleared" end'
oc get volumeattachment -o json | jq -r --arg pv "$PV" '.items[]|select(.spec.source.persistentVolumeName==$pv)|"now on \(.spec.nodeName) attached=\(.status.attached)"'
oc get pod "$POD" -n "$NS" -o wide
```

Dependent pods that CrashLooped during the outage may sit in backoff. Nudge them (Deployment/StatefulSet-managed, safe to delete):

```bash
oc delete pod <crashlooping-pods> -n "$NS"
```

---

## 2B. Remediation — holding node is genuinely DOWN / unreachable

> Only if `<holder>` is actually powered off or unrecoverable. **Do not** use this on a running node — it force-detaches volumes and **will corrupt filesystems** if the node is still writing.

1. **Confirm the node is fully powered off** (BMC / `oc get node <holder>` NotReady, no kubelet).
2. Apply the OpenShift out-of-service taint — this force-deletes the node's pods and force-detaches their volumes for failover:

   ```bash
   oc adm taint node <holder> node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
   ```
3. Once volumes have re-attached and pods recovered elsewhere, and the node is back, remove the taint:

   ```bash
   oc adm taint node <holder> node.kubernetes.io/out-of-service=nodeshutdown:NoExecute-
   ```

---

## 3. Optional immediate hardening (prevent recurrence on already-connected volumes)

The permanent fix (host udev rule, [#295](https://github.com/igou-io/igou-openshift/issues/295)) sets `ctrl_loss_tmo=-1` so an NVMe-oF controller is never torn down (no renumber → no stuck unstage). You can apply it now to live controllers without waiting for the MachineConfig:

```bash
for n in $(oc get nodes -o name); do
  oc debug "$n" --quiet -- chroot /host bash -c '
    for c in /sys/class/nvme/nvme*; do
      [ "$(cat "$c/transport" 2>/dev/null)" = tcp ] && echo -1 > "$c/ctrl_loss_tmo"
    done'
done
# verify: ctrl_loss_tmo reads back as "off" on tcp controllers
```

> Tradeoff: with `ctrl_loss_tmo=-1`, I/O **queues indefinitely** during a storage outage (DB processes block in `D`-state) instead of erroring out. For our single-target, no-multipath TrueNAS topology this is the desired behavior (wait for the box rather than fail/corrupt), but it is a deliberate choice.

---

## Background / references

- Root cause + permanent fix: [igou-io/igou-openshift#295](https://github.com/igou-io/igou-openshift/issues/295)
- Upstream (acknowledged, unfixed): democratic-csi/democratic-csi#536 (NodeUnstageVolume not idempotent on a missing device), #559 (renumber → stale globalmount → Multi-Attach)
- Prior incident: 2026-06-05, 5 stuck volumes after a network outage; 2026-06-06, `aap-postgres-15-0` after adding node `p330`.
