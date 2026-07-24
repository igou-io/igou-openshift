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

## Policy-as-code (#547)

Five `SecurityPolicy` CRs (`cluster-apps-*-securitypolicy.yaml`, reconciled by
config-controller) clone the dangerous-workload built-ins — Privileged
Container, Sensitive Host Mounts, Runtime Socket Mount, CAP_SYS_ADMIN,
Secret in Env Var — scoped to the **cluster-apps ArgoCD project namespaces +
hermes**. Criteria copied verbatim from the 4.11 built-ins. The built-ins keep
observing cluster-wide; the clones carry admission enforcement actions
(`FAIL_DEPLOYMENT_CREATE/UPDATE`).

**Enforcement is currently OFF**: the SecuredCluster CR has
`admissionControl.enforcement: Disabled`, which makes those actions inert.
The flip, when decided, is that single field → `Enabled` (failurePolicy stays
Ignore/fail-open). Runtime policies (exec/attach) deliberately carry no
enforcement — killing virt-launcher kills the hermes VM.

### Built-in tuning (API-managed, not GitOps)

Built-in policies cannot be managed by CR. Namespace *exclusions* on noisy
built-ins are applied via the Central API and recorded here as the source of
truth:

| Built-in policy | Excluded namespaces | Why |
|---|---|---|
| Docker CIS 4.1 (container user) | ansible-automation-platform, nvidia-gpu-operator | vendor images, acceptable behavior |
| Red Hat Package Manager in Image | ansible-automation-platform, nvidia-gpu-operator | vendor images, acceptable behavior |

Recipe (add an exclusion): `GET /v1/policies?query=Policy:<name>` for the id,
`GET /v1/policies/{id}`, append to `.exclusions` an entry
`{"name": "<ns> (acceptable)", "deployment": {"scope": {"namespace": "<ns>"}}}`,
`PUT /v1/policies/{id}` with the full body.

## Violation notifications (#548)

The five cluster-apps SecurityPolicy CRs reference the notifier
`slack-igoucloud-alerts` by name — violations of those policies (and only
those) post to the **#igoucloud-alerts-warning** Slack channel (the same
channel Alertmanager's warning receiver uses). With zero in-scope violations
at baseline, this is silent until something dangerous ships.

The notifier itself is **API-managed** (declarative config supports only
generic/splunk types): type `slack`, name `slack-igoucloud-alerts`, webhook
from the 1P `lab_openshift` item `slack-webhook-igoucloud-alerts-warning`.
Recreate: `POST /v1/notifiers` with
`{"name":"slack-igoucloud-alerts","type":"slack","uiEndpoint":"<central route>","labelDefault":"<webhook url>"}`;
verify with `POST /v1/notifiers/test` (flat notifier object as body).
Built-in policies deliberately have NO notifier — the ~400 violation
events/day of platform churn would flood the channel.
