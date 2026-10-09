# Cluster API — cluster-specific resources (ocp)

Provisions the `casval` bare-metal worker onto this cluster via upstream
Cluster API + Metal3. The reusable operator, providers, and cross-cluster
RBAC live in `components/cluster-api-operator/`. This directory holds only
the cluster-specific objects (Cluster/Metal3Cluster, MachineSet, BMH, and
the CronJob workarounds).

## Cluster-name config

`cluster-config-configmap.yaml` carries `clusterName`, which should equal
`infrastructure.status.infrastructureName`. On reprovision, update that
ConfigMap and commit — kustomize `replacements` propagate the value into
the Cluster, Metal3Cluster, and MachineSet fields that must match it.

```bash
oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'
```

Note: `MachineSet.spec.clusterName` is immutable, so changing the
ConfigMap value requires deleting the `casval-worker` MachineSet (do it
while casval is scaled to zero) and letting ArgoCD recreate it. The CAPI
stack is internally consistent as long as everything uses the ConfigMap
value — a drift from the live `infrastructureName` (e.g. after a cluster
reinstall) is cosmetic and does not block provisioning, but rename at the
next opportunity to keep names meaningful.

## Manual bootstrap (one-time per cluster — RERUN AFTER EVERY REINSTALL)

These steps are not yet automated in GitOps; they will eventually move to
the GitOps bootstrap Ansible. Perform them once after the
`cluster-api-operator` and `cluster-api` ArgoCD applications go healthy.

**A cluster reinstall silently loses all of them** (they live only in the
recreated namespaces). Symptoms of a missed re-run, seen 2026-07-05:

- BMH stuck in `provisioning` with `poweredOn: false`; baremetal-operator
  logs `could not retrieve user data: ... secrets "worker-user-data-managed"
  not found` → step 1 missing.
- capm3/capi logs loop on `error getting kubeconfig secret: Secret
  "<clusterName>-kubeconfig" not found`; Machine never gets a nodeRef →
  step 2 missing.
- After fixing, the baremetal-operator can sit in reconcile backoff for
  minutes; touch an annotation on the BMH to trigger an immediate retry
  (`oc annotate bmh casval -n openshift-cluster-api nudge=1 --overwrite`).

### 1. Copy `worker-user-data-managed` secret

CAPM3 consumes this for the Ignition bootstrap. Copy the managed Secret from
`openshift-machine-api` using the existing name, changing its MCS source to
`/config/casval` so the partition MachineConfig is consumed before first boot.
The source Secret stays unchanged; certificates and other bootstrap data are
preserved. Run this only when preparing an authorized fresh installation:

```bash
oc get secret worker-user-data-managed -n openshift-machine-api -o json \
  | jq '
      .metadata = {name: .metadata.name, namespace: "openshift-cluster-api"}
      | .data.userData |= (
          @base64d | fromjson
          | if ([.ignition.config.merge[]? | select(.source | endswith("/config/worker"))] | length) != 1
            then error("Expected one worker pool source") else . end
          | .ignition.config.merge[].source |= sub("/config/worker$"; "/config/casval")
          | tojson | @base64
        )
    ' \
  | oc apply -f -
```

### Casval installation disk

`../machineconfigs/98-casval-data-partition-machineconfig.yaml` reserves the first
300 GiB of Casval's Samsung 990 PRO for boot, RHCOS, and container images. Partition
5 (`casval-lvm`) starts at 307200 MiB and consumes the remaining approximately
1.53 TiB, unformatted and unmounted. The disk is selected by its stable by-id path.

`MachineConfigPool/casval` inherits worker configuration and adds this MC. The MC
registers `node.igou.systems/casval=true`, which the pool selects immediately.
Kubelet rejects custom `node-role.kubernetes.io/*` registration labels; CAPI
applies the existing worker and burst roles after registration.
The existing MachineSet and Metal3 template keep their names and Secret references.
The pool selector label is not propagated through the MachineSet: CAPI would also apply it
to existing Machines whose disks cannot be repartitioned in place.

