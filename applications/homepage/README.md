# homepage

Lab landing page at <https://home.apps.ocp.igou.systems> — [gethomepage.dev](https://gethomepage.dev)
deployed via the bjw-s `app-template` chart (same pattern as ntfy).

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
   gethomepage.dev/href: https://myapp.example.com/
   gethomepage.dev/siteMonitor: https://myapp.example.com/health
   ```

   Current annotated examples: Jellyfin, MeTube, and T3 Code
   (HTTPRoute). New apps should prefer Ingress (`className:
   openshift-default`) over a raw Route — OpenShift generates the Route from
   the Ingress and homepage can discover it.

2. **Static tiles** in `config/services.yaml` — for apps exposed via raw
   OpenShift Routes (not discoverable), off-cluster things (TrueNAS), and the
   rk8s cluster (homepage discovery is same-cluster only).

Group layout/order is controlled in `config/settings.yaml`; discovered and
static tiles merge into the same named groups.

## Availability checks

Every linked static tile has a `siteMonitor`; discovered tiles set
`gethomepage.dev/siteMonitor` on their HTTPRoute. `statusStyle: basic` shows
an explicit UP/DOWN badge. These are HTTP checks from the Homepage pod every
30 seconds while the page is open. They follow redirects; use public health
endpoints where available. The pinned Homepage version treats HTTP 401/403
as reachable, so netboot.xyz's expected authentication challenge is UP.
Other tiles check the linked page or its login page. The GitHub queue tiles
check `https://github.com`, not the authenticated user's PR search.

Continuous monitoring is separate: the blackbox exporter's `infra-https`
Probe and the app-local SO-CRATES Probe cover the remaining linked services,
alongside existing infra,
media, GitHub, VPS, and Jellyfin probes. It supplies failure and TLS alerts
even when nobody has Homepage open. Keep both layers current when adding
links; a working widget or Kubernetes pod status alone does not test ingress.
SO-CRATES uses `http_2xx_http10` because its server returns HTTP/1.0; that
module retains TLS verification and requires a 2xx response.

## Widgets / secrets

- Kubernetes cluster + node utilisation (info widget, needs `metrics.k8s.io`
  — see `homepage-clusterrole.yaml`).
- TrueNAS pool/alert widget: API key comes from 1Password
  (`lab_openshift/truenas` → `truenas_api_key` field only) via ExternalSecret
  as env var `HOMEPAGE_VAR_TRUENAS_KEY`, referenced from `services.yaml` as
  `{{HOMEPAGE_VAR_TRUENAS_KEY}}`.
- ArgoCD and AAP widgets use read-only tokens from their ExternalSecrets.

## Gotchas

- `HOMEPAGE_ALLOWED_HOSTS` must match the Route host or homepage serves 400s.
- Namespace is default-deny. `homepage-egress-networkpolicy.yaml` permits
  DNS, the kube-apiserver, and HTTPS to the linked service destinations.
  Gateway checks also match Envoy pods after DNAT. New destinations need
  matching egress rules; test from the Homepage pod, not only a workstation.
- Set an explicit HTTPS `gethomepage.dev/href` on HTTPRoutes whose Gateway
  has an HTTP listener first; discovery otherwise infers HTTP from it.
- Homepage has no auth of its own — it is only reachable via the trusted-LAN
  default ingress tier.
