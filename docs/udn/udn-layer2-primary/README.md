# UserDefinedNetwork — Layer2 Primary

Replaces the default cluster network with a flat Layer2 network. All pods in the namespace share a single broadcast domain across all nodes.

## When to use

- Network isolation between tenants (each namespace gets its own network)
- Applications requiring flat L2 connectivity across nodes
- Latency-sensitive applications using L2 protocols (ARP, mDNS)
- VM live migration with persistent IPs across nodes

## How it works

1. The namespace must have `k8s.ovn.org/primary-user-defined-network: ""` label **at creation time**
2. The UDN replaces the default cluster network as the pod's primary interface
3. Pods get `eth0` on the UDN network instead of the default cluster network
4. A minimal default network interface is still present but restricted to kubelet healthchecks only

## Prerequisites

- The namespace label **must** be set when the namespace is created — it cannot be added later
- No existing pods can be in the namespace when the primary UDN is created

## Configuration

| Field | Value | Purpose |
|-------|-------|---------|
| `topology` | `Layer2` | Single broadcast domain |
| `role` | `Primary` | Replaces default cluster network |
| `subnets` | `10.200.0.0/16` | IP range for all pods |
| `ipam.lifecycle` | `Persistent` | IPs persist across pod restarts |

## Limitations

- DNS lookups always resolve to the default cluster network IP, not the UDN IP
- Pod IPs are not visible via `kubectl get pods` — check `k8s.ovn.org/pod-networks` annotation
- ClusterIP services are isolated to the UDN; NodePort and LoadBalancer remain cross-network
- Two UDNs can use overlapping subnets since they are fully isolated
