# Disposable RHEL IdM and Satellite lab

Four clean RHEL 9 guests in namespace `redhat-lab`, pinned to
`casval.igou.systems`. Install IdM and Satellite yourself; cloud-init only
prepares networking, SSH access, swap, and Satellite's content disk.

| Guest | FQDN | Private address | vCPU | RAM | Disks |
|---|---|---|---|---|---|
| idm | idm.lab.igou.systems | 192.168.240.10 | 2 | 6 GiB | 40 GiB |
| satellite | satellite.lab.igou.systems | 192.168.240.20 | 8 | 32 GiB | 80 GiB root + 100 GiB Pulp |
| client1 | client1.lab.igou.systems | 192.168.240.31 | 2 | 4 GiB | 30 GiB |
| client2 | client2.lab.igou.systems | 192.168.240.32 | 2 | 4 GiB | 30 GiB |

IdM and Satellite each get 4 GiB swap. Total guest RAM is 46 GiB; allow
additional VM overhead. All disks use TrueNAS
`freenas-nvmeof-ssd-csi`, not Casval's ephemeral local disks.
Nominal guest disk capacity is 280 GiB: 40 + 80 + 100 + 30 + 30.
CDI adds filesystem-volume overhead to the server root PVC requests.
The 40/80 GiB server roots use filesystem volumes with CDI copies: raw-block
snapshot clones requiring expansion hit this driver's NodeExpand mount-path
error. The 30 GiB client roots still use block snapshot clones, and the blank
Pulp disk is block-backed. CDI helper pods alone can reach the API and accept
image transfers from the boot-image namespace.

## Bring up and destroy

From this repository:

```bash
use ocp
use aap
test-workloads/redhat-lab/labctl up
test-workloads/redhat-lab/labctl status
```

`up` uses the existing AAP `casval_scale` template if Casval is down,
waits for node readiness, creates the namespace, and waits for VM readiness.
A cold Casval provision can take 20–30 minutes. An already Ready node is reused
without taking ownership of somebody else's lease. If another job is currently
provisioning it, wait for that job before retrying.

The AAP template receives `casval_state=up`, `casval_lease_id=redhat-lab`,
and `casval_lease=24h`. Override the duration with `LAB_CASVAL_LEASE`
(`2h`, `4h`, `8h`, `12h`, or `24h`). This direct AAP launch records
a deadline; it does **not** launch AO's timed workflow. Release the node
explicitly when finished.

```bash
# Destroys the entire lab namespace and every VM disk.
test-workloads/redhat-lab/labctl down

# Separately release Casval when no other workloads need it.
test-workloads/redhat-lab/labctl node-down
```

`node-down` refuses if the lab still exists, another workflow owns the
lease, or another non-DaemonSet pod is running on Casval. The AAP playbook
also checks lease ownership. To reset, run `down` followed by `up`.
`up` on an existing lab preserves its current disks.

This directory is intentionally absent from the ArgoCD app-of-apps:
ArgoCD must not recreate a namespace you just destroyed. Manifests remain
the declarative source; `labctl` renders them with Kustomize.

## Access

The cloud-init `igou` account uses your lab's Ansible SSH public key.
Load its matching private key into the SSH agent:

```bash
ssh-use ansible
virtctl ssh -n redhat-lab igou@vm/idm
virtctl ssh -n redhat-lab igou@vm/satellite
virtctl ssh -n redhat-lab igou@vm/client1
virtctl ssh -n redhat-lab igou@vm/client2
```

Fresh clones get new SSH host keys. With virtctl's local OpenSSH client,
remove the old lab records after a reset before reconnecting:

```bash
for vm in idm satellite client1 client2; do
  ssh-keygen -R "vm.$vm.redhat-lab"
done
```

Inside each guest, verify preparation before starting an installation:

```bash
sudo cloud-init status --wait
hostname -f
ip -brief address
getent hosts idm.lab.igou.systems satellite.lab.igou.systems
sudo swapon --show
```

On Satellite, also verify `findmnt /var/lib/pulp` shows the XFS data disk.
Register the RHEL guests using your own subscriptions. Satellite needs its
Satellite repositories, and a subscription manifest for Red Hat content.
Before destroying registered guests, unregister them or remove their
consumer records from the subscription service.

After installing a service, forward its HTTPS port locally:

```bash
virtctl port-forward -n redhat-lab vm/satellite 8443:443
virtctl port-forward -n redhat-lab vm/idm 8444:443
```