Before reprovisioning, require the pool's served configuration to include the
partition MC. With zero updated nodes, the MCS uses `status.configuration`:

```bash
oc get mcp casval -o jsonpath='{.status.configuration.name}{"\n"}{.status.configuration.source[*].name}{"\n"}'
oc get mc 98-casval-data-partition
```

A fresh installation is required; this does not shrink the running node's root
partition. Do not label the existing node into the new pool. `install_coreos`
does not preserve this data partition across reinstalls, so treat local volumes
as disposable. After installation, verify pool membership and partition 5, then
add a Casval device class and burst toleration to the existing LVMCluster and
test PVC provisioning. See the storage and bare-metal burst worker runbooks in
`igou-docs` for the rollout checks.

### 2. Create the workload-cluster kubeconfig + mark control plane initialized

The CAPI cluster cache connects to the "workload cluster" (same cluster,
here) via the `<cluster-name>-kubeconfig` Secret. The Secret must carry the
`cluster.x-k8s.io/cluster-name` label so CAPI's filtered informer sees it.
Additionally, `ControlPlaneInitialized=True` must be patched onto the
Cluster status since there are no CAPI-managed control-plane Machines.

`CLUSTER_NAME` here MUST be the CAPI Cluster object's name — i.e. the
`clusterName` in `cluster-config-configmap.yaml` — NOT the live
`infrastructure.status.infrastructureName`. The two match only while the
ConfigMap is kept in sync; after a reinstall they drift, and deriving the
secret name from the infra name mints a secret CAPI never reads.

```bash
CLUSTER_NAME=$(oc get cm cluster-api-cluster-config -n openshift-cluster-api -o jsonpath='{.data.clusterName}')
API_SERVER=$(oc whoami --show-server)
CA_DATA=$(oc get configmap kube-root-ca.crt -n openshift-cluster-api -o jsonpath='{.data.ca\.crt}' | base64 -w0)
TOKEN=$(oc create token default -n openshift-cluster-api --duration=8760h)

KUBECONFIG_B64=$(base64 -w0 <<INNEREOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    certificate-authority-data: ${CA_DATA}
    server: ${API_SERVER}
  name: ${CLUSTER_NAME}
contexts:
- context:
    cluster: ${CLUSTER_NAME}
    user: ${CLUSTER_NAME}
  name: ${CLUSTER_NAME}
current-context: ${CLUSTER_NAME}
users:
- name: ${CLUSTER_NAME}
  user:
    token: ${TOKEN}
INNEREOF
)

oc apply -f - <<OUTEREOF
apiVersion: v1
kind: Secret
metadata:
  name: ${CLUSTER_NAME}-kubeconfig
  namespace: openshift-cluster-api
  labels:
    cluster.x-k8s.io/cluster-name: ${CLUSTER_NAME}
type: cluster.x-k8s.io/secret
data:
  value: ${KUBECONFIG_B64}
OUTEREOF

oc patch cluster ${CLUSTER_NAME} -n openshift-cluster-api \
  --type=merge --subresource=status \
  -p "{\"status\":{\"conditions\":[{\"type\":\"ControlPlaneInitialized\",\"status\":\"True\",\"reason\":\"ExternalControlPlane\",\"message\":\"Control plane managed by OpenShift, not CAPI\",\"lastTransitionTime\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"observedGeneration\":2}]}}"
```

### 3. Flip the BMH online

`casval-baremetalhost.yaml` ships with `online: false` to keep the host
powered down until you're ready. Set `online: true` and commit when ready,
or edit imperatively for first boot.

## Watch the rollout

```bash
oc get coreprovider,infrastructureprovider,ipamprovider -A
oc get bmh -n openshift-cluster-api -w
oc get cluster,metal3cluster,machineset.cluster.x-k8s.io,machine.cluster.x-k8s.io,metal3machine -n openshift-cluster-api
```
