# OpenShift public service endpoints

This chart owns one OpenShift namespace, `public-services`, for application
pods and their private Tailscale-backed Services. Empty default values create
the namespace guardrails without publishing an endpoint. The chart remains
registered by the `public-services` platform Application with an empty service
list. Its companion reader identity is in `components/public-services`; no
application is published until an endpoint is explicitly configured.

`examples/web-test-values.yaml` selects the deployed `public-web-test` pods
from `test-workloads/public-services-web` on TCP 8080. It creates a separate
Tailscale Service, `public-web-test-public`, preserving the fixture's existing
ClusterIP Service. Render it locally:

```bash
helm template public-services .helm/charts/tailscale-public-services \
  -f .helm/charts/tailscale-public-services/examples/web-test-values.yaml
```

These endpoint values remain staged. The matching VPS examples expose HTTPS
or raw TCP to the same HTTP server. The separate `examples/udp-values.yaml`
selects the `udp-echo` workload in `test-workloads/public-services-udp` on UDP
9000. That staged workload uses `agnhost netexec` to answer echo and hostname
requests. The web fixture does not serve UDP.

Each entry requires a Service name, pod selector, distinct tailnet hostname,
application-specific `tag:ocp-public-*` tag, and named ports. Target ports may
be numbers or named container ports.
Services use `loadBalancerClass: tailscale`, without NodePorts or MetalLB.

The namespace enforces restricted Pod Security and denies ingress and egress
by default. Every endpoint gets an ingress policy allowing only its own
Service-managed Tailscale proxy pods on the declared target ports. The only
default egress allowance is cluster DNS, including OpenShift's post-NAT port
5353. Dependencies, internet access, and communication between applications
need separate reviewed allowances; colocating pods grants no network access.
Admission policy rejects secondary/default-network override annotations in
this namespace so pods cannot bypass that boundary with a Multus attachment.

The default ServiceAccount does not mount an API token. A ResourceQuota caps
CPU, memory, pods, Services, LoadBalancers, PVCs, and storage; a LimitRange
sets container defaults. Resource budgets are configurable in `values.yaml`.
No namespace users or RBAC permissions are granted by this chart. Give
workload deployers a narrow Role rather than namespace-wide `edit` access
that would let them change the guardrails. NetworkPolicies are additive.

Adopt this chart once as a platform-owned Kustomization and keep its guardrails
separate from per-share cleanup. Deploy public-facing application pods into
`public-services` and supply their selectors in the central service list.
Selectors cannot reach workloads in other namespaces; there is no per-service
namespace override. Existing applications are not moved by this chart.
The Tailscale operator must already exist.
Authorize the operator to mint the selected tag and grant the VPS egress
identity access to only the chosen ports. The matching VPS chart lives in
`igou-kubernetes/.helm/charts/tailscale-public-services`.

The design and rollout checks are in igou-docs:
`networking/Tailnet Access Model - Tailscale Operators on Both Clusters.md`.
