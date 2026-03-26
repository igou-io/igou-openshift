# multus-ovnk-static-ip

OVN-Kubernetes secondary network with a static IP assigned via pod annotation.

## What this demonstrates

- Assigning a static IP on a localnet secondary network using the pod annotation
- L2-only NAD (no `subnets`) — OVN does not manage IPAM
- IP address specified in the `k8s.v1.cni.cncf.io/networks` annotation as JSON

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-ovnk-static-ip` |
| `nad-vlan45.yaml` | NetworkAttachmentDefinition | Localnet NAD on VLAN 45, no subnets |
| `pod.yaml` | Pod | ose-tools-rhel9 pod with static IP `10.10.45.222/24` |

## Usage

```bash
oc apply -k .
oc rsh -n multus-ovnk-static-ip multus-ovnk-static-ip-test
ip a  # secondary interface should have 10.10.45.222/24
```

## Notes

- Static IP assignment requires the NAD to **not** have `subnets` defined
- The IP is set in the pod annotation, not in the NAD
- No privileged SCC is needed — OVN-K handles the IP assignment
- Compliant with `restricted-v2` SCC (seccompProfile, runAsNonRoot, drop ALL capabilities)
