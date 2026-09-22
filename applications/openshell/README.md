# OpenShell

OpenShell 0.0.116 runs as an evaluation-only gateway backed by the existing Red
Hat Agent Sandbox operator. The gateway and dynamically created sandboxes share
the `openshell` namespace.

## Security posture

- The gateway is a single SQLite-backed StatefulSet and is not highly
  available.
- The Service is cluster-internal. There is no Route, OIDC client, or public
  endpoint; connect through `oc port-forward` only.
- TLS is disabled in accordance with NVIDIA's OpenShift evaluation procedure.
- Sandbox pods use the ordinary CRI-O runtime. No `RuntimeClass` is configured.
- OpenShell 0.0.116 requires its sandbox ServiceAccount to use the OpenShift
  `privileged` SCC. The grant is scoped to `system:serviceaccount:openshell:openshell-sandbox`.
- Anonymous OpenShell telemetry is disabled.

Do not treat this release as a production security boundary. Reassess the SCC,
TLS/OIDC, ingress, database, workspace isolation, and chart values when upgrading
to OpenShell 0.1.x.

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
oc -n openshell port-forward service/openshell 8080:8080
```

In another terminal:

```bash
openshell gateway add http://127.0.0.1:8080 --local --name openshift
openshell status
```

## Verify a sandbox

```bash
openshell sandbox create --name smoke-test -- bash
openshell sandbox exec --name smoke-test -- uname -a
openshell sandbox delete smoke-test
```

The resulting sandbox pod must not have `spec.runtimeClassName` set.
