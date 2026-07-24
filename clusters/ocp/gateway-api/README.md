# gateway-api

Shared per-tier Gateway API infrastructure — design and rationale in
[igou-openshift#367](https://github.com/igou-io/igou-openshift/issues/367).
One Gateway per MetalLB exposure tier replaces per-app TLS proxy
deployments (the jellyfin Hummingbird nginx pattern from #365): apps
onboard with a single HTTPRoute in their own namespace.

## Components

| Resource | Purpose |
| --- | --- |
| `GatewayClass openshift-default` | Binds to `openshift.io/gateway-controller/v1`; on first reconcile the Ingress Operator installs the managed OSSM 3 / Istio control plane in `openshift-ingress` |
| `Gateway guest-dmz` | Tier entry point. Managed Envoy Deployment + LoadBalancer Service, pinned to `10.10.152.3` in the MetalLB `guest-dmz` pool via `spec.infrastructure.annotations` |
| `Certificate gateway-guest-dmz-tls` | Wildcard `*.dmz.igou.systems` via the `cluster-acme` ClusterIssuer (LE production, Cloudflare DNS-01). Envoy hot-reloads the renewed secret via SDS — no restart choreography |
| `Gateway trusted-lan` | Same shape for the trusted-lan tier ([#490](https://github.com/igou-io/igou-openshift/issues/490)), pinned to `10.10.150.3` in the `trusted-lan` pool. rk8s serves the same tier domain from its half of the pool (`10.10.150.129`); per-hostname DNS on the rb5009 decides which cluster serves a name |
| `Certificate gateway-trusted-lan-tls` | Wildcard `*.lan.igou.systems`, same issuer. Tier domains are cluster-agnostic — both clusters hold this wildcard |

## Onboarding an app onto a tier

1. Label the app namespace: `gateway-access/<tier>: "true"`
   (`gateway-access/guest-dmz` or `gateway-access/trusted-lan`).
2. Create an HTTPRoute with `parentRefs` → the tier Gateway /
   `namespace: openshift-ingress`, hostname `<app>.<domain>` (`dmz` or
   `lan` `.igou.systems`), and the backend Service. For long-lived streams
   set `rules[].timeouts.request: 0s`. Websocket upgrades require the
   backend Service port to have an `http`-prefixed name.
3. rb5009 (igou-inventory): add a static DNS record for the hostname
   pointing at the tier VIP (`10.10.152.3` guest-dmz, `10.10.150.3`
   trusted-lan) — explicit per-hostname records only, no tier-domain
   wildcards. For guest-dmz, add a per-VLAN pinhole to
   `10.10.152.3 tcp/443` if a new VLAN needs access; trusted-lan admits
   VLAN 9/10/99 tier-wide already.

## Constraints (verified against the OCP 4.21 docs — see #367)

- Gateways are only reconciled in `openshift-ingress`; listener
  certificates must live there too (or need ReferenceGrants).
- The generated Service is `externalTrafficPolicy: Cluster` with no
  supported override: apps see node IPs (XFF carries the node, not the
  client), and the VIP is BGP-advertised from all nodes (ECMP).
- Listeners are Terminate/Passthrough only — no TLS re-encrypt to
  backends.
- Anything routed onto a tier Gateway is reachable by every VLAN admitted
  to that tier's VIP — per-app L4 firewall granularity does not exist on
  a shared VIP. Apps needing different exposure belong on a different
  tier's Gateway.
- Raw Istio APIs are unsupported; only Gateway API configuration.
- Pre-flight (verified clean 2026-07-02): no OSSM v2.x Subscription may
  exist on the cluster (`GatewayAPIOSSMConflict`), and the Gateway API
  CRDs must remain the operator-managed bundle (community CRDs trigger an
  upgrade admin-gate).

## DNS on bare metal

The operator creates a `DNSRecord` CR per listener hostname but only
publishes via cloud DNS providers. On this cluster DNS is self-managed on
the rb5009 — the `DNSRecord` CRs stay unpublished; verify they do not
drive the `ingress` ClusterOperator Degraded.

## Adding another tier

Copy the Gateway + Certificate pair with the tier's pool name and a free
pinned VIP from that tier's `IPAddressPool` (see
`clusters/ocp/metallb/`), and matching rb5009 DNS/pinholes in
igou-inventory.
