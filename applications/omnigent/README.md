# Omnigent

Use <https://omnigent.apps.ocp.igou.systems> for interactive sessions and its
REST API for pipeline launches. In **New Chat**, choose `opencode-go-test`
and a new OpenShell sandbox in the host picker. OpenShell is the only backend
for new sessions. Admin login manages application access, but does not
provide a backend configuration editor.

The operator runbook is
[Omnigent Managed Sandboxes and API Workflows](https://github.com/igou-io/igou-docs/blob/main/openshift/Omnigent%20Managed%20Sandboxes%20and%20API%20Workflows.md).
It covers new backends, harnesses, OpenShell configuration, OpenShell
service authentication, and autonomous REST launches.

## Where to change settings

| Setting | Source in this directory |
|---|---|
| Backend list, image, model binding, callback URL | `omnigent-sandbox-config-configmap.yaml` |
| Agent prompt, harness, model, model-provider name | `omnigent-test-agent-configmap.yaml` |
| Server auth, machine-token lifetime, environment forwarding | `omnigent-config-configmap.yaml` |
| OpenShell gateway endpoint and OIDC metadata | `omnigent-openshell-gateway-configmap.yaml` |
| OpenShell host filesystem and network access | `openshell-host-policy.yaml`, mounted on the server and sent at sandbox creation |
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

The OpenShell backend creates sandboxes through the existing gateway in
`openshell`. It uses the Agent Sandbox operator, ordinary CRI-O, and the
`openshell-sandbox` ServiceAccount's privileged SCC. It runs the published
devenv image directly, with Omnigent and proxy-aware WebSockets baked into
read-only `/opt/omnigent`. The server sends the policy when creating each
sandbox. Harnesses come from devenv: OpenCode, Codex, and Claude Code are
exposed on PATH. The launcher performs no harness installation. The policy
allows the Omnigent callback and OpenCode Go for the installed OpenCode binary.

The existing server image patch also supplies creation-time policy and the
sandbox executable PATH (`patch_openshell_policy.py`). The policy is in a
generated ConfigMap; its content hash triggers a server rollout. OpenCode's
real binary precedes the local workstation launcher shim on PATH; OpenShell
provides the outer sandbox.

The server patch supplies renewable OAuth client credentials to the
OpenShell 0.0.116 SDK. `omnigent-openshell` needs the Keycloak
`openshell-user` role and `user` membership in the gateway's `default`
workspace. Gateway membership is persistent OpenShell state, not a ConfigMap.

The `opencode-go-test` agent uses OpenCode, `glm-5.3-flash`, and the OpenCode Go key from External
Secrets. The `codex-chatgpt` agent uses Codex and the ChatGPT account cached
on the separate `omnigent-codex-auth` PVC in `openshell`. Their caller-process
tools run inside the outer sandbox, without a second nested sandbox. Neither
agent has Git or cluster credentials. Built-in `accounts` auth has
passed the recorded smoke tests; upstream still warns about managed-runner
WebSocket compatibility. Recheck it after auth or image upgrades.

OpenCode's provider/model binding is in `sandbox.host_config.inference.harnesses`.
Its native integration requires that profile in addition to the agent's
`executor.auth`. Provider `default` entries name protocol families, not harnesses.
The OpenCode Go binding does not configure Codex or Claude Code. Codex uses
`CODEX_HOME=/codex-auth`; the server mounts the RWX auth claim outside
`/sandbox` so OpenShell keeps its per-sandbox workspace PVC. The launcher
creates `config.toml` with file-backed credentials if missing, then Omnigent
links `auth.json` into each Codex session's private home. OpenShell policy
allows Codex's login and model endpoints. This claim is mounted into every
Omnigent OpenShell sandbox, so only trusted users and agents should be given
these sandboxes. Serialize Codex jobs using this account to avoid concurrent
token refreshes. Initial ChatGPT device authorization is an interactive step;
see the operator runbook. Claude Code still needs separate credentials.

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
The former Kubernetes runner Jobs and their support resources remain until
their existing sessions are retired; they are no longer offered for new ones.

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

Expect `openshell` as the default and sole entry in `sandbox_providers`.
A successful session-create response or HTTP 202 prompt acknowledgement does
not prove agent completion. Read the assistant output and check task-specific
results. Delete disposable sessions through Omnigent to reclaim their backend.
