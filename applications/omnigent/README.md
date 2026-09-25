# Omnigent

Use <https://omnigent.apps.ocp.igou.systems> for interactive sessions and its
REST API for pipeline launches. In **New Chat**, choose `opencode-go-test`
and a new sandbox in the host picker. Kubernetes is the default; OpenShell
is also configured. Admin login manages application access, but does not
provide a backend configuration editor.

The operator runbook is
[Omnigent Managed Sandboxes and API Workflows](https://github.com/igou-io/igou-docs/blob/main/openshift/Omnigent%20Managed%20Sandboxes%20and%20API%20Workflows.md).
It covers new backends, harnesses, both sandbox configurations, OpenShell
service authentication, and autonomous REST launches.

## Where to change settings

| Setting | Source in this directory |
|---|---|
| Backend list, default, runner sizes, images, placement, callback URL | `omnigent-sandbox-config-configmap.yaml` |
| Agent prompt, harness, model, model-provider name | `omnigent-test-agent-configmap.yaml` |
| Server auth, machine-token lifetime, environment forwarding | `omnigent-config-configmap.yaml` |
| OpenShell gateway endpoint and OIDC metadata | `omnigent-openshell-gateway-configmap.yaml` |
| OpenShell host filesystem and network access | `openshell-host-policy.yaml`, mounted on the server and sent at sandbox creation |
| Pi installation in each new OpenShell sandbox | `openshell-host-setup.sh` |
| OpenShell SDK and renewable service authentication | `Containerfile.openshell`, `patch_openshell_service_auth.py` |
| Secret references | `*-externalsecret.yaml` |
| Server mounts, image, restart trigger | `omnigent-deployment.yaml` |

The OpenShell gateway's own settings live in
[`../openshell/kustomization.yaml`](../openshell/kustomization.yaml).
Changing its default sandbox image does not change Omnigent's explicit host
image. Omnigent's model provider `opencode-go` is separate from OpenShell's
stored inference providers.

## Runtime

One server in `omnigent` stores conversations in CNPG and artifacts on a
10 Gi PVC. Keep one replica because the runner registry is in memory.
`Recreate` avoids overlapping Pods trying to attach the ReadWriteOnce volume.
CNPG uses Barman for WAL archiving and nightly backups.

The Kubernetes backend creates Jobs in `omnigent-sandboxes`. Runners use
`nonroot-v2`, no mounted ServiceAccount token, and ephemeral home storage.
The `kata-runtime=enabled` node selector chooses eligible workers; it does
not select Kata. No runtime class is set. Jobs have a seven-day deadline.

The OpenShell backend creates sandboxes through the existing gateway in
`openshell`. It uses the Agent Sandbox operator, ordinary CRI-O, and the
`openshell-sandbox` ServiceAccount's privileged SCC. It runs the published
devenv image directly, with Omnigent and proxy-aware WebSockets baked into
read-only `/opt/omnigent`. The server sends the policy when creating each
sandbox, then installs pinned Pi under writable `/sandbox/.local`. No Python
runtime bootstrap is needed. The policy allows Node under `/opt/mise`, the
Omnigent callback, OpenCode Go, and npm registry access.

The existing server image patch also supplies creation-time policy and the
sandbox executable PATH (`patch_openshell_policy.py`). Policy/setup files are
in a generated ConfigMap; its content hash triggers a server rollout. A failed
Pi setup deletes the newly provisioned sandbox.

The server patch supplies renewable OAuth client credentials to the
OpenShell 0.0.116 SDK. `omnigent-openshell` needs the Keycloak
`openshell-user` role and `user` membership in the gateway's `default`
workspace. Gateway membership is persistent OpenShell state, not a ConfigMap.

The seeded agent uses Pi, `glm-5.3-flash`, and the OpenCode Go key from External
Secrets. Its caller-process tools run inside the outer sandbox, without a
second nested sandbox. It has no Git or cluster credentials. Built-in `accounts` auth has
passed the recorded smoke tests; upstream still warns about managed-runner
WebSocket compatibility. Recheck it after auth or image upgrades.

## Apply configuration changes

Edit the files in Git and render with `kustomize build applications/omnigent`.
For sandbox-config changes, put the output of this command into the Deployment
Pod annotation `omnigent.io/sandbox-config-sha256` in the same change:

```bash
sha256sum applications/omnigent/omnigent-sandbox-config-configmap.yaml
```

The config uses a `subPath` mount and requires a new server Pod. Other
startup configuration and Secret rotations also require a server rollout;
ConfigMap reconciliation alone does not reload the process. Keep that rollout
in the GitOps change. New sandboxes use changed images and settings; existing
sandboxes keep their launch configuration.

## Verify

```bash
use ocp-cluster-reader
oc whoami --show-server
oc whoami
oc get applications.argoproj.io omnigent openshell -n openshift-gitops
oc get deployment,route,cluster.postgresql.cnpg.io,externalsecret -n omnigent
oc get jobs,pods -n omnigent-sandboxes
oc get sandboxes.agents.x-k8s.io,pods -n openshell
curl -fsS https://omnigent.apps.ocp.igou.systems/v1/info |
  jq '{managed_sandboxes_enabled, sandbox_provider, sandbox_providers}'
```

Expect `kubernetes` as the default and both backends in `sandbox_providers`.
A successful session-create response or HTTP 202 prompt acknowledgement does
not prove agent completion. Read the assistant output and check task-specific
results. Delete disposable sessions through Omnigent to reclaim their backend.
