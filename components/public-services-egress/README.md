# Public service egress

This infrastructure gateway sends `public-services` internet traffic through
the VPS Tailscale exit node. It makes the Steam-facing public IP match the
public game endpoint. Application pods retain Kata, their existing NetworkPolicies,
and their tokenless service account.

OVN's `AdminPolicyBasedExternalRoute` selects only `public-services` and uses
the fixed next hop `10.10.9.12`. The next hop remains configured when the gateway
pod disappears. BFD is disabled so a gateway outage cannot withdraw that route
and restore the ordinary home egress path.

The gateway runs separately in `public-services-egress` on the control plane.
A macvlan on `br-ex` supplies its underlay address. Return routes point the two
Kata worker pod subnets at their corresponding node addresses. Other cluster
pod destinations are blackholed. Update these routes when adding a Kata worker.
Application pods do not receive a secondary interface.

The init container sets a default-drop forwarding policy before enabling IPv4
forwarding and disables IPv6. Only the init container is privileged; the daemon
has `NET_ADMIN`. Both use a pinned image and read-only root filesystem, with
no host network, host PID, or host directory mounts. The pod has a projected
API token that can read and update only its own pre-created Tailscale state
Secret. It cannot read operator OAuth or application Secrets. Its enrollment
key comes from a separate ExternalSecret.

The forwarding firewall accepts public TCP 80/443 and TCP/UDP 27000–27100
only when the outgoing interface is `tailscale0`. It rejects private and
reserved destinations. Replies return through the underlay to OVN. The
application NetworkPolicy and tailnet grant provide additional restrictions.
Gateway process traffic has separate DNS/API/Tailscale transport exceptions.

Dependencies: the VPS `public-egress` component, approval of its exit node,
the narrow internet grant through that exit node, and the backing 1Password
enrollment item. See the private `igou-docs/networking/Public Service Sharing
with AAP.md` runbook for preparation, verification, and rollback. No tailnet
domain suffix is required in this repository.

Render with `kustomize build components/public-services-egress`. This changes
the namespace's outbound routing; deploying it requires live routing and
authenticated player-join verification. It does not expose the Steam query port
or replace the Rust pod.
