# homepage

Lab landing page at <https://home.apps.ocp.igou.systems> — [gethomepage.dev](https://gethomepage.dev)
deployed via the bjw-s `app-template` chart (same pattern as ntfy/gitea-mirror).

## How tiles get on the page

Two paths:

1. **Auto-discovery (preferred, zero dashboard config).** Homepage watches the
   cluster (`config/kubernetes.yaml`: `mode: cluster`, `gateway: true`) and
   builds tiles from `gethomepage.dev/*` annotations on **Ingress** and
   **Gateway API HTTPRoute** objects. Minimum viable annotation block:

   ```yaml
   gethomepage.dev/enabled: "true"
   gethomepage.dev/name: My App
   gethomepage.dev/group: Applications
   gethomepage.dev/icon: myapp.png
   ```

   Current annotated examples: ntfy + gitea-mirror (Ingress), jellyfin
   (HTTPRoute). New apps should prefer Ingress (`className:
   openshift-default`) over a raw Route — OpenShift generates the Route from
   the Ingress and homepage can discover it.

2. **Static tiles** in `config/services.yaml` — for apps exposed via raw
   OpenShift Routes (not discoverable), off-cluster things (TrueNAS), and the
   rk8s cluster (homepage discovery is same-cluster only).

Group layout/order is controlled in `config/settings.yaml`; discovered and
static tiles merge into the same named groups.

## Widgets / secrets

- Kubernetes cluster + node utilisation (info widget, needs `metrics.k8s.io`
  — see `homepage-clusterrole.yaml`).
- TrueNAS pool/alert widget: API key comes from 1Password
  (`lab_openshift/truenas` → `truenas_api_key` field only) via ExternalSecret
  as env var `HOMEPAGE_VAR_TRUENAS_KEY`, referenced from `services.yaml` as
  `{{HOMEPAGE_VAR_TRUENAS_KEY}}`.
- Follow-up candidate: ArgoCD widget (needs a read-only apiKey account minted
  in the openshift-gitops ArgoCD CR + a 1P item; skipped in v1).

## Gotchas

- `HOMEPAGE_ALLOWED_HOSTS` must match the Route host or homepage serves 400s.
- Namespace is default-deny; egress allows only DNS, kube-apiserver
  (post-DNAT node IP `10.10.9.10:6443` — OVN-K matches after service DNAT)
  and the TrueNAS API (`10.10.9.213:443`). A new widget that calls anything
  else needs a matching egress rule.
- Homepage has no auth of its own — it is only reachable via the trusted-LAN
  default ingress tier.
