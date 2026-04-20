---
name: import-grafana-dashboard
description: Import a dashboard from grafana.com or a URL into a Grafana instance managed by the grafana-operator. Fetches the dashboard JSON, resolves its `__inputs` to existing GrafanaDatasources, generates a `GrafanaDashboard` CR, and wires it into the target component's kustomization.yaml.
argument-hint: <grafana-com-id-or-url> [component-path]
allowed-tools: Read, Edit, Write, WebFetch, Bash(kustomize build *), Bash(ls *), Grep, Glob
---

# Import a Grafana dashboard via the Grafana Operator

Generate a `grafana.integreatly.org/v1beta1 GrafanaDashboard` CR that pulls a dashboard from grafana.com (via `spec.grafanaCom`) or from an arbitrary URL (via `spec.url`), and maps its `__inputs` to existing `GrafanaDatasource` resources in the target component.

## Inputs

`$ARGUMENTS` should be `<grafana-com-id-or-url> [component-path]`. Examples:
- `7587`
- `1860 components/grafana`
- `https://raw.githubusercontent.com/org/repo/main/dashboard.json`
- `https://example.com/dashboard.json components/grafana`

**Source detection**: If the first argument is a URL (starts with `http://` or `https://`), use URL mode (`spec.url`). Otherwise treat it as a grafana.com dashboard ID (`spec.grafanaCom`).

If the source is missing, ask. If the component path is missing, default to `components/grafana` and confirm. The component path must contain a `Grafana` CR (so the `instanceSelector` label can be derived) and at least one `GrafanaDatasource` (so inputs can be mapped).

## Step 1: Inspect the target component

