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

## Networking — shared guest-dmz Gateway (Gateway API)

Jellyfin is **not** exposed via an OpenShift Route or Ingress. LAN clients
reach it through the shared guest-dmz tier Gateway
(`clusters/ocp/gateway-api/`, design in
[#367](https://github.com/igou-io/igou-openshift/issues/367)):

| Entry point | Purpose |
| --- | --- |
| `https://jellyfin.dmz.igou.systems` → `10.10.152.3:443` | TLS entry point for LAN clients (shared tier Gateway / Envoy) |
| `10.10.152.1:8096` (`jellyfin` chart Service, pinned VIP) | Direct HTTP for the VLANs with tier-wide guest-dmz access (debugging, initial setup) |

This app contributes only two things to the gateway wiring:

1. **Namespace label** `gateway-access/guest-dmz: "true"`
   (`jellyfin-namespace.yaml`) — opts the namespace into the Gateway's
   `allowedRoutes` selector.
2. **HTTPRoute `jellyfin`** (`jellyfin-httproute.yaml`) — hostname
   `jellyfin.dmz.igou.systems` → Service `jellyfin:8096`, with
   `timeouts.request: 0s` for long-lived streaming sessions. Websocket
   upgrades work because the chart Service port is named `http`.

TLS (wildcard `*.dmz.igou.systems`, hot-reloaded on renewal), the VIP, and
DNS/firewall contracts live with the Gateway, not here: the rb5009 has a
wildcard DNS record `*.dmz.igou.systems -> 10.10.152.3` and per-VLAN
pinholes (VLAN35/Shield, VLAN20/phones) to `10.10.152.3 tcp/443`.

Because the Gateway's Service is `externalTrafficPolicy: Cluster`, jellyfin
sees node IPs as client addresses (X-Forwarded-For carries the node, not
the real client). `KnownProxies` in jellyfin's network config is set to the
pod network (`10.128.0.0/14`) so the Envoy hop itself is trusted.

> History: jellyfin was previously fronted by a dedicated Hummingbird
> nginx proxy at `10.10.152.2:443` as `jellyfin.igou.systems` (#365),
> retired for the shared Gateway. Before that it rode a Multus + macvlan
> secondary interface on VLAN 45 (`10.10.45.221`), migrated to MetalLB in
> commit `107a0fe`.

### Consequences / constraints

- `replicaCount` must stay at `1`: the `jellyfin-config` PVC is **RWO**
  (ReadWriteOnce) and the Intel iGPU is a single device, so only one pod
  can run at a time.
- `deploymentStrategy: Recreate` is required because the RWO config volume
  cannot be mounted by an old and new pod simultaneously during a rolling
  update.

### Reaching jellyfin from the LAN

Clients use `https://jellyfin.dmz.igou.systems` (rb5009 wildcard DNS →
`10.10.152.3`). Which VLANs may reach it is governed by the per-VLAN
pinhole rules on the rb5009, not by anything in this repo — and note the
tier semantics: every VLAN admitted to the tier VIP can reach every
hostname on the shared Gateway.

> **Note:** the chart Service uses the `metallb.universe.tf/address-pool`
> annotation, which MetalLB now logs as deprecated. It still functions;
> migrating to a pool selector / `IPAddressPool`-scoped advertisement is a
> future cleanup.
