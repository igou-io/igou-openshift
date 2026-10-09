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

The workload-cluster kubeconfig and initialized status are not yet automated
in GitOps; they will eventually move to the GitOps bootstrap Ansible. Perform
the remaining manual steps once after the
`cluster-api-operator` and `cluster-api` ArgoCD applications go healthy.

**A cluster reinstall silently loses the manual bootstrap state** (it lives
only in the recreated namespaces). The Casval bootstrap Secret is generated
declaratively. Symptoms to check after reinstall:

- BMH stuck in `provisioning` with `poweredOn: false`; baremetal-operator
  cannot find `casval-worker-user-data` → check the bootstrap ExternalSecret
  and SecretStore in step 1.
- capm3/capi logs loop on `error getting kubeconfig secret: Secret
  "<clusterName>-kubeconfig" not found`; Machine never gets a nodeRef →
  step 2 missing.
- After fixing, the baremetal-operator can sit in reconcile backoff for
  minutes; touch an annotation on the BMH to trigger an immediate retry
  (`oc annotate bmh casval -n openshift-cluster-api nudge=1 --overwrite`).

### 1. Verify the generated Casval bootstrap

External Secrets reads only `worker-user-data-managed` in
`openshift-machine-api`, through the `casval-bootstrap-reader` service account,
and generates `casval-worker-user-data` in `openshift-cluster-api`. It preserves
the managed worker Ignition bootstrap and adds Casval's installation partition.
No bootstrap credentials or certificates are committed to git. The reader
uses the cluster's default `system:basic-user` permission for self-access reviews.

```bash
oc get secretstore casval-bootstrap -n openshift-cluster-api
oc get externalsecret casval-worker-user-data -n openshift-cluster-api
oc get secret casval-worker-user-data -n openshift-cluster-api
```

Both CAPI's `bootstrap.dataSecretName` and the Metal3 template's `userData`
reference this generated Secret. The old copied Secret is no longer needed
for new Machines. Existing Machines keep their original bootstrap reference.

### Casval installation disk

On the next fresh RHCOS installation, Ignition creates partition 5 on
`/dev/disk/by-id/nvme-Samsung_SSD_990_PRO_2TB_S7KHNU0Y110642R`, labeled
`casval-lvm`, starting at 307200 MiB (300 GiB). Boot and root occupy the space
before that boundary. The partition extends to the end of the 2 TB disk,
leaving about 1.53 TiB for LVMS before its metadata/thin-pool overhead.
Ignition leaves it unformatted and unmounted; LVMS will own its volume group.

This is an installation-time change. Syncing these resources does not shrink
the root partition of the running node. A fresh install is required, with
workloads stopped and data backed up before an explicitly authorized release
and reprovision. No partition-preservation option has been added to
`install_coreos`; treat data on this disk as disposable across reprovisioning.

The new `casval-worker-lvm-template` avoids editing an immutable Metal3 template.
The MachineSet uses it for new Machines and continues to leave lease-owned
replicas alone. The old template may remain live because auto-prune is disabled;
do not remove it while existing Metal3Machines still reference it.

LVMS enablement is a separate step after verifying the new partition: add a
Casval-specific device class to the existing LVMCluster, select the partition's
stable by-id path with `-part5`, and add the burst toleration. See
`igou-docs/storage/Cluster Storage with democratic-csi and Volume Recovery.md`.

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
