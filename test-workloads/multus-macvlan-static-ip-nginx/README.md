# multus-macvlan-static-ip-nginx

Macvlan secondary network with a static IP, default gateway route, and nginx deployment.

## What this demonstrates

- Macvlan CNI plugin attached to a pre-created VLAN subinterface (`enp2s0f1.45`)
- Static IPAM with a default gateway route for cross-subnet reachability
- Custom MAC address and interface name via pod annotation
- Unlike OVN-K localnet, macvlan programs a real default route on the secondary interface, solving asymmetric routing for cross-subnet traffic

## Prerequisites

- VLAN subinterface `enp2s0f1.45` must exist on the node (created via NMState NNCP)
- The base interface (`enp2s0f1`) can be OVS-managed — macvlan attaches to the VLAN subinterface, not the base interface
- Do **not** use `"master": "enp2s0f1"` with `"vlan": 45` — this fails with "device or resource busy" when the base interface is managed by an OVS bridge

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-macvlan-static-ip-nginx` |
| `nad-vlan45.yaml` | NetworkAttachmentDefinition | Macvlan on `enp2s0f1.45` with static IPAM and default route |
| `deployment.yaml` | Deployment | nginx with static IP `10.10.45.225/24`, custom MAC, interface `vlan45` |
| `service.yaml` | Service | ClusterIP service on port 80 -> 8080 |
| `route.yaml` | Route | Edge-terminated TLS route |

## Usage

```bash
oc apply -k .
oc exec -n multus-macvlan-static-ip-nginx deploy/nginx -- ip a  # vlan45 interface should have 10.10.45.225/24
oc exec -n multus-macvlan-static-ip-nginx deploy/nginx -- ip r  # should show default via 10.10.45.1
curl 10.10.45.225:8080  # reachable from any subnet routable to VLAN 45
```

## Notes

- Static IP is set in the pod annotation, not in the NAD IPAM config
- The default route (`0.0.0.0/0 via 10.10.45.1`) in the NAD ensures replies to cross-subnet clients go back through the VLAN 45 gateway rather than the pod network default route (asymmetric routing fix)
- Compliant with `restricted-v2` SCC (seccompProfile, runAsNonRoot, drop ALL capabilities)
- Macvlan `bridge` mode allows pods on the same node to communicate via the macvlan interface, but pods cannot communicate with the host on the master interface
