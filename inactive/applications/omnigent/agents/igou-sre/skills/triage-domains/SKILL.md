---
name: triage-domains
description: Domain deep-dives when the generic alert-triage pass is not enough - storage (democratic-csi/TrueNAS), network (MetalLB/BGP/OVN), rk8s, and change correlation (what merged recently).
version: 1.0.0
author: igou-io
platforms:
  - linux
metadata:
  igou:
    tags:
      - sre
      - storage
      - network
      - rk8s
      - argocd
---

# Triage deep-dives

Start with `openshift-alert-triage`; come here when the symptom is in one
of these domains and the generic pass did not name a cause. Read ONLY the
matching file:

- PVC/PV stuck, mount or provisioning failures, `dataset is busy`,
  NVMe-oF/iSCSI errors, snapshot problems -> `storage.md`
- LoadBalancer/VIP unreachable, BGP/BFD, probe failures, slow first
  byte, secondary-interface/Multus, *.dmz routes -> `network.md`
- Anything on the rk8s cluster (its Alertmanager relays here too) -> `rk8s.md`
- "It worked yesterday" / find what changed -> `change-correlation.md`

Every path stays read-only and ends in the standard triage report.
