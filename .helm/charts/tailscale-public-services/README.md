# OpenShift public service endpoints

This chart creates private Tailscale-backed Services for applications that
will be reached through the VPS. It renders nothing with the default values.
No application or Argo entry is enabled by adding this chart.

`examples/arena-values.yaml` covers HTTP, TCP, and UDP ports for an illustrative
application. Render it locally:

```bash
helm template public-services .helm/charts/tailscale-public-services \
  -f .helm/charts/tailscale-public-services/examples/arena-values.yaml
```

Each entry requires a Service name, an existing application namespace, pod
selector, distinct tailnet hostname, application-specific `tag:ocp-public-*`
tag, and named ports. Target ports may be numbers or named container ports.
Services use `loadBalancerClass: tailscale`, without NodePorts or MetalLB.

`allowFromTailscale` optionally creates an ingress NetworkPolicy that allows
only this Service's managed proxy pods on its target ports. Leave it false
until existing policy is reviewed: adding the first ingress policy for a pod
also isolates it from other callers. Policies are additive; this rule cannot
remove access allowed by another policy. The chart does not change egress.

To adopt an endpoint, include this local chart in the application's
Kustomization, supply reviewed values, and register through the usual GitOps
path. The Tailscale operator and application namespace must already exist.
Authorize the operator to mint the selected tag and grant the VPS egress
identity access to only the chosen ports. The matching VPS chart lives in
`igou-kubernetes/.helm/charts/tailscale-public-services`.

The design and rollout checks are in igou-docs:
`networking/Tailnet Access Model - Tailscale Operators on Both Clusters.md`.
