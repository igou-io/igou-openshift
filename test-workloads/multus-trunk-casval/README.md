# multus-trunk-casval

Validates the OVN `trunk-network` localnet bridge-mapping on casval
(see `clusters/ocp/nmstate/mapping-casval-nodenetworkconfigurationpolicy.yaml`).

Casval must be scaled up before applying — see
`clusters/ocp/cluster-api/casval-worker-machineset.yaml`.

```bash
# Scale casval up (if at 0)
oc -n openshift-cluster-api scale machineset/casval-worker --replicas=1

# Wait for the node and for the NNCE to converge
oc wait --for=condition=Ready node/casval --timeout=20m
oc get nnce | grep casval

# Apply the test workload
oc apply -k test-workloads/multus-trunk-casval/

# Verify the secondary interface
oc -n multus-trunk-casval exec trunk-test -- ip -br addr show vlan45
# Expected: vlan45 ... 10.10.45.226/24

# Verify VLAN 45 reachability from casval
oc -n multus-trunk-casval exec trunk-test -- ping -c2 10.10.45.1
```
