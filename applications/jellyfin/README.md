# jellyfin

Jellyfin media server deployed via the upstream Helm chart (vendored under
`charts/jellyfin-3.2.0/`) with a few cluster-specific overrides.

## Storage

| Purpose | PVC | Source | Access | Notes |
| --- | --- | --- | --- | --- |
| Library DB / metadata (`/config`) | `jellyfin-config` | `freenas-nvmeof-ssd-csi` (democratic-csi, NVMe-oF) | RWO, 20Gi | Passed to the chart via `persistence.config.existingClaim`. |
| Media library (`/media`) | `jellyfin-media` | Static NFS PV (`10.10.9.213:/mnt/cold/media/data/media`) | ROX, 1Ti, read-only mount | Chart's built-in media volume is disabled (`persistence.media.enabled: false`) and replaced by a JSON-patch that swaps in this PVC. |

## Node placement

The deployment is pinned to `ocp.igou.systems` (the Minisforum MS-01) via
`nodeSelector: kubernetes.io/hostname: ocp.igou.systems`. Rationale: jellyfin
must run on the MS-01, whose Intel iGPU (`gpu.intel.com/i915`) is used for
hardware transcoding. Note that more than one node now advertises
`gpu.intel.com/i915` (e.g. `hpg5.igou.systems`), so the GPU request alone no
longer gates scheduling to the MS-01 — the explicit `nodeSelector` is what
enforces placement on this node.

## Networking — MetalLB LoadBalancer (BGP, no Route/Ingress)

Jellyfin is **not** exposed via an OpenShift Route or Ingress. The chart's
Service is set to `type: LoadBalancer` and MetalLB hands it an address from
the `guest-dmz` pool, reachable directly at `10.10.152.1:8096` on the LAN.
This keeps media traffic off the ingress controller.

> History: jellyfin previously rode a Multus + macvlan secondary interface
> on VLAN 45 (`10.10.45.221`). That was migrated to MetalLB in commit
> `107a0fe`; the old `vlan45-jellyfin` NetworkAttachmentDefinition and the
> `k8s.v1.cni.cncf.io/networks` pod annotation are gone.

### Components

1. **LoadBalancer Service** — created by the chart (`service.type:
   LoadBalancer`, port `8096`). Pool selection is via the Service
   annotation `metallb.universe.tf/address-pool: guest-dmz`.

2. **MetalLB `guest-dmz` IPAddressPool** — `10.10.152.0/24`, defined in
   `components/metallb/`. `autoAssign: false`, so the pool is only used by
   services that explicitly request it via the annotation above.

3. **BGP advertisement** — MetalLB runs in FRR/BGP mode and advertises the
   service IP (`10.10.152.1/32`) to the MikroTik router (`10.10.9.1`,
   AS 64512) via the `guest-dmz` `BGPAdvertisement`. There is no L2/ARP
   advertisement.

### Consequences / constraints

- `replicaCount` must stay at `1`: the `jellyfin-config` PVC is **RWO**
  (ReadWriteOnce) and the Intel iGPU is a single device, so only one pod
  can run at a time.
- `deploymentStrategy: Recreate` is required because the RWO config volume
  cannot be mounted by an old and new pod simultaneously during a rolling
  update.

### Reaching jellyfin from the LAN

DNS for the external name should point at `10.10.152.1`. The service IP is
reachable from any LAN host that routes to the `guest-dmz` subnet via the
MikroTik (which learns the `/32` over BGP).

> **Note:** the Service uses the `metallb.universe.tf/address-pool`
> annotation, which MetalLB now logs as deprecated. It still functions;
> migrating to a pool selector / `IPAddressPool`-scoped advertisement is a
> future cleanup.
