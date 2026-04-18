# jellyfin

Jellyfin media server deployed via the upstream Helm chart (vendored under
`charts/jellyfin-3.0.0/`) with a few cluster-specific overrides.

## Storage

| Purpose | PVC | Source | Access | Notes |
| --- | --- | --- | --- | --- |
| Library DB / metadata (`/config`) | `jellyfin-config` | `freenas-nvmeof-ssd-csi` (democratic-csi, NVMe-oF) | RWO, 20Gi | Passed to the chart via `persistence.config.existingClaim`. |
| Media library (`/media`) | `jellyfin-media` | Static NFS PV (`10.10.9.213:/mnt/cold/media/data/media`) | ROX, 1Ti, read-only mount | Chart's built-in media volume is disabled (`persistence.media.enabled: false`) and replaced by a JSON-patch that swaps in this PVC. |

## Node placement

The deployment is pinned to `hub.igou.systems` via `nodeSelector:
kubernetes.io/hostname: hub.igou.systems`. Rationale: the Intel iGPU
(`gpu.intel.com/i915`) used for hardware transcoding is only exposed on the
hub node by the Intel Device Plugin Operator. The GPU request alone would
gate scheduling, but the explicit nodeSelector makes the intent obvious and
prevents admission-retry churn when the device plugin flaps.

## Networking — Multus secondary interface (intentional, no Route/Ingress)

Jellyfin is **not** exposed via an OpenShift Route or Ingress. Instead it is
attached to a secondary interface on VLAN 45 using Multus + macvlan and
reachable directly at `10.10.45.221:8096` on the LAN. This keeps media
traffic off the cluster SDN and off the ingress controller.

### Components

1. **NetworkAttachmentDefinition** — `jellyfin-nad-vlan45.yaml`
   - Name: `vlan45-jellyfin` (namespace-scoped to `jellyfin`)
   - CNI: `macvlan` in `bridge` mode
   - Master interface: `enp2s0f1.45` (VLAN 45 subinterface of the
     OVS-managed secondary NIC; see `clusters/hub/nmstate/` for the NNCP
     that provisions it)
   - IPAM: `static` — the IP is assigned per-pod via the pod annotation
     below, not by the NAD itself. Default route via `10.10.45.1`.

2. **Pod annotation** (set via chart `podAnnotations`):
   ```yaml
   k8s.v1.cni.cncf.io/networks: |-
     [
       {
         "name": "vlan45-jellyfin",
         "ips": ["10.10.45.221/24"]
       }
     ]
   ```
   The `ips` field here is what actually assigns the address; pairing it
   with `"ipam": { "type": "static" }` in the NAD produces a deterministic,
   per-pod address without running an IPAM daemon.

3. **ClusterIP Service** — created by the chart, kept for cluster-local
   health/probe traffic on `8096/TCP`. It is **not** the user-facing entry
   point.

### Consequences / constraints

- `replicaCount` must stay at `1`. The hardcoded IP in `podAnnotations`
  means two replicas would race for the same address and one would fail
  CNI setup.
- `deploymentStrategy: Recreate` is required for the same reason — a
  rolling update would briefly have two pods and collide on the IP.
- If the VLAN 45 subinterface (`enp2s0f1.45`) goes away (NNCP drift, NIC
  rename), pod admission fails with a CNI error. Check
  `clusters/hub/nmstate/` first when that happens.

### Reaching jellyfin from the LAN

DNS for the external name should point at `10.10.45.221`. The pod binds
`8096/TCP` on both its primary (OVN) and secondary (macvlan) interfaces;
use the secondary IP from outside the cluster.
