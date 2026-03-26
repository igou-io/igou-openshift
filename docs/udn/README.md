# OVN-Kubernetes User Defined Networks (UDN)

User Defined Networks provide OVN-Kubernetes-native network segmentation and secondary network connectivity. UDN is a higher-level abstraction over NetworkAttachmentDefinitions — OVN-K automatically creates and manages NADs internally.

## UDN Types

| Type | Scope | Localnet Support | Primary Role |
|------|-------|:----------------:|:------------:|
| `UserDefinedNetwork` | Namespace | No | Yes |
| `ClusterUserDefinedNetwork` | Cluster | Yes | Yes |

## Topologies

| Topology | Description | Use Case |
|----------|-------------|----------|
| **Layer3** | Per-node subnets with L3 routing | General purpose, recommended default |
| **Layer2** | Single broadcast domain across nodes | Flat L2 connectivity, VM live migration |
| **Localnet** | Connects overlay to physical underlay | External network access without SNAT |

## Key Concepts

- **Primary role**: Replaces the default cluster network for pods in the namespace. Namespace must have label `k8s.ovn.org/primary-user-defined-network: ""` set at creation time.
- **Secondary role**: Adds an additional network interface alongside the default cluster network.
- **Persistent IPAM**: IPs are persisted via `ipamclaims.k8s.cni.cncf.io` objects and survive pod restarts.
- **physicalNetworkName**: Must match the `localnet` name in the OVS bridge-mappings (configured via NMState NNCP).
- **Immutability**: UDN and CUDN CRs cannot be modified after creation — delete and recreate to change.

## Examples

| Example | Description |
|---------|-------------|
| [cudn-localnet-ipam](cudn-localnet-ipam/) | CUDN with localnet topology and OVN IPAM |
| [cudn-localnet-no-ipam](cudn-localnet-no-ipam/) | CUDN with localnet topology, IPAM disabled |
| [udn-layer2-primary](udn-layer2-primary/) | Namespace-scoped Layer2 primary UDN |
| [udn-layer3-primary](udn-layer3-primary/) | Namespace-scoped Layer3 primary UDN |

## Prerequisites

- OVN-Kubernetes CNI (default on OpenShift 4.x)
- For localnet: OVS bridge-mappings configured via NMState NNCP
- For primary UDN: namespace label set at creation time

## References

- [OKD 4.21 — About User Defined Networks](https://docs.okd.io/4.21/networking/multiple_networks/secondary_networks/about-user-defined-network.html)
- [OKD 4.21 — Creating UDN on OVN-K](https://docs.okd.io/4.21/networking/multiple_networks/secondary_networks/creating-user-defined-network-ovnk.html)