1. Verify `<component-path>/kustomization.yaml` exists.
2. Find the `Grafana` CR in the component (`Grep` for `kind: Grafana$`). Read its `metadata.labels` — the `instanceSelector` on the dashboard must match one of these. Conventionally `dashboards: <name>`.
3. Enumerate existing `GrafanaDatasource` resources (`Grep` for `kind: GrafanaDatasource`). Capture each `spec.datasource.name` and its `type` (prometheus, loki, etc.) — these are the candidates for input mapping.
4. Determine the next ArgoCD sync-wave: max wave in the directory + 1 (or reuse the datasource's wave if you want them to apply together).

If the directory has no `Grafana` CR or no `GrafanaDatasource`, stop and tell the user — importing won't work without them.

## Step 2: Fetch the dashboard metadata

### grafana.com mode (numeric ID)

Use `WebFetch` against:

```
https://grafana.com/api/dashboards/<id>
```

Extract:
- `name` / `slug` — for human-readable identification and filename hints
- `latestRevision` — current revision number (for optional pinning)
- `datasource` — the primary datasource type advertised on the listing

Then fetch the dashboard JSON itself (latest revision):

```
https://grafana.com/api/dashboards/<id>/revisions/<latestRevision>/download
```

From the JSON, extract the `__inputs` array. Each entry looks like:

```json
{ "name": "DS_PROMETHEUS", "label": "Prometheus", "type": "datasource", "pluginId": "prometheus" }
```

Capture every entry where `type: datasource` — these are the inputs the operator must rewrite.

If `WebFetch` to grafana.com is blocked in this environment, stop and tell the user; ask them to paste the `__inputs` block from the dashboard JSON, or to provide the JSON via `spec.json:` instead of `spec.grafanaCom:`.

### URL mode (http/https URL)

Use `WebFetch` to fetch the dashboard JSON from the URL directly.

From the JSON, check for:

1. **`__inputs` array** — if present, these need `spec.datasources` mapping (same as grafana.com mode).
2. **Template variables** — if the dashboard uses `$datasource` (a Grafana template variable of type `datasource`), no `spec.datasources` mapping is needed. The user selects the datasource in the Grafana UI at view time.

Extract the dashboard `title` from the JSON for naming hints.

For the `dashboard-name`, derive it from the URL path (e.g. `https://...external-secrets.../dashboard.json` → `grafana-dashboard-external-secrets`). If ambiguous, ask the user.

## Step 3: Map inputs to datasources

For each `__input`:

1. Match its `pluginId` against the `type` of the discovered `GrafanaDatasource` resources.
2. If exactly one datasource matches, use it.
3. If multiple match, ask the user which to use.
4. If none match, warn the user — they will need to add a compatible datasource first, or accept a broken panel.

Build the `datasources:` list using the **exact** `name` from each `__input` (case- and punctuation-sensitive — e.g. `DS_SIGNCL-PROMETHEUS`, not `DS_PROMETHEUS`). A wrong `inputName` silently leaves `${...}` in the panel queries and Grafana shows "datasource not found."

## Step 4: Gather remaining options

| Field | Description | Default |
|-------|-------------|---------|
| `dashboard-name` | `metadata.name` of the GrafanaDashboard CR | `grafana-dashboard-<id>` (grafana.com) or `grafana-dashboard-<slug>` (URL) |
| `pin-revision` | Pin to the current `latestRevision` (`yes`/`no`) — grafana.com only | `no` (track latest) |
| `resync-period` | How often the operator re-pulls from grafana.com | `24h` (grafana.com mode) |
| `content-cache-duration` | How often the operator re-fetches the URL | `24h` (URL mode) |
| `sync-wave` | ArgoCD sync-wave annotation | auto-detect (see Step 1) |
| `folder` | Grafana folder to place the dashboard in | unset (root folder) |

Ask in a single message. Use the dashboard's grafana.com `slug` or URL path to suggest a friendlier `dashboard-name` if the user wants one.

## Step 5: Generate the GrafanaDashboard CR

### grafana.com mode

```yaml
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: <dashboard-name>
  namespace: <namespace-from-Grafana-CR>
  annotations:
    argocd.argoproj.io/sync-wave: '<sync-wave>'
spec:
  instanceSelector:
    matchLabels:
      <key>: <value>          # from the Grafana CR's labels
  resyncPeriod: <resync-period>
  datasources:
    - inputName: <input-name-1>
      datasourceName: <datasource-name-1>
    # ... one entry per __input
  grafanaCom:
    id: <grafana-com-id>
    # revision: <n>           # only if pin-revision=yes
```

### URL mode

```yaml
---
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: <dashboard-name>
  namespace: <namespace-from-Grafana-CR>
  annotations:
    argocd.argoproj.io/sync-wave: '<sync-wave>'
spec:
  instanceSelector:
    matchLabels:
      <key>: <value>          # from the Grafana CR's labels
  url: <dashboard-url>
  contentCacheDuration: <content-cache-duration>
  # datasources:             # only if the JSON has __inputs
  #   - inputName: <input-name-1>
  #     datasourceName: <datasource-name-1>
```

Omit `datasources:` if the dashboard uses Grafana template variables (`$datasource`) instead of `__inputs`. The template variable lets users pick the datasource in the UI.

Include `folder: <folder>` under `spec` only if the user provided one.

### File naming

`<dashboard-name>.yaml` (consistent with the existing convention of `<metadata.name>-<kind>.yaml` — for dashboards the prefix `grafana-dashboard-` already encodes the kind).

## Step 6: Update kustomization.yaml

Append the new file to the `resources:` list of `<component-path>/kustomization.yaml` using `Edit`. Place it after the last existing dashboard, or after the datasource if this is the first.

Do not rewrite the whole file.

## Step 7: Validate

```bash
kustomize build <component-path>/
```

If it fails, fix and rerun before reporting completion.

## Completion report

1. **Dashboard**: title, source (grafana.com ID + revision, or URL)
2. **Inputs resolved**: each `__input` → datasource mapping, or note that dashboard uses template variables (no mapping needed)
3. **File created** (path)
4. **kustomization.yaml updated** (one-line diff)
5. **Kustomize build result**
6. **Next step**: ArgoCD will sync; if the dashboard was already imported with broken inputs, delete the existing `GrafanaDashboard` resource on-cluster to force a clean re-import.

## Notes & gotchas

- The operator only substitutes inputs whose `inputName` matches **exactly** what is in the dashboard JSON's `__inputs[].name`. Common mistake: assuming every Prometheus dashboard uses `DS_PROMETHEUS`. Many use vendor-specific names like `DS_SIGNCL-PROMETHEUS`, `DS_PROM-OPS`, etc.
- `tlsSkipVerify: true` on the datasource (as in the hub's `thanos-querier`) is fine — the substitution happens by datasource UID, not URL.
- The Grafana CR must already include the dashboard's label in `instanceSelector.matchLabels` — otherwise the operator silently ignores the new dashboard.
- For air-gapped imports, replace `spec.grafanaCom` with `spec.json: |` and inline the JSON, or `spec.url:` pointing at an internal mirror. Everything else (inputs mapping, instance selector) is identical.
- **`__inputs` vs template variables**: Dashboards exported from grafana.com typically use `__inputs` for datasource binding. Dashboards from project repos often use Grafana template variables (`$datasource` of type `datasource`) instead — these don't need `spec.datasources` mapping because the user selects the datasource in the UI. Check the JSON for both patterns.
- **`spec.url` caching**: The operator fetches the URL on initial sync and re-fetches after `contentCacheDuration` expires. Unlike `spec.grafanaCom` which uses `resyncPeriod`, URL-sourced dashboards use `contentCacheDuration`. If neither is set, the operator uses its default (which may be very long).
- **`spec.url` auth**: For private URLs, use `spec.urlAuthorization` to attach bearer tokens or basic auth headers. Public raw GitHub URLs don't need auth.
