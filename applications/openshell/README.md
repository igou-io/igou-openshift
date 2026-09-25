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
openshell --gateway ocp sandbox create --name smoke-test -- sleep infinity
openshell --gateway ocp sandbox exec --name smoke-test -- sh -lc 'command -v codex; command -v claude; command -v opencode'
openshell --gateway ocp sandbox exec --name smoke-test -- uname -a
openshell --gateway ocp sandbox delete smoke-test
```

This uses the pinned `ghcr.io/igou-io/igou-devenv` image directly. The
resulting sandbox pod must not have `spec.runtimeClassName` set. Creating a
sandbox without `--policy` uses OpenShell's built-in restrictive policy;
agent network access requires an explicit policy for the selected provider,
endpoints, and executable paths. Omnigent sends its own policy when it creates
managed sandboxes.

The former `openshell-devenv` image, GLM protocol adapter, and
`opencode-go-devenv` provider are no longer part of this GitOps deployment.
OpenCode Go serves GLM Flash through Chat Completions; the installed Codex and
Claude Code clients require different protocols. Omnigent uses OpenCode for
GLM Flash and Codex with its persistent ChatGPT login. Existing gateway
provider records are stored in SQLite and are not removed by GitOps.

## Configuration ownership

| Setting | Where to configure it |
|---|---|
| Gateway image, TLS, Route, OIDC roles, storage, sandbox defaults | `kustomization.yaml` under `helmCharts[].valuesInline` |
| Sandbox SCC grant | `openshell-sandbox-privileged-clusterrolebinding.yaml` |
| Default sandbox image | `server.sandboxImage`; Omnigent currently pins the same devenv digest in its own backend configuration |
| Workspace membership | OpenShell workspace CLI/API; persisted in the gateway database |
| Stored inference providers and credentials | OpenShell provider CLI/API; persisted in the gateway database |
| Effective sandbox policy | OpenShell's built-in restrictive policy, plus any creation-time or live sandbox policy |
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
