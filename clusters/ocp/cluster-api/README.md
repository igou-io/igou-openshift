# Cluster API — cluster-specific resources (ocp)

Provisions the `casval` bare-metal worker onto this cluster via upstream
Cluster API + Metal3. The reusable operator, providers, and cross-cluster
RBAC live in `components/cluster-api-operator/`. This directory holds only
the cluster-specific objects (Cluster/Metal3Cluster, MachineSet, BMH, and
the CronJob workarounds).

## Cluster-name config

`cluster-config-configmap.yaml` carries `clusterName`, which must equal
`infrastructure.status.infrastructureName`. On reprovision, update that
ConfigMap and commit — kustomize `replacements` propagate the value into
the Cluster, Metal3Cluster, and MachineSet fields that must match it.

```bash
oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}'
```

## Manual bootstrap (one-time per cluster)

These steps are not yet automated in GitOps; they will eventually move to
the GitOps bootstrap Ansible. Perform them once after the
`cluster-api-operator` and `cluster-api` ArgoCD applications go healthy.

### 1. Copy `worker-user-data-managed` secret

CAPM3 consumes this for the Ignition bootstrap. One-time copy from
`openshift-machine-api`:

```bash
oc get secret worker-user-data-managed -n openshift-machine-api -o yaml \
  | sed 's/namespace: openshift-machine-api/namespace: openshift-cluster-api/' \
  | oc apply -f -
```

### 2. Create the workload-cluster kubeconfig + mark control plane initialized

The CAPI cluster cache connects to the "workload cluster" (same cluster,
here) via the `<cluster-name>-kubeconfig` Secret. The Secret must carry the
`cluster.x-k8s.io/cluster-name` label so CAPI's filtered informer sees it.
Additionally, `ControlPlaneInitialized=True` must be patched onto the
Cluster status since there are no CAPI-managed control-plane Machines.

```bash
CLUSTER_NAME=$(oc get infrastructure cluster -o jsonpath='{.status.infrastructureName}')
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
