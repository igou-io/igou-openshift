# multus-macvlan-dhcp-nginx

Macvlan secondary network with DHCP IPAM and nginx deployment. Matches the macvlan example from the [OKD docs](https://docs.okd.io/4.21/networking/multiple_networks/secondary_networks/creating-secondary-nwt-other-cni.html).

## What this demonstrates

- Macvlan CNI plugin with DHCP-assigned IP address
- No static IP in the NAD or pod annotation — the DHCP server on the VLAN assigns the address
- Routes (including default gateway) come from the DHCP lease, not from CNI config

## Prerequisites

- VLAN subinterface `enp2s0f1.45` must exist on the node (created via NMState NNCP)
- A DHCP server must be available and running on VLAN 45 — the CNI DHCP daemon is **not** a DHCP server, it is a client-side daemon that relays requests to an external DHCP server
- The CNI DHCP IPAM daemon must be deployed on the cluster (see [Enabling the DHCP IPAM daemon](#enabling-the-dhcp-ipam-daemon) below)

## Enabling the DHCP IPAM daemon

The DHCP IPAM CNI plugin has two components:

1. **CNI plugin** (`/var/lib/cni/bin/dhcp`) — integrates with the Kubernetes networking stack to request and release IP addresses
2. **DHCP IPAM CNI daemon** — listens on `/run/cni/dhcp.sock` and coordinates with the external DHCP server to handle lease requests and renewals

The daemon is **not deployed by default**. To trigger its deployment, you must create a shim network attachment definition via the Cluster Network Operator (CNO). This is a cluster-level change to the `Network.operator.openshift.io` CR — it is not applied via this kustomization.

Edit the CNO configuration:

```bash
oc edit network.operator.openshift.io cluster
```

Add the `additionalNetworks` section under `spec`:

```yaml
apiVersion: operator.openshift.io/v1
kind: Network
metadata:
  name: cluster
spec:
  additionalNetworks:
  - name: dhcp-shim
    namespace: default
    type: Raw
    rawCNIConfig: |-
      {
        "name": "dhcp-shim",
        "cniVersion": "0.3.1",
        "type": "bridge",
        "ipam": {
          "type": "dhcp"
        }
      }
```

This shim NAD tells the CNO to deploy the DHCP IPAM daemon. The shim itself does not need to be used by any pod — its purpose is solely to trigger the daemon deployment.

Without this configuration, pod creation will fail with:

```
error dialing DHCP daemon: dial unix /run/cni/dhcp.sock: connect: no such file or directory
```

### Alternative: whereabouts

If no external DHCP server is available, or you prefer not to modify the CNO configuration, use the [whereabouts example](../multus-macvlan-whereabouts-nginx/) instead. Whereabouts provides cluster-managed dynamic IP allocation without requiring an external DHCP server or the DHCP daemon.

## Resources

| File | Resource | Description |
|------|----------|-------------|
| `namespace.yaml` | Namespace | `multus-macvlan-dhcp-nginx` |
| `nad-vlan45.yaml` | NetworkAttachmentDefinition | Macvlan on `enp2s0f1.45` with DHCP IPAM |
| `deployment.yaml` | Deployment | nginx with DHCP-assigned IP on secondary interface |
| `service.yaml` | Service | ClusterIP service on port 80 -> 8080 |
| `route.yaml` | Route | Edge-terminated TLS route |

## Usage

```bash
# 1. Ensure the DHCP IPAM daemon is running (see above)
# 2. Ensure a DHCP server is serving VLAN 45

oc apply -k .
oc exec -n multus-macvlan-dhcp-nginx deploy/nginx -- ip a  # net1 interface should have DHCP-assigned IP
oc exec -n multus-macvlan-dhcp-nginx deploy/nginx -- ip r  # routes from DHCP lease
```

## Notes

- The pod annotation uses the short form (`vlan45-macvlan-dhcp`) since no per-pod IP or MAC override is needed
- `linkInContainer: false` explicitly states the master interface is in the host network namespace (the default)
- DHCP leases are periodically renewed by the DHCP IPAM daemon throughout the lifetime of the pod
- If the DHCP server provides a default gateway, cross-subnet routing works without explicit route config in the NAD
- Compliant with `restricted-v2` SCC (seccompProfile, runAsNonRoot, drop ALL capabilities)
