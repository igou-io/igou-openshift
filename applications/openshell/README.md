# OpenShell

OpenShell 0.1.1 runs as a single SQLite-backed gateway in `openshell`, using
this cluster's Red Hat Agent Sandbox operator (`agents.x-k8s.io/v1beta1`).

## Security and deployment

- Keycloak's `igou` realm authenticates users; `openshell-admin` and
  `openshell-user` roles authorize access. Anonymous access is disabled.
- A cert-manager certificate from `cluster-acme` and an OpenShift passthrough
  Route serve `https://openshell.apps.ocp.igou.systems` with end-to-end TLS.
- Sandboxes and separate supervisors use non-root namespace identities with
  no added capabilities. No privileged SCC grant is configured.
- The ordinary CRI-O runtime must support nested seccomp user notification
  and Landlock. OVN-Kubernetes must enforce ingress and egress NetworkPolicies.
  Fix failed runtime probes at the runtime; do not bypass them with privileged SCC.
- The default workload is minimal NVIDIA Ubuntu 24.04. Select an explicit,
  prebuilt agent image with `--from` when agent tools are needed.
- Gateway, supervisor, sandbox runtime and default workload images are pinned
  by digest. Upgrade CLI/SDK clients together with the runtime.
- Telemetry is disabled. The gateway is not highly available; all workspaces
  currently share one namespace.

The gateway PVC and workspace defaults use 10 Gi `freenas-nvmeof-ssd-csi`
block storage. Provider credentials use encrypted SQLite storage; External
Secrets supplies the encryption key from `lab_agents/openshell`, field
`key-encryption-key`, through `onepassword-lab-agents`.

Kustomize renders offline, so only the chart's live Agent Sandbox API preflight
is disabled. The parent application creates the namespace before chart PreSync
certificate/JWT hooks. Post-render patches clear fixed gateway UID/GID values
(Kustomize drops null Helm overrides) and preserve the gateway PVC size/class.
The published 0.1.1 chart still uses `server` values to generate schema-v2 TOML;
it does not implement the upgrade guide's `gatewayConfig` mapping.

## Connect and verify

Use the matching 0.1.1 CLI:

```bash
openshell gateway add https://openshell.apps.ocp.igou.systems \
  --name ocp \
  --oidc-issuer https://keycloak.apps.ocp.igou.systems/realms/igou \
  --oidc-client-id openshell-cli \
  --oidc-audience openshell-cli
openshell gateway login ocp
openshell --gateway ocp status
openshell --gateway ocp whoami
openshell --gateway ocp sandbox create --name smoke-test --detach -- sleep infinity
openshell --gateway ocp sandbox exec --name smoke-test -- uname -a
openshell --gateway ocp sandbox delete smoke-test
```

Check sandbox and supervisor `openshift.io/scc` annotations, non-root security
contexts, and effective ingress/egress isolation. Readiness alone does not prove
policy enforcement. No RuntimeClass is selected. Import provider profiles with
`openshell profile import --file <file>` and explicitly attach providers with
`--provider <name>`; the gateway no longer bundles provider profiles.
The optional OpenCode Go profile is in `provider-profiles/opencode-go-codex.yaml`.
Keep credential values in the provider store, never in manifests or commands.

## Upgrade and recovery

Follow the [upstream migration guide](https://docs.nvidia.com/openshell/upgrade/0-1-0)
and the templates from the exact chart release. For 0.0.x upgrades:

1. Export provider profiles using the old CLI, preserving workspace/global scope.
2. Preserve workspace data and remove all legacy sandboxes.
3. Stop the gateway with ArgoCD reconciliation controlled, and snapshot its PVC.
   Preserve the credential-encryption key through the existing secret store.
   The chart changes StatefulSet `serviceName` to `openshell-peer`; replace
   the controller while retaining its PVC before syncing the new chart.
4. Upgrade the chart and all runtime/client versions together; import profiles
   and recreate sandboxes. Legacy persisted runtime descriptors are incompatible.
5. Verify TLS/OIDC, restricted SCC admission, execution, storage and network isolation.

ArgoCD does not auto-prune this application. Explicitly remove the obsolete
`openshell-sandbox-privileged` ClusterRoleBinding and old `openshell-node-reader`
ClusterRole/ClusterRoleBinding when upgrading an existing installation.
Rollback requires the old database snapshot and matching runtime/client versions;
an image downgrade alone is not a supported database rollback.

The September 26 migration encountered incompatible stored provider protobufs
(`NetworkEndpoint.enforcement` wire-type mismatch). The unused evaluation
database was archived under `/var/openshell/pre-0.1.1` while the gateway was
stopped, then a fresh database initialized. The `openshell-before-0-1-1`
VolumeSnapshot also retains the old state. All 16 exported provider profiles
were imported after removing obsolete `tls: terminate` fields; old provider
credentials and workspace records remain archived, not active.

Verified on CRI-O with the 0.1.1 CLI: OIDC authentication; sandbox create,
exec, stop/start with persistent files, and deletion; workload and supervisor
admission under `restricted-v2`; zero effective capabilities, seccomp filters,
denied writes to `/var/tmp`, denied direct egress even via `oc exec`, and
blocked boundary-port ingress from an unrelated pod. The gateway is
`Synced/Healthy`. No inference-provider credential was provisioned by this upgrade.

External integrations must adopt the 0.1.x SDK/API contract before reconnecting.
The platform does not retain legacy images, privileges or policy exceptions for
old clients. Gateway resources and workload resource limits are separate settings.
