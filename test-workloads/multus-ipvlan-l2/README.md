# multus-ipvlan-l2

IPVLAN L2 mode secondary network on VLAN 45.

## What this demonstrates

- IPVLAN CNI plugin in L2 mode — operates at the data link layer, similar to macvlan
- All pods share the host's MAC address on the master interface (unlike macvlan which assigns unique MACs)
- `host-local` IPAM with a constrained range to avoid conflicts with other VLAN 45 consumers
- Default gateway route for cross-subnet reachability

## When to use IPVLAN L2 instead of macvlan

- The upstream switch enforces MAC address limits or port security policies
- You want pods to be indistinguishable from the host at L2 (single MAC per physical port)
- The workload needs same-subnet L2 adjacency with other hosts on the VLAN

## Prerequisites

- VLAN subinterface `enp2s0f1.45` must exist on the node (created via NMState NNCP)
- The master interface must **not** also have a macvlan NAD — a single interface cannot use both macvlan and ipvlan simultaneously

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-ipvlan-l2` |
| `nad.yaml` | NetworkAttachmentDefinition | IPVLAN L2 on `enp2s0f1.45`, host-local IPAM `10.10.45.230-239` |
| `pod.yaml` | Pod | ose-tools-rhel9 pod attached to the IPVLAN L2 NAD |

## Usage

```bash
oc apply -k .
oc rsh -n multus-ipvlan-l2 multus-ipvlan-l2-test
ip a          # net1 should have an IP from 10.10.45.230-239
ip link show  # net1 MAC will match the master interface's MAC
ip r          # default route via 10.10.45.1
```

## Notes

- IPVLAN does not allow the pod to communicate with the host via the master interface — traffic between pod and host must go through the cluster network (eth0)
- L2 mode supports broadcast and multicast, behaving like a standard Ethernet interface
- Compliant with `restricted-v2` SCC (seccompProfile, runAsNonRoot, drop ALL capabilities)
