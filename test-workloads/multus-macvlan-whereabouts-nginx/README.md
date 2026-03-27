# multus-macvlan-whereabouts-nginx

Macvlan secondary network with whereabouts IPAM and nginx deployment.

## What this demonstrates

- Macvlan CNI plugin with cluster-managed IP allocation via whereabouts
- No static IP in the pod annotation — whereabouts allocates from the configured range
- Default gateway route for cross-subnet reachability
- Whereabouts tracks allocations cluster-wide, preventing IP conflicts across nodes

## Prerequisites

- VLAN subinterface `enp2s0f1.45` must exist on the node (created via NMState NNCP)
- The `whereabouts` binary is included with OpenShift (installed by the Cluster Network Operator) — no additional setup required

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-macvlan-whereabouts-nginx` |
| `nad-vlan45.yaml` | NetworkAttachmentDefinition | Macvlan on `enp2s0f1.45` with whereabouts IPAM, range `10.10.45.224/28` |
| `deployment.yaml` | Deployment | nginx with whereabouts-assigned IP on secondary interface |
| `service.yaml` | Service | ClusterIP service on port 80 -> 8080 |
| `route.yaml` | Route | Edge-terminated TLS route |

## Usage

```bash
oc apply -k .
oc exec -n multus-macvlan-whereabouts-nginx deploy/nginx -- ip a  # net1 interface should have IP from 10.10.45.224/28
oc exec -n multus-macvlan-whereabouts-nginx deploy/nginx -- ip r  # should show default via 10.10.45.1
```

## Why whereabouts instead of DHCP

The CNI DHCP plugin requires a DHCP daemon running on the node (`/run/cni/dhcp.sock`). On OpenShift, this daemon is not started by default for macvlan NADs — it fails with `error dialing DHCP daemon: dial unix /run/cni/dhcp.sock: connect: no such file or directory`. Whereabouts is built into OpenShift and works without any additional infrastructure.

## Notes

- The pod annotation uses the short form (`vlan45-macvlan-whereabouts`) since whereabouts assigns the IP automatically
- `range` defines the allocation pool — whereabouts will assign IPs from `10.10.45.225` to `10.10.45.238` (usable range of a /28)
- Whereabouts stores allocations as custom resources (`ippools.whereabouts.cni.cncf.io`), ensuring cluster-wide uniqueness
- Use `exclude` in the IPAM config to reserve specific IPs within the range (e.g., `"exclude": ["10.10.45.225/32"]`)
- Compliant with `restricted-v2` SCC (seccompProfile, runAsNonRoot, drop ALL capabilities)
