# Public service workload examples

Three independent workload examples target the fixed `public-services` namespace.
All three are deliberately scaled to zero while public-service egress isolation
is being redesigned. To resume testing, set the selected Deployment's replicas
to one through GitOps after reviewing that design.
Each folder contains the application, ClusterIP Service, Tailscale endpoint
Service, and a NetworkPolicy allowing only that endpoint's own proxy pods.

| Example | Workload | Backend | Tailscale Service | VPS sharing example |
| --- | --- | --- | --- | --- |
| `http/` | nginx, `public-web-test` | HTTP on TCP 8080 | `public-web-test-public` | `igou-kubernetes/examples/public-services/http/` |
| `tcp/` | agnhost, `tcp-hostname` | Raw TCP 9000 | `tcp-hostname-public` | `igou-kubernetes/examples/public-services/tcp/` |
| `udp/` | agnhost, `udp-echo` | UDP 9000 | `udp-echo-public` | `igou-kubernetes/examples/public-services/udp/` |

The HTTP objects keep their existing names through the folder reorganization.
Current deployment status and ad hoc verification evidence are recorded in
`igou-docs/networking/Public Service Sharing with AAP.md`.

The platform's `.helm/charts/tailscale-public-services` chart owns the namespace,
restricted pod security, default-deny networking, DNS egress, resource budget,
and admission policy. Install those guardrails once before these examples.
The Tailscale operator must be installed and authorized to mint the shared
`tag:ocp-public-service` tag. One tailnet grant allows
`tag:vps-public-service` to reach it on all TCP and UDP ports. The Services
and NetworkPolicies restrict each proxy to its declared application ports.
See the matching igou-docs public-sharing note.

Render one workload or all three from this repository:

```bash
kustomize build test-workloads/public-services/http
kustomize build test-workloads/public-services
```

For an authorized manual installation, verify the cluster and identity first:

```bash
oc whoami --show-server
oc whoami
oc apply -n public-services -k test-workloads/public-services/http
oc rollout status deployment/public-web-test -n public-services
```

Choose `tcp` or `udp` for the other examples. The parent Kustomization includes
all three. Services and policies contain the fixed namespace; none creates a
new namespace or moves application pods elsewhere.

Workloads and stable endpoints have no share-expiration metadata. AAP cleanup
removes only the temporary forwarding objects it creates on the VPS. If these
native endpoint manifests own a Service, do not also list it in the platform
chart's `services` values.

Remove an example with `oc delete -n public-services -k` and its folder path.
That removes its workload, endpoint, and ingress policy while preserving the
shared namespace and guardrails.

All three Deployments require the existing `kata` RuntimeClass. Each pod has
250m CPU/350Mi memory runtime overhead on this cluster; include that in quota
and capacity planning. They need no DNS egress. Namespace admission enforces
the sandbox and token/volume restrictions, including on future workloads.
