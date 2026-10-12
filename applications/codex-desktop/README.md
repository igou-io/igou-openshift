# Fedora Codex desktop

GitOps owns the namespace, VM definition, retained state PVC, scoped import and
lifecycle RBAC, Services, NetworkPolicy, and
ServiceMonitor. AAP creates/replaces the root DataVolume and configures the guest.
No root DataVolume URL or desktop image build is committed here.

- The VM softly prefers casval when it is schedulable, then other non-control-plane
  workers, with control-plane fallback. There is no required casval selector.
- It tolerates `workload=burst:NoSchedule` and master/control-plane
  `NoSchedule` taints. The control-plane host also has a worker label, so the
  preference explicitly excludes both control-plane role labels.
- `runStrategy: Manual` allows AAP start/stop operations without Argo power drift.
- The namespace and retained state PVC have `Prune=false,Delete=false`; root is independently
  created by AAP and never appears in `dataVolumeTemplates`.
- AAP creates the runtime `codex-desktop-operation` Lease and uses it to
  serialize desktop jobs. Argo excludes coordination Leases.
- Argo preserves KubeVirt's generated MAC, firmware identity, PCI topology
  annotation, and machine default. Scheduling, CPU/RAM, and Manual power remain declarative.
- `daily-apps` in `clusters/ocp/oadp` includes this namespace.

```bash
kustomize build --enable-helm applications/codex-desktop
```

Scheduling preferences live in the VM manifest. Desktop automation controls
only the VM; it does not provision, scale, lease, start, or stop casval.
Initial rollout uses AAP `codex_desktop_rollout`. The start job restores
ephemeral Tailscale enrollment and T3 Serve; the stop job preserves both disks.
Tailscale removes an ephemeral device after it disconnects. Permanent retirement
uses `codex_desktop_stop` before removing the VM definition through GitOps.
See the [Fedora Codex Desktop runbook](https://github.com/igou-io/igou-docs/blob/main/openshift/Fedora%20Codex%20Desktop.md),
including the one-time migration from the previous persistent tailnet registration.
