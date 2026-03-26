# multus-pod-nad

Basic Multus secondary network attachment using OVN-Kubernetes localnet topology.

## What this demonstrates

- Attaching a pod to VLAN 45 via a `NetworkAttachmentDefinition` (NAD)
- L2-only connectivity (no IPAM — the pod gets a secondary interface but no IP address on it)
- Uses the `trunk-network` OVS bridge mapping defined by the cluster NNCP

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-pod-nad` |
| `nad-vlan45.yaml` | NetworkAttachmentDefinition | Localnet NAD on VLAN 45, no subnets |
| `pod.yaml` | Pod | ose-tools-rhel9 pod attached to the NAD |

## Usage

```bash
oc apply -k .
oc rsh -n multus-pod-nad multus-pod-nad-test
ip a  # secondary interface is present but has no IP
```

## Notes

- The pod will have two interfaces: `eth0` (cluster network) and a secondary interface (VLAN 45)
- Without subnets or a static IP annotation, the secondary interface has no IP address
- This workload does not set pod security context — it relies on the namespace's default SCC
