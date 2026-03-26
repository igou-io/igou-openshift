# multus-ovnk-multinetpolicy

OVN-Kubernetes secondary network with MultiNetworkPolicy examples for secondary network firewalling.

## What this demonstrates

- Applying network policies to secondary (non-default) pod networks using `MultiNetworkPolicy`
- Two policy types: `ipBlock`-based and `podSelector`-based ingress rules
- OVN IPAM with `subnets` (required for `podSelector`-based policies)

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-ovnk-multinetpolicy` |
| `nad-vlan45.yaml` | NetworkAttachmentDefinition | Localnet NAD on VLAN 45 with OVN IPAM |
| `pod.yaml` | Pod | ose-tools-rhel9 pod with label `name: multinetpolicy-test` |
| `multinetworkpolicy-ipblock.yaml` | MultiNetworkPolicy | Restricts ingress to `10.10.45.0/24` CIDR |
| `multinetworkpolicy-podselector.yaml` | MultiNetworkPolicy | Allows ingress only from pods in the same namespace |

## Policy details

### ipBlock policy
- Works with or without `subnets` on the NAD
- Restricts secondary network ingress to the `10.10.45.0/24` subnet
- Blocks traffic from any other network

### podSelector policy
- **Requires** `subnets` on the NAD (OVN needs to manage IPs to enforce pod-level rules)
- Allows ingress only from pods within the `multus-ovnk-multinetpolicy` namespace
- Empty `podSelector: {}` matches all pods in the namespace

## Usage

```bash
oc apply -k .
oc rsh -n multus-ovnk-multinetpolicy multus-ovnk-multinetpolicy-test
ip a  # secondary interface should have an IP in 10.10.45.201-254
```

## Notes

- The `k8s.v1.cni.cncf.io/policy-for` annotation on the MultiNetworkPolicy points to the NAD
- MultiNetworkPolicy is part of the `k8s.cni.cncf.io/v1beta1` API group
- Both policies can coexist — they are additive (most restrictive wins)
- The pod label `name: multinetpolicy-test` is used as the selector target in the ipBlock policy
