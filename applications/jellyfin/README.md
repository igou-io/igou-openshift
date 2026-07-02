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

Jellyfin is **not** exposed via an OpenShift Route or Ingress. This keeps
media traffic off the ingress controller (and off the server-VLAN ingress
VIP). Two MetalLB LoadBalancer VIPs from the `guest-dmz` pool are pinned via
the `metallb.universe.tf/loadBalancerIPs` annotation:

| VIP | Service | Purpose |
| --- | --- | --- |
| `10.10.152.2:443` | `jellyfin-proxy` | TLS entry point for LAN clients — `https://jellyfin.igou.systems` |
| `10.10.152.1:8096` | `jellyfin` (chart) | Direct HTTP, reachable only from the admin-ish VLANs (9/10/25/70) |

Both VIPs are contracts with the MikroTik config in `igou-inventory`
(`host_vars/rb5009.igou.systems.yml`): the static DNS record
`jellyfin.igou.systems -> 10.10.152.2` and per-VLAN firewall pinholes
(VLAN35/IoT for the NVIDIA Shield, VLAN20/users for phones) allow exactly
`10.10.152.2` tcp/443 — do not change these IPs without updating both repos.

> History: jellyfin previously rode a Multus + macvlan secondary interface
> on VLAN 45 (`10.10.45.221`). That was migrated to MetalLB in commit
> `107a0fe`; the old `vlan45-jellyfin` NetworkAttachmentDefinition and the
> `k8s.v1.cni.cncf.io/networks` pod annotation are gone.

### Components

1. **TLS proxy (`jellyfin-proxy`)** — a single-replica
   [Project Hummingbird](https://hummingbird-project.io/) nginx
   (`quay.io/hummingbird/nginx`, distroless, non-root, read-only rootfs)
   that terminates TLS on `8443` and proxies to the chart Service on
   `8096`. The server block in `jellyfin-proxy-nginx.conf` is ported from
   the nginx that fronted the old deployment on biscuit (websocket
   upgrade, streaming timeouts, `proxy_buffering off`). The config is
   shipped via `configMapGenerator`, so edits hash-roll the Deployment.

2. **Certificate (`jellyfin-tls`)** — cert-manager, issued by the
   `cluster-acme` ClusterIssuer (Let's Encrypt production, Cloudflare
   DNS-01) for `jellyfin.igou.systems`, so clients need no custom CA.
   **Renewal caveat:** nginx does not watch the secret; after a renewal
   (~every 75 days) the proxy must be restarted to serve the new cert
   (`oc -n jellyfin rollout restart deploy/jellyfin-proxy`). The blackbox
   probe's `probe_ssl_earliest_cert_expiry` metric is the safety net.

3. **LoadBalancer Services** — the proxy Service (`443 -> 8443`) and the
   chart Service (`8096`). Pool selection is via the Service annotation
   `metallb.universe.tf/address-pool: guest-dmz`; both use
   `externalTrafficPolicy: Local`.

4. **MetalLB `guest-dmz` IPAddressPool** — `10.10.152.0/24`, defined in
   `components/metallb/`. `autoAssign: false`, so the pool is only used by
   services that explicitly request it via the annotation above.

5. **BGP advertisement** — MetalLB runs in FRR/BGP mode and advertises the
   service `/32`s to the MikroTik router (`10.10.9.1`, AS 64512) via the
   `guest-dmz` `BGPAdvertisement`. There is no L2/ARP advertisement.

### Consequences / constraints

- `replicaCount` must stay at `1`: the `jellyfin-config` PVC is **RWO**
  (ReadWriteOnce) and the Intel iGPU is a single device, so only one pod
  can run at a time.
- `deploymentStrategy: Recreate` is required because the RWO config volume
  cannot be mounted by an old and new pod simultaneously during a rolling
  update.

### Reaching jellyfin from the LAN

Clients use `https://jellyfin.igou.systems` (rb5009 static DNS →
`10.10.152.2`). Which VLANs may reach it is governed by the per-VLAN
pinhole rules on the rb5009, not by anything in this repo. The direct
HTTP endpoint `10.10.152.1:8096` remains for the VLANs with tier-wide
guest-dmz access (debugging, initial setup).

> **Note:** the Service uses the `metallb.universe.tf/address-pool`
> annotation, which MetalLB now logs as deprecated. It still functions;
> migrating to a pool selector / `IPAddressPool`-scoped advertisement is a
> future cleanup.
