# vlan9-vm-multinode

End-to-end validation that VLAN 9 (`trunk-network` localnet via the
`vlan9-no-ipam` ClusterUserDefinedNetwork) works on every node that carries
`br-secondary`. Deploys one CentOS Stream 10 VM per node:

| VM | Pinned to | Pattern |
|---|---|---|
| `vm-ocp` | `ocp.igou.systems` (SNO master+worker) | B — secondary network |
| `vm-hpg5` | `hpg5.igou.systems` (worker) | B — secondary network |
| `vm-casval` | `casval` (CAPI burst worker) | C — secondary + burst toleration |

Start an AO `casval-lease` before applying this workload. The casval VM's
launcher stays Pending until BMC powers casval on, RHCOS deploys, the node
joins, the `mapping-casval` NNCE converges, and the VM schedules. Plan up to
30 minutes from lease start to Ready.

`vlan9-no-ipam` has IPAM disabled — VMs rely on DHCP on VLAN 9. The
qemu-guest-agent reports the lease back to KubeVirt for inspection via
`virtctl`.

```bash
oc apply -k test-workloads/vlan9-vm-multinode/

# Watch VMs (vm-casval will sit in WaitingForVolumeBinding then Scheduling
# until casval finishes provisioning)
oc -n vlan9-vm-multinode get vm,vmi -w

# Once Running, check guest IPs
oc -n vlan9-vm-multinode get vmi -o custom-columns=NAME:.metadata.name,NODE:.status.nodeName,IFACES:.status.interfaces

# SSH from a privileged debug pod (or via virtctl ssh)
virtctl -n vlan9-vm-multinode ssh igou@vm-ocp
```

Delete the workload before the lease expires so CAPM3 can drain and
deprovision the BMH cleanly:

```bash
oc delete -k test-workloads/vlan9-vm-multinode/
```
