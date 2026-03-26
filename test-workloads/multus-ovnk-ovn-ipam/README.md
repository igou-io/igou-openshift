# multus-ovnk-ovn-ipam

OVN-Kubernetes secondary network with OVN-managed IPAM on VLAN 45.

## What this demonstrates

- OVN IPAM via the `subnets` field in the NAD configuration
- Using `physicalNetworkName` to decouple the logical network name from the bridge mapping
- Using `excludeSubnets` to reserve IP ranges from OVN allocation
- Pod receives an IP automatically from OVN without any pod annotation

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-ovnk-ovn-ipam` |
| `nad-vlan45.yaml` | NetworkAttachmentDefinition | Localnet NAD on VLAN 45 with OVN IPAM |
| `pod.yaml` | Pod | ose-tools-rhel9 pod attached to the NAD |

## NAD configuration details

- **`name: vlan45-ipam`** — Unique logical network name (separate OVN logical switch from other NADs)
- **`physicalNetworkName: trunk-network`** — Maps to the `trunk-network` OVS bridge mapping
- **`subnets: 10.10.45.0/24`** — OVN allocates IPs from this range
- **`excludeSubnets`** — Reserves `.0-.200` to avoid conflicts with existing devices on the network

## Usage

```bash
oc apply -k .
oc rsh -n multus-ovnk-ovn-ipam multus-ovnk-ovn-ipam-test
ip a  # secondary interface should have an IP in 10.10.45.201-254
```

## Notes

- Each unique `name` in the NAD config creates a separate OVN logical switch
- All NADs sharing the same `name` must have identical network parameters (subnets, mtu, vlanID)
- `physicalNetworkName` is required when the logical network name differs from the bridge mapping name
