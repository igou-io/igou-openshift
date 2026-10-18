# Rust server

The Deployment is deliberately scaled to zero pending a hardened design for
public ingress and VPS egress. The connection instructions below describe its
configuration when enabled. Restore replicas through GitOps only after that
design is reviewed and authenticated joins pass.

Small vanilla Rust game server in `public-services`: a 2000-size procedural
map, seed 20261018, and ten player slots. The pinned SteamCMD base downloads
the current stable dedicated server (Steam app 258550) at startup.

The pod uses Kata, an arbitrary OpenShift nonroot UID, no API token, a read-only
root filesystem, and bounded temporary storage. World data survives container
restarts but is lost when the pod is replaced. PVCs remain forbidden by the
namespace admission policy. Installation and map generation can take several
minutes. There is no liveness restart during startup.

The server supports direct connections at `igou.io:27020`. Only its own
Tailscale proxy can reach that UDP game port. The Steam query listener on
UDP 27021 stays inside the pod for readiness checks; Services and NetworkPolicies
do not expose it, and the private AAP catalog contains only `rust-game`.
Blocking query traffic follows [Facepunch's hidden-server guidance](https://wiki.facepunch.com/rust/Creating_a_hidden_whitelisted_server)
and prevents server-browser queries. Previously cached listings may take time
to disappear. This is not a player whitelist: anyone with the address can
attempt to join. RCON and Rust+ remain disabled. The website continues on
HTTPS 443.

Connect from the Rust F1 console:

```text
client.connect igou.io:27020
```

This application alone can query OpenShift DNS and reach public IPv4 addresses
on HTTP/HTTPS and Steam TCP/UDP 27000–27100. Private, link-local, loopback,
multicast and tailnet ranges are excluded. This permits Steam downloads and
authentication without granting access to other cluster workloads. DNS and
public service connections are outbound data channels; this workload needs
them, unlike the network test examples.

Render with `kustomize build applications/rust-server`. Resource overrides for
the shared namespace quota are in `clusters/ocp/values.yaml`.
