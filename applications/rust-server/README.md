# Rust server

Small vanilla Rust game server in `public-services`: a 2000-size procedural
map, seed 20261018, and ten player slots. The pinned SteamCMD base downloads
the current stable dedicated server (Steam app 258550) at startup.

The pod uses Kata, an arbitrary OpenShift nonroot UID, no API token, a read-only
root filesystem, and bounded temporary storage. World data survives container
restarts but is lost when the pod is replaced. PVCs remain forbidden by the
namespace admission policy. Installation and map generation can take several
minutes. There is no liveness restart during startup.

Only its own Tailscale proxy can reach UDP 27020 (game) and UDP 27021 (Steam
query). RCON is disabled and bound to loopback; Rust+ is disabled. AAP exposes
the two UDP ports as separate shares using the `rust-game` and `rust-query`
private inventory entries. Matching public/backend ports avoid advertising a
different game port in query responses. The existing `igou.io` website remains
on HTTPS 443.

This application alone can query OpenShift DNS and reach public IPv4 addresses
on HTTP/HTTPS and Steam TCP/UDP 27000–27100. Private, link-local, loopback,
multicast and tailnet ranges are excluded. This permits Steam downloads and
authentication without granting access to other cluster workloads. DNS and
public service connections are outbound data channels; this workload needs
them, unlike the network test examples.

Render with `kustomize build applications/rust-server`. Resource overrides for
the shared namespace quota are in `clusters/ocp/values.yaml`.
