# UserDefinedNetwork — Layer3 Primary

Replaces the default cluster network with a Layer3 routed network. Each node gets its own subnet, and OVN routes between them — similar to how the default cluster network works.

## When to use

- Network isolation between tenants with standard L3 routing
- General purpose — **recommended topology when unsure which to choose**
- Large-scale deployments where a single broadcast domain would be too noisy

## How it works

1. The namespace must have `k8s.ovn.org/primary-user-defined-network: ""` label **at creation time**
2. OVN carves a `/hostSubnet` per node from the `cidr` range (e.g., `10.100.0.0/24` for node 1, `10.100.1.0/24` for node 2)
3. OVN logical routers interconnect the per-node subnets
4. Pods get `eth0` on the UDN network instead of the default cluster network

## Prerequisites

- The namespace label **must** be set when the namespace is created — it cannot be added later
- No existing pods can be in the namespace when the primary UDN is created

## Configuration

| Field | Value | Purpose |
|-------|-------|---------|
| `topology` | `Layer3` | Per-node subnets with L3 routing |
| `role` | `Primary` | Replaces default cluster network |
| `subnets.cidr` | `10.100.0.0/16` | Overall IP range |
| `subnets.hostSubnet` | `24` | Prefix length per node (supports up to 256 nodes) |

## Limitations

- Same as Layer2 primary: DNS resolves to default network IP, pod IPs not in `kubectl get pods`
- `hostSubnet` must be between 1 and 127 (prefix bits for per-node allocation)
- Maximum number of nodes is determined by `cidr` size minus `hostSubnet` size
