# User Workload Monitoring

OpenShift UWM deploys a second Prometheus + Thanos Ruler (+ optional Alertmanager)
into `openshift-user-workload-monitoring` for scraping app metrics, evaluating
custom rules, and routing alerts — all via CRs in the app's own namespace.

Enable the component at `components/user-workload-monitoring/`.

## Add a service to monitor

Create a `ServiceMonitor` (or `PodMonitor`) in the application's namespace
matching the Service that exposes `/metrics`.

```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: example-app
  namespace: example-app
  labels:
    app.kubernetes.io/name: example-app
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: example-app
  endpoints:
    - port: metrics
      interval: 30s
      scheme: http
      path: /metrics
      # For TLS + bearer-token scraping (e.g. serving-cert annotated Service):
      # scheme: https
      # tlsConfig:
      #   ca:
      #     configMap:
      #       name: openshift-service-ca.crt
      #       key: service-ca.crt
      # bearerTokenSecret:
      #   name: <sa-token-secret>
      #   key: token
```

## Custom recording rules and alerts

```yaml
---
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: example-app
  namespace: example-app
  labels:
    app.kubernetes.io/name: example-app
    # Route via UWM Alertmanager (leaf) rather than platform Alertmanager.
    openshift.io/prometheus-rule-evaluation-scope: leaf-prometheus
spec:
  groups:
    - name: example-app.recording
      interval: 30s
      rules:
        - record: example_app:request_errors:rate5m
          expr: |
            sum by (namespace, pod) (
              rate(http_requests_total{namespace="example-app",status=~"5.."}[5m])
            )
    - name: example-app.alerts
      rules:
        - alert: ExampleAppHighErrorRate
          expr: example_app:request_errors:rate5m > 1
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: Example app 5xx error rate above 1 req/s
            description: |
              Pod {{ $labels.pod }} in {{ $labels.namespace }} has
              {{ $value | humanize }} 5xx/sec over the last 5m.
```

## Namespace-scoped alert routing

`enableAlertmanagerConfig: true` is set on the UWM Alertmanager, so
developers with `alert-routing-edit` can route their own alerts:

```yaml
---
apiVersion: monitoring.coreos.com/v1beta1
kind: AlertmanagerConfig
metadata:
  name: example-app
  namespace: example-app
spec:
  route:
    receiver: slack
    groupBy: [alertname, namespace]
    groupWait: 30s
    groupInterval: 5m
    repeatInterval: 12h
  receivers:
    - name: slack
      slackConfigs:
        - apiURL:
            name: slack-webhook
            key: url
          channel: '#alerts'
          sendResolved: true
```

## Dashboards

UWM does not bundle Grafana. Options:

- **OpenShift console** — Observe → Dashboards supports custom dashboards via
  `ConsoleDashboard` ConfigMaps in `openshift-config-managed` (JSON Grafana format).
- **Grafana Operator** — deploy separately and point its datasource at
  `https://thanos-querier.openshift-monitoring.svc:9091` with a bearer token
  from a ServiceAccount bound to `cluster-monitoring-view`.

## Gotchas

- Default retention is 24h — this component sets 15d on PVCs via
  `freenas-nvmeof-fast-csi`.
- Alerts from `PrometheusRule` route to **platform** Alertmanager by default.
  Add `openshift.io/prometheus-rule-evaluation-scope: leaf-prometheus` to use
  the UWM Alertmanager and `AlertmanagerConfig` routing.
- A developer needs `monitoring-rules-edit` / `monitoring-edit` on the
  namespace to create `ServiceMonitor` / `PrometheusRule`.
