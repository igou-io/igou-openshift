# multus-dummy-device

Dummy device secondary network attached to a pod.

## What this demonstrates

- The dummy CNI plugin, which functions like a loopback device but can route packets to arbitrary IP addresses (not limited to `127.0.0.0/8`)
- `host-local` IPAM for node-scoped IP allocation
- No physical interface or VLAN required — the dummy device is entirely virtual

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-dummy-device` |
| `nad.yaml` | NetworkAttachmentDefinition | Dummy device with host-local IPAM on `10.1.1.0/24` |
| `pod.yaml` | Pod | ose-tools-rhel9 pod attached to the dummy NAD |

## Usage

```bash
oc apply -k .
oc rsh -n multus-dummy-device multus-dummy-device-test
ip a   # net1 interface should have an IP from 10.1.1.0/24
ip r   # route for 10.1.1.0/24 on the dummy interface
```

## Notes

- The dummy interface appears as `net1` in the pod
- Unlike macvlan or OVN-K secondary networks, the dummy device has no connection to any physical or bridge interface
- Useful for testing, internal pod-to-pod routing via policy routes, or as a target for custom routing rules
- Compliant with `restricted-v2` SCC (seccompProfile, runAsNonRoot, drop ALL capabilities)
