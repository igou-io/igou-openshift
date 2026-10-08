# Fedora Codex desktop

GitOps owns the namespace, VM definition, retained state PVC, scoped import and
lifecycle RBAC, Services, NetworkPolicy, and
ServiceMonitor. AAP creates/replaces the root DataVolume and configures the guest.
No root DataVolume URL or desktop image build is committed here.

- `overlays/standard`: soft preference for non-control-plane workers and casval.
- `overlays/casval`: the same policy plus a required burst node selector.
- Both tolerate `workload=burst:NoSchedule` and master/control-plane
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
kustomize build --enable-helm applications/codex-desktop/overlays/standard
kustomize build --enable-helm applications/codex-desktop/overlays/casval
```

Select the overlay in `clusters/ocp/values.yaml` while stopped and sync Argo CD
before starting. Initial rollout uses AAP `codex_desktop_rollout`; routine power
jobs preserve both disks and enrollment. See
`igou-ansible/docs/codex-desktop.md` and the Fedora Codex Desktop vault runbook.
