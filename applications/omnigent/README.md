# Omnigent

## Deployment path

This application is a Kustomize adaptation of Omnigent's documented
[`sandbox-runners` Kubernetes overlay](https://github.com/omnigent-ai/omnigent/tree/f33d43262b8ab963e6edac4913bae46353c32b10/deploy/kubernetes/overlays/sandbox-runners)
and [OpenShift overlay](https://github.com/omnigent-ai/omnigent/tree/f33d43262b8ab963e6edac4913bae46353c32b10/deploy/kubernetes/overlays/openshift)
(upstream revision `f33d43262b8ab963e6edac4913bae46353c32b10`). The local
manifests preserve the upstream server image variant, `kubernetes` sandbox
provider, dedicated runner namespace, namespaced Job permissions, and
entrypoint-based runner Jobs. They replace upstream's placeholder Secret,
Ingress, and bundled Postgres with External Secrets, an OpenShift Route, and
CNPG. `kustomize build applications/omnigent` renders the application for
ArgoCD; no Helm chart or Kata RuntimeClass is involved.

Omnigent runs as a single server in `omnigent`. A managed session creates one
runner Job in `omnigent-sandboxes`. Runners use the normal CRI-O runtime; this
evaluation does not request Kata or the Agent Sandbox controller. The existing
`kata-runtime=enabled` node label selects `hpg5` or `p330` as worker hosts;
`runtimeClassName` remains unset.

The server uses `omnigent-pg` (CNPG) for sessions and a 10 Gi PVC for artifacts.
CNPG archives WAL and takes nightly full backups through the existing Barman
Cloud Plugin and `cnpg-backups` bucket. The `cloudnative-pg` namespace has an
additive `allow-omnigent` NetworkPolicy so the operator can read the instance's
status endpoint and the instance can reach the Barman plugin.
Only the server ServiceAccount can create runner Jobs and launch-token Secrets.
The runner ServiceAccount has no Kubernetes API rights and uses the `nonroot-v2`
SCC for the upstream image's fixed non-root UID. The runner receives only the
OpenCode Go subscription key through `omnigent-creds`; the key is sourced from
`op://lab_agents/opencode-go-subscription-key/password`. The server's account
cookie secret and initial admin password come from `op://lab_agents/omnigent`.
The initial admin username is `igou`.

Upstream currently documents `header` or OIDC auth for managed runners and
warns that its built-in `accounts` mode can reject the runner WebSocket with
`403`. This proof uses `accounts` and completed an OpenCode Go API smoke test,
but that result does not establish long-term support for this combination.
Before broader use, move the server to a trusted OIDC or identity-injecting
proxy configuration and repeat the managed-session test.

The test agent is seeded from `omnigent-test-agent` at server startup and uses
Pi with OpenCode Go's OpenAI-compatible endpoint. Both upstream images are
pinned to the digests tested here. The server stays at one replica because the
runner registry is in memory.

## Verify

```bash
oc get externalsecret -n omnigent
oc get externalsecret -n omnigent-sandboxes
oc get cluster.postgresql.cnpg.io -n omnigent
oc rollout status deployment/omnigent -n omnigent
oc get jobs,pods -n omnigent-sandboxes
oc get route omnigent -n omnigent
```

Use the account credentials in `op://lab_agents/omnigent` at
`https://omnigent.apps.ocp.igou.systems`. The REST API creates managed sessions
with `POST /v1/sessions` and `host_type: managed`. The `opencode-go-test` agent
is for the first API smoke test; it has no cluster or Git credentials.

Deleting a session through the API removes its runner Job. Runners have a
seven-day Job deadline if abandoned. The `agent_sandbox` provider is a possible
follow-up after the Job-based path is proven.
