# Hub cluster — User Defined Networks

## `vlan9-no-ipam` (ClusterUserDefinedNetwork)

Secondary **localnet** on VLAN **9**, using the same OVS bridge mapping as other trunk networks:

- **`physicalNetworkName`**: `trunk-network` — must match `ovn.bridge-mappings` (`localnet: trunk-network` → `br-secondary`) in [nmstate mapping](../nmstate/mapping-nodenetworkconfigurationpolicy.yaml).
- **Tagging**: `vlan.access.id: 9` applies 802.1Q VLAN 9 on that localnet path (OVN tags traffic to the underlay).
- **IPAM**: disabled — OVN assigns a MAC only; VMs/pods must get addresses via DHCP, cloud-init, or static config (see [docs/udn/cudn-localnet-no-ipam](../../docs/udn/cudn-localnet-no-ipam/)).

### Namespace access

Label any namespace that should receive the generated NAD:

```yaml
metadata:
  labels:
    network.igou.systems/vlan9: "true"
```

### Pods

```yaml
metadata:
  annotations:
    k8s.v1.cni.cncf.io/networks: vlan9-no-ipam
```

### OpenShift Virtualization (VMs)

Reference the **ClusterUserDefinedNetwork** name as the Multus network name in the VM spec (same as the generated NAD name in that namespace), for example:

```yaml
spec:
  template:
    spec:
      networks:
        - name: default
          pod: {}
        - name: vlan9
          multus:
            networkName: vlan9-no-ipam
      domain:
        devices:
          interfaces:
            - name: default
              masquerade: {}
            - name: vlan9
              bridge: {}
```

### Changing VLAN or IPAM

UDN/CUDN objects are **immutable**. To change VLAN, subnet, or IPAM mode, delete and recreate the `ClusterUserDefinedNetwork` (and plan workload impact).

### Optional: host VLAN interface

If you need a **host**-level `enp2s0f1.9` (for example, node routing on VLAN 9), extend the hub NNCP similarly to `enp2s0f1.45`. OVN localnet tagging for workloads does not require a Linux VLAN subinterface on the node if the switch trunks VLAN 9 to the same physical port as `br-secondary`.
