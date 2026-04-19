# Blackbox Exporter

Synthetic probing of external services from inside the cluster. Deployed by the
`user-workload-monitoring` ArgoCD app, lives in its own `blackbox-exporter`
namespace, and is scraped by UWM Prometheus.

Manifests: `components/user-workload-monitoring/exporters/blackbox-exporter/`

## What it gives you

- `probe_success` — up/down per target
- `probe_duration_seconds` — end-to-end latency
- `probe_http_status_code`, `probe_http_duration_seconds` — HTTP detail
- `probe_ssl_earliest_cert_expiry` — TLS cert expiry timestamp

Alerts shipped out of the box (`blackbox-exporter-prometheusrule.yaml`):

| Alert | Trigger |
|---|---|
| `BlackboxProbeFailed` | `probe_success == 0` for 5m |
| `BlackboxProbeFailedCritical` | `probe_success{tier="critical"} == 0` for 2m |
| `BlackboxProbeSlow` | `probe_duration_seconds > 5` for 10m |
| `BlackboxSSLCertExpiringSoon` | cert expires within 14 days |
| `BlackboxSSLCertExpiringCritical` | cert expires within 3 days |

All rules use `openshift.io/prometheus-rule-evaluation-scope: leaf-prometheus`
so they route via the UWM Alertmanager and respect namespace-scoped
`AlertmanagerConfig` resources.

## Available modules

Defined in the chart `valuesInline.config.modules` stanza:

| Module | Use |
|---|---|
| `http_2xx` | Default HTTPS, verify cert |
| `http_2xx_insecure` | Self-signed endpoints (FreeNAS, iDRAC, RouterOS) |
| `http_post_2xx` | POST health endpoints |
| `tcp_connect` | Plain port reachability |
| `dns_soa` | DNS resolution check |

ICMP is intentionally not enabled (requires `NET_RAW` capability). Add it to
the chart values if needed later.

## Adding a target

**Preferred: the `/add-probe` skill** — it enforces the conventions below,
validates URL shape, prevents duplicates, and updates kustomization.yaml when
app-local probe files are created.

```
/add-probe https://example.apps.igou.systems --category infra --tier standard
```

### Manual workflow

1. Pick the target file by category:

   | Category | Location |
   |---|---|
   | App in this repo | `applications/<app>/<app>-probe.yaml` (add to that app's `kustomization.yaml` resources list) |
   | External infra (FreeNAS, RouterOS, nginx vhosts) | `components/user-workload-monitoring/exporters/blackbox-exporter/probes/infra-<module-short>-probe.yaml` |
   | SaaS / public | `components/user-workload-monitoring/exporters/blackbox-exporter/probes/saas-<module-short>-probe.yaml` |

2. If a `Probe` CR in that file already uses the **same module and identical
   labels**, append the URL under `spec.targets.staticConfig.static`. Otherwise
   add a new `Probe` document to the file.

3. Include these labels on every Probe:

   - `tier` — `critical` / `standard` / `best-effort` (drives alert severity)
   - `category` — `infra` / `saas` / or the app name
   - `owner` — free-text for alert routing

4. Run `make lint validate-kustomize`, commit, push. Argo syncs within ~30s
   and UWM Prometheus picks up the new scrape config automatically.

### Example — append an HTTPS target

`components/user-workload-monitoring/exporters/blackbox-exporter/probes/infra-https-probe.yaml`:

```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: infra-https
  namespace: blackbox-exporter
  labels:
    app.kubernetes.io/name: blackbox-exporter
spec:
  interval: 60s
  module: http_2xx
  prober:
    url: blackbox-exporter.blackbox-exporter.svc:9115
  targets:
    staticConfig:
      static:
        - https://hub.igou.systems
        - https://pgadmin.apps.igou.systems   # new entry
      labels:
        tier: standard
        category: infra
        owner: platform
```

### Example — different module needs its own Probe

Self-signed TLS goes in `infra-https-insecure-probe.yaml`, not mixed with
verified-cert targets:

```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: infra-https-insecure
  namespace: blackbox-exporter
  labels:
    app.kubernetes.io/name: blackbox-exporter
spec:
  interval: 60s
  module: http_2xx_insecure
  prober:
    url: blackbox-exporter.blackbox-exporter.svc:9115
  targets:
    staticConfig:
      static:
        - https://freenas.igou.systems
      labels:
        tier: standard
        category: infra
        owner: platform
```

### Example — app-local probe

`applications/jellyfin/jellyfin-probe.yaml`:

```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: jellyfin
  namespace: blackbox-exporter
  labels:
    app.kubernetes.io/name: blackbox-exporter
spec:
  interval: 60s
  module: http_2xx
  prober:
    url: blackbox-exporter.blackbox-exporter.svc:9115
  targets:
    staticConfig:
      static:
        - https://jellyfin.apps.igou.systems
      labels:
        tier: critical
        category: jellyfin
        owner: media
```

Remember to add `jellyfin-probe.yaml` to `applications/jellyfin/kustomization.yaml`.

## Removing a target

Delete the URL line. The series age out of Prometheus per retention. Active
alerts auto-resolve on the next evaluation.

## Verifying

After Argo sync:

1. OCP console → Observe → Metrics:
   ```
   probe_success{instance="https://<url>"}
   probe_ssl_earliest_cert_expiry{instance="https://<url>"}
   probe_http_status_code{instance="https://<url>"}
   ```
2. Observe → Alerting → Silences/Alerts to confirm new probes are being
   evaluated.

## Reachability gotchas

Probes originate from the `blackbox-exporter` pod on the cluster pod network.
If a target lives on a VLAN the pod network can't reach, either:

- Route via the cluster egress (default SNAT through the node), which works
  for anything reachable from the hub node.
- Or add a Multus secondary interface to the blackbox deployment on the
  target VLAN (chart doesn't expose this — would need a patch overlay).

## Cert expiry coverage

`probe_ssl_earliest_cert_expiry` is only populated when the probe actually
performs a TLS handshake. Use `http_2xx` (not `http_2xx_insecure`) wherever
possible so the cert-expiry alerts remain meaningful.
