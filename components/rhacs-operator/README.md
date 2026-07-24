# rhacs-operator

Red Hat Advanced Cluster Security (RHACS/StackRox) — **phase 1: minimal
observe-only install** ([#381](https://github.com/igou-io/igou-openshift/issues/381)).
Measures steady-state footprint for ~1 week to drive the placement/sizing/
keep-vs-kill decisions before any enforcement or policy work.

## Shape

- Operator: `stable` channel, Automatic approval, AllNamespaces OperatorGroup
  (the CSV supports no other install mode).
- `Central` + `SecuredCluster` trimmed to ~2.2 cpu / ~7Gi requests cluster-wide
  (plus ~150m/420Mi per node for Collector+compliance). Scanner V4 and
  local/delegated scanning disabled on both CRs; admission controller deployed
  with `enforcement: Disabled` (observe-only, fail-open).
- Placement: Central + Central DB are pinned to `truenas-w1` (the only
  non-tenant, non-master worker) so the single stateful piece stays off the
  tenant nodes and the master. Everything else schedules freely — that
  placement is part of the phase-1 measurement.

## Bootstrap: cluster-init bundle (one-time, non-GitOps)

Sensor/Collector/AdmissionControl authenticate to Central with an init bundle
minted *by* Central — chicken-and-egg with pure GitOps. The SecuredCluster
services sit degraded and the three ExternalSecrets sit in SecretSyncedError
until this is done once:

1. Wait for Central to be Ready (`oc get central -n stackrox`).
2. Get the admin password:
   `oc get secret central-htpasswd -n stackrox -o go-template='{{index .data "password" | base64decode}}'`
3. Mint the bundle:
   `roxctl -e central-stackrox.apps.ocp.igou.systems:443 central init-bundles generate ocp --output-secrets cluster_init_bundle.yaml`
4. Create three items in the 1Password vault `lab_openshift` (Connect mode —
   no `op item create`; use the Connect REST API), one per Secret in the
   bundle YAML, with field labels exactly matching the Secret's stringData
   keys:
   - `stackrox-sensor-tls`: `ca.pem`, `sensor-cert.pem`, `sensor-key.pem`
   - `stackrox-collector-tls`: `ca.pem`, `collector-cert.pem`, `collector-key.pem`
   - `stackrox-admission-control-tls`: `ca.pem`, `admission-control-cert.pem`, `admission-control-key.pem`
5. Delete the local bundle file. It must never land in git.
6. Annotate/wait for the ExternalSecrets to refresh; the secured-cluster pods
   pick the secrets up and the cluster shows Healthy in Central.

Fallback (acceptable for phase 1): `oc apply -f cluster_init_bundle.yaml`
and convert to ESO later — the ExternalSecrets will adopt on next refresh
only if the 1P items exist, so prefer the 1P route.

## Measurement (phase-1 exit criteria live in #381)

- `sum by (pod) (container_memory_working_set_bytes{namespace="stackrox", container!=""})`
- `sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="stackrox", container!=""}[5m]))`
- Watch restarts/OOMKills, central-db PVC growth, per-node Collector overhead
  (master + casval during burst).

## Auth (#546)

Login is OpenShift OAuth via the declarative-config ConfigMap
(`central-declarative-config`, mounted through
`central.declarativeConfiguration.configMaps`): auth provider `OpenShift`,
OpenShift group `global-admins` → RHACS `Admin`, everyone else `None`.
Declaratively-managed objects are read-only in the Central UI; change them
here in git. htpasswd basic auth (`admin` + the `central-htpasswd` secret,
step 2 above) stays as break-glass.
