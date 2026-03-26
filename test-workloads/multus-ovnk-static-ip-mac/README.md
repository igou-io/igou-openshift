# multus-ovnk-static-ip-mac

OVN-Kubernetes secondary network with a static IP, explicit MAC address, and custom interface name.

## What this demonstrates

- Assigning a static IP, MAC address, and custom interface name via the pod annotation
- L2-only NAD (no `subnets`) — OVN does not manage IPAM
- Full control over the secondary interface identity (IP, MAC, interface name)

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-ovnk-static-ip-mac` |
| `nad-vlan45.yaml` | NetworkAttachmentDefinition | Localnet NAD on VLAN 45, no subnets |
| `pod.yaml` | Pod | ose-tools-rhel9 pod with static IP, MAC, and custom interface |

## Pod annotation details

```json
{
  "name": "vlan45-trunk",
  "ips": ["10.10.45.223/24"],
  "mac": "02:00:0a:0a:2d:df",
  "interface": "vlan45"
}
```

- **`ips`** — Static IP on the VLAN 45 network
- **`mac`** — Locally-administered MAC address (02:xx prefix)
- **`interface`** — Custom interface name inside the pod (instead of default `net1`)

## Usage

```bash
oc apply -k .
oc rsh -n multus-ovnk-static-ip-mac multus-ovnk-static-ip-mac-test
ip a  # "vlan45" interface with 10.10.45.223/24 and MAC 02:00:0a:0a:2d:df
```

## Notes

- Useful for scenarios requiring deterministic MAC addresses (DHCP reservations, ARP-sensitive services)
- Custom interface names make it easier to identify secondary interfaces in pods with multiple attachments
- Static IP requires the NAD to **not** have `subnets` defined
