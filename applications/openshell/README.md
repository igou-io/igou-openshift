# OpenShell

OpenShell 0.0.116 runs as a lab gateway backed by the existing Red Hat Agent
Sandbox operator. The gateway and dynamically created sandboxes share the
`openshell` namespace.

## Security posture

- The gateway is a single SQLite-backed StatefulSet and is not highly
  available.
- The gateway terminates TLS with a public certificate issued by `cluster-acme`
  for `openshell.apps.ocp.igou.systems`. An OpenShift passthrough Route preserves
  end-to-end TLS.
- CLI users authenticate against the existing Keycloak `igou` realm. Anonymous
  access is disabled; `openshell-admin` and `openshell-user` realm roles control
  API authorization.
- Sandbox pods use the ordinary CRI-O runtime. No `RuntimeClass` is configured.
- OpenShell 0.0.116 requires its sandbox ServiceAccount to use the OpenShift
  `privileged` SCC. The grant is scoped to `system:serviceaccount:openshell:openshell-sandbox`.
- Anonymous OpenShell telemetry is disabled.

Do not treat this release as a production security boundary. Reassess the SCC,
database, workspace isolation, and chart values when upgrading to OpenShell
0.1.x.

## Dependencies

- Red Hat Agent Sandbox operator serving `agents.x-k8s.io/v1beta1`
- External Secrets Operator and `onepassword-lab-agents`
- 1Password item `lab_agents/openshell`, field `key-encryption-key`
- `freenas-nvmeof-ssd-csi`

The chart's Agent Sandbox preflight is disabled only because Kustomize inflates
Helm without live API discovery. The API was verified on the target cluster.
The parent `clusters/ocp` application creates the `openshell` namespace before
the child application so the chart's native PreSync certificate/JWT hook can
run during the first sync.

## Connect

```bash
oc -n openshell rollout status statefulset/openshell
openshell gateway add https://openshell.apps.ocp.igou.systems \
  --name ocp \
  --oidc-issuer https://keycloak.apps.ocp.igou.systems/realms/igou \
  --oidc-client-id openshell-cli \
  --oidc-audience openshell-cli
openshell gateway login ocp
openshell status
openshell whoami
```

Set `OPENSHELL_NO_BROWSER=1` for device authorization from a headless shell.
The Keycloak client enforces S256 PKCE for browser login and enables the device
authorization grant.

## Verify a sandbox

```bash
openshell sandbox create --name smoke-test -- bash
openshell sandbox exec --name smoke-test -- uname -a
openshell sandbox delete smoke-test
```

The resulting sandbox pod must not have `spec.runtimeClassName` set.

## OpenCode Go provider

The `opencode-go` provider supplies Codex credentials without placing the API
key in the sandbox specification or wrapper command. Its non-secret profile is
versioned in `provider-profiles/opencode-go-codex.yaml`; the gateway stores the
credential in its encrypted SQLite database on the persistent volume.

Bootstrap the provider after restoring or replacing the gateway database:

```bash
openshell --gateway ocp settings set --global --yes \
  --key providers_v2_enabled \
  --value true
openshell provider profile lint \
  --file applications/openshell/provider-profiles/opencode-go-codex.yaml
openshell --gateway ocp provider profile import \
  --file applications/openshell/provider-profiles/opencode-go-codex.yaml
read -rsp 'OpenCode Go API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
openshell --gateway ocp provider create \
  --name opencode-go \
  --type opencode-go-codex \
  --credential OPENAI_API_KEY
unset OPENAI_API_KEY
```

Do not commit the API key. The current MVP uses the operator's existing
OpenCode credential; secret-manager integration remains a follow-up.

## Configuration ownership

| Setting | Where to configure it |
|---|---|
| Gateway image, TLS, Route, OIDC roles, storage, sandbox defaults | `kustomization.yaml` under `helmCharts[].valuesInline` |
| Sandbox SCC grant | `openshell-sandbox-privileged-clusterrolebinding.yaml` |
| Private sandbox image pulls | `server.sandboxImagePullSecrets` and the referenced ExternalSecret |
| Workspace membership | OpenShell workspace CLI/API; persisted in the gateway database |
| Stored inference providers and credentials | OpenShell provider CLI/API; persisted in the gateway database |
| Effective sandbox policy | Image policy, plus any gateway-global or live sandbox policy |
| Omnigent host image and policy | `../omnigent/omnigent-sandbox-config-configmap.yaml` and `../omnigent/openshell-host-policy.yaml` |

`server.defaultRuntimeClassName` is empty and `server.appArmorProfile` is
empty for this OpenShift deployment. Gateway `resources` size the gateway
Pod, not each agent sandbox. Workspace defaults are 10 Gi on
`freenas-nvmeof-ssd-csi`. Do not change the runtime class solely because a
worker has the `kata-runtime=enabled` label; validate the supervisor, SCC,
and runtime combination first.

Omnigent talks to OpenShell through its gRPC SDK. Pipelines use Omnigent's
REST API and select `sandbox_provider: openshell`; they do not need to call
the gateway directly. Omnigent's service client is `omnigent-openshell`,
with the `openshell-user` realm role and `user` membership in `default`.
The endpoint metadata mounted into Omnigent is not an authentication token.
Its custom server image obtains and renews tokens with client credentials.

See the [Omnigent runbook](https://github.com/igou-io/igou-docs/blob/main/openshift/Omnigent%20Managed%20Sandboxes%20and%20API%20Workflows.md)
for adding backends and configuring the two sides together. Swarmer is a
separate UI client of this gateway, documented in `../swarmer/README.md`.
