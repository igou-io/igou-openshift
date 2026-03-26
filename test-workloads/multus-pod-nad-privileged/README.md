# multus-pod-nad-privileged

Privileged Multus secondary network attachment for manual IP configuration and connectivity testing.

## What this demonstrates

- Attaching a privileged pod to VLAN 45 via a NAD
- Using the `privileged` SCC to allow manual IP assignment and network tooling inside the pod
- RBAC setup for SCC access (ServiceAccount, Role, RoleBinding)

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-pod-nad-privileged` |
| `nad-vlan45.yaml` | NetworkAttachmentDefinition | Localnet NAD on VLAN 45, no subnets |
| `serviceaccount.yaml` | ServiceAccount | `privileged-sa` |
| `scc-role.yaml` | Role | Grants `use` on the `privileged` SCC |
| `scc-rolebinding.yaml` | RoleBinding | Binds the role to `privileged-sa` |
| `pod.yaml` | Pod | Privileged ose-tools-rhel9 pod attached to the NAD |

## Usage

```bash
oc apply -k .
oc rsh -n multus-pod-nad-privileged multus-pod-nad-test-privileged
# Manually assign an IP on the secondary interface
ip addr add 10.10.45.250/24 dev net1
ping 10.10.45.1  # test gateway connectivity
```

## Notes

- The privileged SCC is required for `ip addr add` and other network configuration commands
- Useful for debugging L2 connectivity before testing OVN IPAM or static IP approaches
