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
`op://lab_agents/opencode-go-subscription-key/password`. The server also
receives that key through `omnigent-opencode-go` for OpenShell sandbox injection.
The server's account
cookie secret and initial admin password come from `op://lab_agents/omnigent`.
The initial admin username is `igou`.

Upstream currently documents `header` or OIDC auth for managed runners and
warns that its built-in `accounts` mode can reject the runner WebSocket with
`403`. This proof uses `accounts` and completed an OpenCode Go API smoke test,
but that result does not establish long-term support for this combination.
Before broader use, move the server to a trusted OIDC or identity-injecting
proxy configuration and repeat the managed-session test.

The test agent is seeded from `omnigent-test-agent` at server startup and uses
Pi with OpenCode Go's OpenAI-compatible endpoint. All images are
pinned to the digests tested here. The server stays at one replica because the
runner registry is in memory. The Deployment uses `Recreate` because its
artifact PVC is ReadWriteOnce; a rolling surge on a different node cannot
attach the same volume until the old Pod stops.

## OpenShell provider

The `sandbox.providers` list offers both backends. Kubernetes stays first and
is the default. A managed session requesting `sandbox_provider: openshell`
asks the existing OpenShell gateway to create an Agent Sandbox in its `default`
workspace. The gateway uses the Agent Sandbox operator and normal CRI-O on
this cluster. This provider does not create Omnigent Jobs in
`omnigent-sandboxes`; the gateway owns the `AgentSandbox` object and Pod.

`Containerfile.openshell` adds the OpenShell 0.0.116 SDK to the pinned
Kubernetes server image. The small source patch passes a renewable OAuth
client-credentials provider to the SDK because upstream's launcher only reads
a CLI user's login state. The `omnigent-openshell` Keycloak client has the
`openshell-user` realm role and a `user` membership in OpenShell's `default`
workspace. Its client secret lives in
`op://lab_agents/omnigent-openshell/OPENSHELL_CLIENT_SECRET`; External Secrets
project it into the server. The gateway's non-secret endpoint and OIDC metadata
are mounted at `/etc/openshell/gateways/ocp/metadata.json`.

`Containerfile.openshell-host` extends the pinned Omnigent host with
`/etc/openshell/policy.yaml`. The policy allows the Omnigent Route for the
managed host WebSocket and `opencode.ai` for the test agent. OpenShell injects
proxy settings into the host; `OMNIGENT_RUNNER_ENV_PASSTHROUGH` forwards them
to the runner subprocess. The OpenCode Go key is injected by name from the
server environment; it is never written into an image or ConfigMap. Both
custom images are pushed to the in-cluster Quay and pinned by digest.

### Change the sandbox image

For Kubernetes, edit `sandbox.providers[0].kubernetes.image` in
`omnigent-sandbox-config-configmap.yaml`. The image must contain the Omnigent
host entrypoint and run under the `nonroot-v2` SCC as `omnigent-runner`.

For OpenShell, edit `Containerfile.openshell-host` and
`openshell-host-policy.yaml`, build and push the image, then change
`sandbox.providers[1].openshell.image` to its digest. Preserve the `sandbox`
user, `ip`/`nft`, Omnigent host entrypoint, and policy path. The gateway's
`server.sandboxImage` is its default for direct OpenShell clients; Omnigent
supplies its own image per session. Existing sessions keep their original
image. Build and publish commands are in the Omnigent runbook in `igou-docs`.

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

Deleting a session through the API removes its Kubernetes runner Job or
OpenShell sandbox. Kubernetes runners have a seven-day Job deadline if
abandoned.
