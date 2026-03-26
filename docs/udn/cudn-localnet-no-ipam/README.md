# ClusterUserDefinedNetwork — Localnet with IPAM Disabled

Connects pods to a physical VLAN without OVN-managed IP assignment. OVN only assigns a MAC address — IP configuration is handled externally.

## When to use

- Pods or VMs handle their own IP assignment (DHCP, cloud-init, static configuration)
- You don't want OVN to manage IPs on this network
- The physical network has its own DHCP server

## How it works

1. The CUDN creates an OVN logical switch connected to the physical network
2. Pods get a secondary interface with a MAC address but no IP
3. The pod or VM must configure its own IP (via DHCP client, cloud-init, or manual assignment)

## Configuration

| Field | Value | Purpose |
|-------|-------|---------|
| `physicalNetworkName` | `trunk-network` | Must match the `localnet` name in OVS bridge-mappings |
| `vlan.access.id` | `45` | VLAN tag applied to traffic |
| `ipam.mode` | `Disabled` | OVN does not assign IPs |

## Pod annotation

```yaml
annotations:
  k8s.v1.cni.cncf.io/networks: vlan45-no-ipam
```

## Notes

- Without IPAM, you cannot use `podSelector`-based `MultiNetworkPolicy` — only `ipBlock` rules work
- Static IPs can still be set via the JSON annotation format with the `ips` field
- Useful for OpenShift Virtualization VMs that use cloud-init for network configuration