Use a workstation hosts entry mapping the corresponding FQDN to
`127.0.0.1`, then browse `https://satellite.lab.igou.systems:8443` or
`https://idm.lab.igou.systems:8444`. Satellite generates links using its
canonical FQDN and port 443; for those workflows, forward local port 443
with a suitably privileged client, or use an SSH SOCKS tunnel with
browser-side proxy DNS. Trust the lab CA when exercising TLS.

## Networking and DNS

Each guest has two interfaces:

- `uplink`: masqueraded pod interface with DHCP and internet egress.
- `lab`: static address on a private OVN Layer2 secondary network.
  It has no physical VLAN uplink, default gateway, or CNI IPAM.

DHCP/PXE broadcasts on `lab` stay inside this logical network. Guest-to-guest
traffic is unrestricted there. The Kubernetes NetworkPolicy covers the pod
network, allowing DNS and public internet egress while excluding private LAN
and cluster ranges. SSH and HTTPS access use the KubeVirt API tunnel.
The policy permits ports 22 and 443 from `virt-api` and `virt-handler`
pods in `openshift-cnv`, which relay those tunnels to the launcher pod.
Do not enable guest routing between the two interfaces.

A small CoreDNS pod on the control-plane node supplies initial A/PTR records
for all four hosts and forwards other queries to cluster DNS. Its Service is
`172.30.250.53`; `labctl up` refuses a conflicting allocation. KubeVirt
passes this resolver to each guest through uplink DHCP.

Use `lab.igou.systems` as the IdM domain and `LAB.IGOU.SYSTEMS` as the realm.
When installing IdM with integrated DNS, select its private address explicitly
(`--ip-address=192.168.240.10`), create the reverse zone, and use
`172.30.250.53` as the external forwarder. The bootstrap resolver supplies
A/PTR records, not IdM SRV records; it never forwards the lab zone back to IdM.
Create the other hosts' A/PTR records in IdM and move the clients to IdM DNS:

```bash
# Run on each client after IdM DNS is working. The connection name is
# discovered by interface; cloud-init's renderer chooses the actual profile name.
LAB_CONNECTION=$(nmcli -g GENERAL.CONNECTION device show lab)
sudo nmcli connection modify "$LAB_CONNECTION" \
  ipv4.dns 192.168.240.10 ipv4.dns-search lab.igou.systems ipv4.dns-priority -50
sudo nmcli connection up "$LAB_CONNECTION"
```

Leave IdM's installer-managed local resolver in place. Chrony/timekeeping,
firewalld service rules, repository configuration, installation, enrollment,
and content synchronization are part of the exercises.

## Suggested exercises

1. Register and update RHEL; inspect hostname, forward/reverse DNS and time sync.
2. Install IdM with DNS and CA; enroll client1; explore users, groups, HBAC,
   sudo policies, Kerberos, and certificates.
3. Install Satellite on its dedicated guest; import a manifest; synchronize
   a small RHEL repository set, using On Demand downloads to start.
4. Create content views, lifecycle environments and activation keys; register
   client2; practice patching and remote execution.
5. Integrate Satellite realm enrollment with IdM. Later add an IdM replica,
   Capsule, or an uninstalled PXE target as separate optional guests.
6. Destroy the namespace and repeat the installation from fresh clones.

## Validation and references

```bash
shellcheck test-workloads/redhat-lab/labctl
yamllint -c .yamllint test-workloads/redhat-lab
kustomize build test-workloads/redhat-lab
```

Satellite 6.19 requires a fresh dedicated latest RHEL 9 x86_64 system,
at least 4 CPU cores, 20 GiB RAM and 4 GiB swap. Its content storage depends
on repositories and retention. The 100 GiB Pulp disk is intended for a
disposable lab using On Demand RPM repositories. An illustrative budget is
40 GiB downloaded packages + 10 GiB retained older packages + 10 GiB metadata
and temporary space = 60 GiB. Keeping 25% free requires 60 / 0.75 = 80 GiB;
100 GiB leaves extra room. These are planning assumptions, not measured
repository sizes. Full repository downloads require sizing from actual content
totals. Red Hat's 300 GB runtime example includes RHEL 7, 8, and 9 repositories
and is not an empty-install content requirement.

- [Satellite installation requirements](https://docs.redhat.com/en/documentation/red_hat_satellite/6.19/html/installing_satellite_server_in_a_connected_network_environment/planning-satellite-server-installation_satellite)
- [Installing Identity Management on RHEL 9](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/installing_identity_management/index)
- [Satellite content and subscription manifests](https://docs.redhat.com/en/documentation/red_hat_satellite/6.19/html-single/managing_content/index)
- [OVN secondary Layer2 networks](https://github.com/ovn-kubernetes/ovn-kubernetes/blob/master/docs/features/multiple-networks/multi-homing.md)
