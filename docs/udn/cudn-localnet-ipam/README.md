# ClusterUserDefinedNetwork — Localnet with OVN IPAM

Connects pods to a physical VLAN using OVN-managed IP assignment. Pods egress directly to the physical network without SNAT — pod IPs are preserved.

## When to use

- Pods need to be reachable on a physical VLAN with a routable IP
- You want OVN to manage IP assignment automatically
- Multiple namespaces need access to the same physical network

## How it works

1. The CUDN creates an OVN logical switch connected to the physical network via the OVS bridge mapping
2. OVN assigns IPs from the `subnets` range, excluding addresses in `excludeSubnets`
3. `lifecycle: Persistent` ensures IPs survive pod restarts via `ipamclaims` objects
4. Namespaces opt in via a label selector — add `network.igou.systems/vlan45: "true"` to any namespace

## Configuration

| Field | Value | Purpose |
|-------|-------|---------|
| `physicalNetworkName` | `trunk-network` | Must match the `localnet` name in OVS bridge-mappings |
| `vlan.access.id` | `45` | VLAN tag applied to traffic |
| `subnets` | `10.10.45.0/24` | IP range for OVN IPAM |
| `excludeSubnets` | `.0-.199` | Reserved for existing devices on the network |
| `ipam.mode` | `Enabled` | OVN assigns IPs |
| `ipam.lifecycle` | `Persistent` | IPs persist across pod restarts |

## Pod annotation

Pods reference the CUDN-generated NAD by name:

```yaml
annotations:
  k8s.v1.cni.cncf.io/networks: vlan45-shared
```

## Pin a specific IP

To force OVN to assign a specific IP (e.g., `.221`), use `excludeSubnets` to exclude everything else. See `clusters/hub/udn/jellyfin-cudn.yaml` for an example.
