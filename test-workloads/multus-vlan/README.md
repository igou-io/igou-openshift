# multus-vlan

VLAN CNI plugin secondary network on VLAN 80.

## What this demonstrates

- The VLAN CNI plugin, which creates a VLAN subinterface on the host's master interface
- VLAN tagging handled by the CNI plugin (no need to pre-create the VLAN subinterface via NMState)
- `host-local` IPAM for node-scoped IP allocation
- Default route set to the VLAN 80 gateway via both NAD routes and pod `default-route` annotation

## Prerequisites

- The master interface `enp2s0f1` must be available on the node
- VLAN 80 must be trunked to the node's switch port

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-vlan` |
| `nad.yaml` | NetworkAttachmentDefinition | VLAN 80 on `enp2s0f1` with host-local IPAM on `10.10.80.0/24` |
| `pod.yaml` | Pod | ose-tools-rhel9 pod with VLAN 80 as default route |

## Usage

```bash
oc apply -k .
oc rsh -n multus-vlan multus-vlan-test
ip a   # net1 interface should have an IP from 10.10.80.0/24
ip -d link show net1   # should show vlan protocol 802.1Q id 80
ip r                   # default route should point to 10.10.80.1 via net1
```
## Expectation:

```bash
sh-5.1$ ip -d link show
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN mode DEFAULT group default qlen 1000
    link/loopback 00:00:00:00:00:00 brd 00:00:00:00:00:00 promiscuity 0 allmulti 0 minmtu 0 maxmtu 0 numtxqueues 1 numrxqueues 1 gso_max_size 65536 gso_max_segs 65535 tso_max_size 524280 tso_max_segs 65535 gro_max_size 65536 gso_ipv4_max_size 65536 gro_ipv4_max_size 65536
2: eth0@if12848: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1400 qdisc noqueue state UP mode DEFAULT group default
    link/ether 0a:58:0a:80:01:39 brd ff:ff:ff:ff:ff:ff link-netnsid 0 promiscuity 0 allmulti 0 minmtu 68 maxmtu 65535
    veth numtxqueues 20 numrxqueues 20 gso_max_size 65536 gso_max_segs 65535 tso_max_size 524280 tso_max_segs 65535 gro_max_size 65536 gso_ipv4_max_size 65536 gro_ipv4_max_size 65536
3: net1@if5: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue state UP mode DEFAULT group default qlen 1000
    link/ether 58:47:ca:77:09:8b brd ff:ff:ff:ff:ff:ff link-netnsid 0 promiscuity 0 allmulti 0 minmtu 0 maxmtu 65535
    vlan protocol 802.1Q id 80 <REORDER_HDR> numtxqueues 1 numrxqueues 1 gso_max_size 65536 gso_max_segs 65535 tso_max_size 65536 tso_max_segs 65535 gro_max_size 65536 gso_ipv4_max_size 65536 gro_ipv4_max_size 65536
```

## Limitations

- **One pod per node**: The VLAN CNI plugin cannot create multiple subinterfaces with the same `vlanId` on the same `master` interface. Only a single pod per node can use this NAD.
- If the master interface is OVS-managed (e.g. part of `br-secondary`), the VLAN plugin may fail with "device or resource busy". In that case, use macvlan on a pre-created VLAN subinterface instead (see [multus-macvlan-static-ip-nginx](../multus-macvlan-static-ip-nginx/)).

## Notes

- Unlike macvlan with a VLAN subinterface, the VLAN CNI plugin creates and destroys the subinterface with the pod lifecycle
- The default route is set via two mechanisms: `routes` in the NAD IPAM config, and `default-route` in the pod annotation — both point to `10.10.80.1`
- Compliant with `restricted-v2` SCC (seccompProfile, runAsNonRoot, drop ALL capabilities)
