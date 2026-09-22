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
