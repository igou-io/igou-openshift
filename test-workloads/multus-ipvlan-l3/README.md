# multus-ipvlan-l3

IPVLAN L3 mode secondary network on VLAN 45.

## What this demonstrates

- IPVLAN CNI plugin in L3 mode — operates at the network layer (L3 routing only)
- No ARP, broadcast, or multicast on the secondary interface — all traffic is routed
- Static IPAM with a /32 address (point-to-point, since L3 mode doesn't use L2 adjacency)
- The host acts as a router for the pod's traffic on this interface

## When to use IPVLAN L3

- You want network isolation without L2 adjacency (no broadcast domain exposure)
- The workload only needs routed IP connectivity, not Ethernet-level access
- You need stricter network segmentation — pods cannot ARP for or discover other hosts on the VLAN

## How L3 mode differs from L2

| | L2 mode | L3 mode |
|---|---------|---------|
| ARP/broadcast | Yes | No |
| Multicast | Yes | No |
| Same-subnet L2 adjacency | Yes | No |
| Routing | Via gateway | Host acts as router |
| Typical IPAM | Subnet range | /32 static |

## Prerequisites

- VLAN subinterface `enp2s0f1.45` must exist on the node (created via NMState NNCP)
- The master interface must **not** also have a macvlan NAD — a single interface cannot use both macvlan and ipvlan simultaneously
- External routing infrastructure must know how to reach the pod's /32 address via the node (static routes or a routing protocol)

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-ipvlan-l3` |
| `nad.yaml` | NetworkAttachmentDefinition | IPVLAN L3 on `enp2s0f1.45`, static IP `10.10.45.245/32` |
| `pod.yaml` | Pod | ose-tools-rhel9 pod attached to the IPVLAN L3 NAD |

## Usage

```bash
oc apply -k .
oc rsh -n multus-ipvlan-l3 multus-ipvlan-l3-test
ip a          # net1 should have 10.10.45.245/32
ip link show  # net1 MAC will match the master interface's MAC
ip r          # no default route on net1 (L3 mode, routed by host)
```

## Notes

- IPVLAN does not allow the pod to communicate with the host via the master interface — traffic between pod and host must go through the cluster network (eth0)
- L3 mode is the most isolated option — no broadcast storms, no ARP spoofing surface
- Pods on the same node using the same L3 IPVLAN can communicate via the host's routing table
- Without external route advertisements, this pod is only reachable from the node itself or via explicitly configured static routes
- Compliant with `restricted-v2` SCC (seccompProfile, runAsNonRoot, drop ALL capabilities)
