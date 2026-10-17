# OpenShift public service endpoints

This chart owns one OpenShift namespace, `public-services`, for application
pods and their private Tailscale-backed Services. Empty default values create
the namespace guardrails without publishing an endpoint. The chart remains
registered by the `public-services` platform Application with an empty service
list. Its companion reader identity is in `components/public-services`; no
application is published until an endpoint is explicitly configured.

The three complete workload examples live in
`test-workloads/public-services/http`, `tcp`, and `udp`. Each owns its native
Tailscale endpoint Service and ingress policy alongside the application.
The paired VPS sharing examples live in `igou-kubernetes/examples/public-services/`.
Keep example-owned endpoints out of this chart's `services` values to avoid
reconciling the same object from two sources.

Each entry requires a Service name, pod selector, distinct tailnet hostname,
and named ports. All endpoint proxies use the chart-wide `proxyTag`, which
defaults to `tag:ocp-public-service`. Target ports may be numbers or named
container ports.
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

Adopt this chart once as a platform-owned Helm Application and keep its guardrails
separate from per-share cleanup. Deploy public-facing application pods into
`public-services` and supply their selectors in the central service list.
Selectors cannot reach workloads in other namespaces; there is no per-service
namespace override. Existing applications are not moved by this chart.
The Tailscale operator must already exist.
Authorize `tag:k8s-operator` to mint `tag:ocp-public-service`. One tailnet grant
allows `tag:vps-public-service` to reach `tag:ocp-public-service` on all TCP
and UDP ports. Adding a service requires no new tags or tailnet policy edits;
its Service and NetworkPolicy still declare the backend ports. The matching VPS chart lives in
`igou-kubernetes/.helm/charts/tailscale-public-services`.

The design and rollout checks are in igou-docs:
`networking/Tailnet Access Model - Tailscale Operators on Both Clusters.md`.
