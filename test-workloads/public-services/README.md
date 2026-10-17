# Public service workload examples

Three independent workloads run in the fixed `public-services` namespace.
Each folder contains the application, ClusterIP Service, Tailscale endpoint
Service, and a NetworkPolicy allowing only that endpoint's own proxy pods.

| Example | Workload | Backend | Tailscale Service | VPS sharing example |
| --- | --- | --- | --- | --- |
| `http/` | nginx, `public-web-test` | HTTP on TCP 8080 | `public-web-test-public` | `igou-kubernetes/examples/public-services/http/` |
| `tcp/` | agnhost, `tcp-hostname` | Raw TCP 9000 | `tcp-hostname-public` | `igou-kubernetes/examples/public-services/tcp/` |
| `udp/` | agnhost, `udp-echo` | UDP 9000 | `udp-echo-public` | `igou-kubernetes/examples/public-services/udp/` |

The HTTP pod and ClusterIP Service are already deployed. TCP, UDP, and all
Tailscale endpoints remain staged. The HTTP objects keep their existing names;
the folder move does not require replacing the deployed workload.

The platform's `.helm/charts/tailscale-public-services` chart owns the namespace,
restricted pod security, default-deny networking, DNS egress, resource budget,
and admission policy. Install those guardrails once before these examples.
The Tailscale operator must be installed and authorized to mint the three
endpoint tags. Tailnet grants must permit the VPS egress tag to reach only
the selected backend ports. See the matching igou-docs public-sharing note.

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
