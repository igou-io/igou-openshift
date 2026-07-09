---
name: add-probe
description: Add a blackbox-exporter Probe target (HTTP/HTTPS/TCP/DNS) to monitor an external or internal service. Appends the URL to an existing Probe CR when the module and label set match, or creates a new Probe. Use when the user asks to monitor a URL, check a cert, or add something to blackbox.
argument-hint: <url> [--module <module>] [--category infra|saas|app:<name>] [--tier critical|standard|best-effort]
disable-model-invocation: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash(kustomize build *), Bash(make lint), Bash(make validate-kustomize), Bash(make test)
---

# Add a blackbox-exporter probe

Add a target to the blackbox-exporter so UWM Prometheus starts scraping it.

## Target URL

Target is: **$ARGUMENTS**

If `$ARGUMENTS` is empty, ask the user for the URL before proceeding.

## Information to gather

Collect the following in a **single** message if not supplied inline:

| Field | Description | Default |
|-------|-------------|---------|
| `url` | Full URL (`https://…`), or `host:port` for `tcp_connect` | from `$ARGUMENTS` |
| `module` | `http_2xx` / `http_2xx_insecure` / `http_post_2xx` / `tcp_connect` / `dns_soa` | `http_2xx` |
| `category` | `infra` / `saas` / `app:<app-name>` | ask |
| `tier` | `critical` / `standard` / `best-effort` | `standard` |
| `owner` | free-text label (team/person); used for alert routing | ask |
| `interval` | scrape interval | `60s` |

## Validation (before writing)

1. **URL format**:
   - For `http_2xx`, `http_2xx_insecure`, `http_post_2xx`: must be `http://…` or `https://…`.
   - For `tcp_connect`: must be `host:port`.
   - For `dns_soa`: must be a domain (no scheme).
   Reject with a clear message if the URL shape doesn't match the module.
2. **Idempotency**: `Grep` for the URL under `components/user-workload-monitoring/exporters/blackbox-exporter/probes/` and under `applications/*/probes/` / `applications/*/*-probe.yaml`. If it already appears anywhere, report the existing location and stop — do not add a duplicate.
3. **icmp** is **not** supported by this component; refuse if requested.

## Target file selection

- `category: app:<name>` → `applications/<name>/<name>-probe.yaml`
  - Create the file if missing; then add it to `applications/<name>/kustomization.yaml` under `resources:` (alphabetical order).
- `category: infra` → `components/user-workload-monitoring/exporters/blackbox-exporter/probes/infra-<module-short>-probe.yaml`
- `category: saas` → `components/user-workload-monitoring/exporters/blackbox-exporter/probes/saas-<module-short>-probe.yaml`

Where `<module-short>` is:
- `http_2xx` → `https`
- `http_2xx_insecure` → `https-insecure`
- `http_post_2xx` → `https-post`
- `tcp_connect` → `tcp`
- `dns_soa` → `dns`

For `http_2xx` in `infra` or `saas`, this matches the existing seed files
(`infra-https-probe.yaml`, `saas-https-probe.yaml`) — prefer appending to
those instead of creating a new file.

## Merge logic

For the chosen target file:

1. **If file exists and a `Probe` CR in it has the same `module` + identical `spec.targets.staticConfig.labels`** (tier, category, owner): append the URL into `spec.targets.staticConfig.static`, keep the list sorted, dedupe.
2. **Else if file exists but no matching Probe**: append a new `Probe` document (separated by `---`) with a unique `metadata.name` (suffix the URL host, sanitized).
3. **Else**: create the file with one `Probe` CR.

Every new `Probe` must include:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: Probe
metadata:
  name: <probe-name>
  namespace: blackbox-exporter
  labels:
    app.kubernetes.io/name: blackbox-exporter
spec:
  interval: <interval>
  module: <module>
  prober:
    url: blackbox-exporter.blackbox-exporter.svc:9115
  targets:
    staticConfig:
      static:
        - <url>
      labels:
        tier: <tier>
        category: <category-or-app-name>
        owner: <owner>
```

App-scoped probes use `category: <app-name>` so alerts can be filtered per app.

## After writing

1. Run `make lint` and `make validate-kustomize`. Report any failures — do not attempt to work around them.
2. Do **not** commit. Leave that to the user.

## Completion report

Return:

1. File(s) written or modified (paths).
2. `make` output summary (pass/fail).
3. Three verification steps the user should follow once Argo syncs:
   - OCP console → Observe → Metrics → `probe_success{instance="<url>"}`
   - Check cert expiry (HTTPS only): `probe_ssl_earliest_cert_expiry{instance="<url>"}`
   - Temporarily break the target to confirm `BlackboxProbeFailed` fires (optional).
4. Reminder to `git add`, commit, and push — Argo applies the `user-workload-monitoring` app automatically at sync-wave 6.
