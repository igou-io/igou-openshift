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
- Placement: components schedule freely. The phase-1 `truenas-w1` hostname
  pins were removed after worker lifecycle operations stranded RHACS Pending
  (#604).

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

Six `SecurityPolicy` CRs (`cluster-apps-*-securitypolicy.yaml`, reconciled by
config-controller) clone built-ins scoped to the **32 current cluster-apps
ArgoCD project namespaces**, including the four Hermes namespaces and both
`omnigent` and `omnigent-sandboxes`. The retired `hermes` namespace is removed.
The dangerous-workload set is Privileged Container, Sensitive Host Mounts,
Runtime Socket Mount, CAP_SYS_ADMIN, and Secret in Env Var (#547), plus Latest
tag (#559). AAP automation-job/activation-job workloads remain excluded from
Latest tag because their EE/DE images track `:latest` by design in igou-inventory.
Detection criteria are unchanged from the 4.11 built-ins. Latest tag checks
only `latest`; it does not require every image to use a digest.

The namespace lists are static, not an ArgoCD project selector. When adding,
moving, or retiring a cluster-apps namespace, update `spec.scope` in **all six**
policy manifests. Include secondary namespaces declared by an application,
such as `omnigent-sandboxes`, and use the namespace name rather than the ArgoCD
application name (`llmkube` deploys to `llmkube-system`).

**Enforcement is currently OFF**: the SecuredCluster CR has
`admissionControl.enforcement: Disabled`, which makes the clones' admission
rejection actions inert. They continue to report violations through the
configured Slack notifier. Expanding their scope can produce new alerts;
the July 2026 zero-violation baseline does not establish that the new namespaces
are clear. Before a separate enforcement rollout, collect a fresh baseline,
review intended workload exceptions, and audit enforcement actions on built-in
policies as well as these clones. The admission webhook remains fail-open.
These six policies evaluate deployment configuration and carry no runtime
kill or scale-to-zero actions. Hermes now runs in `hermes-assistant`,
`hermes-developer`, `hermes-operator`, and `hermes-sre`; the former Hermes VM
is retired.

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

The six cluster-apps SecurityPolicy CRs reference the notifier
`slack-igoucloud-alerts` by name — violations of those policies (and only
those) post to the **#igoucloud-alerts-warning** Slack channel (the same
channel Alertmanager's warning receiver uses). The original July baseline had
zero in-scope violations; re-baseline after namespace changes before
interpreting silence as a clean result.

The notifier itself is **API-managed** (declarative config supports only
generic/splunk types): type `slack`, name `slack-igoucloud-alerts`, webhook
from the 1P `lab_openshift` item `slack-webhook-igoucloud-alerts-warning`.
Recreate: `POST /v1/notifiers` with
`{"name":"slack-igoucloud-alerts","type":"slack","uiEndpoint":"<central route>","labelDefault":"<webhook url>"}`;
verify with `POST /v1/notifiers/test` (flat notifier object as body).
Built-in policies deliberately have NO notifier — the ~400 violation
events/day of platform churn would flood the channel.
