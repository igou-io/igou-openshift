# remote-tenant

Per-user, locked-down OpenShift namespace reachable over the tailnet via the
Tailscale API-server proxy. Each tenant gets a Namespace + ResourceQuota +
LimitRange + default-deny NetworkPolicies + a `RoleBinding(group -> role)`,
pinned to the `hpg5`/`p330` worker pool. Two shared, once-rendered resources:
the `remote-tenant-operator` ClusterRole and the `remote-tenant-no-burst` /
`remote-tenant-no-secondary-net` ValidatingAdmissionPolicies.

See the design spec: `docs/superpowers/specs/2026-06-13-remote-tenant-access-design.md`.

## One-time cluster prerequisites

1. Enable the Tailscale API-server proxy (set in
   `components/tailscale-operator/kustomization.yaml`: `apiServerProxyConfig.mode: "true"`).
2. Label the tenant worker pool:
   ```
   oc label node hpg5.igou.systems node-role.kubernetes.io/tenant=""
   oc label node p330.igou.systems node-role.kubernetes.io/tenant=""
   ```

## Onboarding a tenant

1. Add an entry to `clusters/ocp/remote-tenants/values.yaml` under `tenants:`
   (see the schema in `values.yaml`). Open a PR; ArgoCD syncs the namespace,
   guardrails, and RoleBinding.
2. Add the grant block printed by the chart NOTES (or below) to the Tailscale
   ACL policy in the admin console:
   ```json
   { "src": ["alice@example.com"], "dst": ["tag:k8s-operator"],
     "app": { "tailscale.com/cap/kubernetes": [ { "impersonate": { "groups": ["alice-dev-operator"] } } ] } }
   ```
   The impersonated group MUST equal the tenant's `grantGroup` (default
   `<name>-operator`).
3. The user runs:
   ```
   tailscale up
   tailscale configure kubeconfig tailscale-operator
   oc -n alice-dev get pods
   ```

## Offboarding

Remove the grant (immediate API cut-off) and the `tenants:` entry (ArgoCD
prunes the namespace).

## Optional: kubectl session recording

Add `"recorder": ["tag:tsrecorder"], "enforceRecorder": true` to the grant and
deploy a `Recorder` CR to record all kubectl/exec/API sessions.
