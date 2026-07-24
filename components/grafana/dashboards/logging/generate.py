#!/usr/bin/env python3
"""Generate ALL logging dashboards (igou-openshift#382 + overhaul spec).

Conventions from the researched overhaul spec (workflow 2026-07-24):
- now-1h default window, auto-refresh OFF, picker floor 5m (window size is
  the real scan-cost lever on 1x.demo; widened-range + auto-refresh is THE
  expensive combination).
- Entity query variables stay refresh=2 (On Time Range Change) — refresh=1
  is a dropdown trap when the operator widens the window.
- $search is a SUBSTRING filter (|=), not regex: cheap, never errors on
  metacharacters. Curated regexes stay in panel exprs.
- Timeseries = range + [$__auto]; bargauge/stat = instant + [$__range]
  wrapped in topk — small returned matrix (render cost, not scan cost).
- Severity matchers live INSIDE the stream selector where a level label
  exists (syslog); the (?i) error regex is only for level-less streams.
- Fixed level->color mapping wherever grouped by level; red reserved for
  error severity, never volume.
- KPI stat rows only on single-entity boards (hermes, sands-of-time).
- Logs panels: standard options, maxLines=1000 on the TARGET, prettify
  only for structured-JSON app logs.
"""
import json
import sys

OUT = sys.argv[1]

PERF_NOTE = (" Default 1h window with auto-refresh off: widen the range "
             "deliberately and refresh manually — widened-range + "
             "auto-refresh is the expensive combination on the small Loki.")

LEVEL_OVERRIDES = [
    {"matcher": {"id": "byRegexp", "options": "err.*|error"},
     "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#F2495C"}}]},
    {"matcher": {"id": "byRegexp", "options": "crit.*|panic|alert|emerg.*"},
     "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#B877D9"}}]},
    {"matcher": {"id": "byRegexp", "options": "warn.*"},
     "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#FF9830"}}]},
    {"matcher": {"id": "byRegexp", "options": "info.*|notice"},
     "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#73BF69"}}]},
    {"matcher": {"id": "byRegexp", "options": "debug"},
     "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "#5794F2"}}]},
]

def ds(input_name):
    return {"type": "loki", "uid": "${%s}" % input_name}

def inputs(pairs):
    return [{"name": n, "label": l, "type": "datasource", "pluginId": "loki"}
            for n, l in pairs]

def var_query(d, name, label, query):
    # refresh=2 (On Time Range Change) is INTENTIONAL — refresh=1 would
    # freeze the dropdown at the 1h default when the operator widens the
    # window to chase an older incident.
    return {"name": name, "label": label, "type": "query", "datasource": d,
            "definition": query, "query": query, "refresh": 2, "multi": True,
            "includeAll": True, "sort": 1,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]}}

def var_text(name, label):
    return {"name": name, "label": label, "type": "textbox",
            "current": {"text": "", "value": ""}, "query": ""}

def ts(d, title, expr, legend, x, y, w=12, h=8, desc="", overrides=None,
       bars=False):
    custom = {"lineWidth": 2, "fillOpacity": 8, "pointSize": 4,
              "showPoints": "never", "drawStyle": "line"}
    if bars:
        custom = {"lineWidth": 0, "fillOpacity": 100, "drawStyle": "bars",
                  "barAlignment": 1,
                  "stacking": {"mode": "normal", "group": "A"}}
    return {"type": "timeseries", "title": title, "description": desc,
            "datasource": d, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "fieldConfig": {"defaults": {"unit": "short", "custom": custom},
                            "overrides": overrides or []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom",
                                   "calcs": ["max"]},
                        "tooltip": {"mode": "multi", "sort": "desc"}},
            "targets": [{"datasource": d, "expr": expr,
                         "legendFormat": legend, "refId": "A"}]}

def bargauge(d, title, expr, legend, x, y, w=8, h=6, desc=""):
    return {"type": "bargauge", "title": title, "description": desc,
            "datasource": d, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"displayMode": "basic", "orientation": "horizontal",
                        "reduceOptions": {"calcs": ["lastNotNull"]},
                        "valueMode": "color"},
            "fieldConfig": {"defaults": {"unit": "short",
                "color": {"mode": "continuous-BlPu"}}, "overrides": []},
            "targets": [{"datasource": d, "expr": expr, "legendFormat": legend,
                         "instant": True, "refId": "A"}]}

def stat(d, title, expr, x, y, w=6, h=4, thresholds=None, desc=""):
    if thresholds:
        fc = {"defaults": {"unit": "short", "color": {"mode": "thresholds"},
                           "thresholds": {"mode": "absolute",
                                          "steps": thresholds}},
              "overrides": []}
        color_mode = "background"
    else:
        # Neutral: red is never spent on volume.
        fc = {"defaults": {"unit": "short",
                           "color": {"mode": "fixed", "fixedColor": "text"}},
              "overrides": []}
        color_mode = "none"
    return {"type": "stat", "title": title, "description": desc,
            "datasource": d, "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "fieldConfig": fc,
            "options": {"graphMode": "none", "colorMode": color_mode,
                        "reduceOptions": {"calcs": ["lastNotNull"]},
                        "textMode": "auto"},
            "targets": [{"datasource": d, "expr": expr, "instant": True,
                         "refId": "A"}]}

def logs(d, title, expr, x, y, w=24, h=12, prettify=False):
    return {"type": "logs", "title": title, "datasource": d,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"showTime": True, "wrapLogMessage": True,
                        "enableLogDetails": True, "showLabels": False,
                        "prettifyLogMessage": prettify,
                        "dedupStrategy": "none", "sortOrder": "Descending"},
            "targets": [{"datasource": d, "expr": expr, "maxLines": 1000,
                         "refId": "A"}]}

def board(title, uid, input_pairs, variables, panels, desc):
    return {"__inputs": inputs(input_pairs), "title": title, "uid": uid,
            "description": desc + PERF_NOTE, "tags": ["logging"],
            "schemaVersion": 39, "timezone": "browser",
            "time": {"from": "now-1h", "to": "now"}, "refresh": False,
            "timepicker": {"refresh_intervals": ["5m", "15m", "30m", "1h"]},
            "templating": {"list": variables}, "panels": panels}

APP = ds("DS_LOKI_APPLICATION")
INF = ds("DS_LOKI_INFRASTRUCTURE")
APP_IN = [("DS_LOKI_APPLICATION", "loki-application")]
INF_IN = [("DS_LOKI_INFRASTRUCTURE", "loki-infrastructure")]
boards = {}

# ---------------- Fleet Journals ----------------
boards["fleet-journals"] = board(
    "Fleet Journals", "fleet-journals", INF_IN,
    [var_query(INF, "host", "Host", 'label_values({job="systemd-journal"}, host)'),
     var_query(INF, "unit", "Unit", 'label_values({job="systemd-journal", host=~"$host"}, unit)'),
     var_text("search", "Line contains")],
    [ts(INF, "Journal volume by host",
        'sum by (host) (count_over_time({job="systemd-journal", host=~"$host"}[$__auto]))',
        "{{host}}", 0, 0),
     ts(INF, "Error-ish lines by host",
        'sum by (host) (count_over_time({job="systemd-journal", host=~"$host"} |~ `(?i)(error|fail|critical|panic|oom)` [$__auto]))',
        "{{host}}", 12, 0,
        desc="Unanchored regex — journals carry no level label; bounded by the 1h default window."),
     bargauge(INF, "Noisiest units (selection, range)",
        'topk(10, sum by (unit) (count_over_time({job="systemd-journal", host=~"$host", unit=~"$unit"}[$__range])))',
        "{{unit}}", 0, 8,
        desc="Top 10 units by line count over the dashboard range."),
     bargauge(INF, "Volume by host (range)",
        'topk(10, sum by (host) (count_over_time({job="systemd-journal", host=~"$host"}[$__range])))',
        "{{host}}", 8, 8),
     ts(INF, "OOM / kernel panic mentions",
        'sum by (host) (count_over_time({job="systemd-journal", host=~"$host"} |~ `Out of memory|oom-kill|Kernel panic` [$__auto]))',
        "{{host}}", 16, 8, w=8, h=6,
        desc="Feeds the HostKernelOOM alert; should normally be empty."),
     logs(INF, "Journal lines",
          '{job="systemd-journal", host=~"$host", unit=~"$unit"} |= `$search`',
          0, 14)],
    "systemd journals shipped by the alloy role (linux_logging) and the rk8s DaemonSet — igou-openshift#382.")

# ---------------- Device Syslog ----------------
boards["device-syslog"] = board(
    "Device Syslog", "device-syslog", INF_IN,
    [var_query(INF, "host", "Device", 'label_values({job="syslog"}, host)'),
     var_query(INF, "level", "Severity", 'label_values({job="syslog", host=~"$host"}, level)'),
     var_text("search", "Line contains")],
    [ts(INF, "Syslog volume by device",
        'sum by (host) (count_over_time({job="syslog", host=~"$host"}[$__auto]))',
        "{{host}}", 0, 0),
     ts(INF, "Volume by severity",
        'sum by (level) (count_over_time({job="syslog", host=~"$host", level=~"$level"}[$__auto]))',
        "{{level}}", 12, 0, bars=True, overrides=LEVEL_OVERRIDES,
        desc="Severity from the syslog PRI relabel (indexed level label); stacked Explore-style histogram."),
     ts(INF, "Login failures (RouterOS)",
        'sum by (host) (count_over_time({job="syslog", host=~"$host"} |= `login failure` [$__auto]))',
        "{{host}}", 0, 8, w=12, h=6,
        desc="Feeds the RouterOSLoginFailures alert (>3 in 15m)."),
     bargauge(INF, "Lines per device (range)",
        'topk(10, sum by (host) (count_over_time({job="syslog", host=~"$host"}[$__range])))',
        "{{host}}", 12, 8, w=12,
        desc="A device at zero here for a day trips SyslogRouterOSSilent."),
     logs(INF, "Device lines",
          '{job="syslog", host=~"$host", level=~"$level"} |= `$search`',
          0, 14)],
    "Appliance/device syslog through the log-gateway (RouterOS, TrueNAS, future Synology/HA/UniFi) — igou-openshift#382.")

# ---------------- rk8s Logs ----------------
boards["rk8s-logs"] = board(
    "rk8s Logs", "rk8s-logs", INF_IN,
    [var_query(INF, "namespace", "Namespace", 'label_values({cluster="rk8s", job="rk8s-pods"}, namespace)'),
     var_query(INF, "pod", "Pod", 'label_values({cluster="rk8s", job="rk8s-pods", namespace=~"$namespace"}, pod)'),
     var_text("search", "Line contains")],
    [ts(INF, "Pod-log volume by namespace",
        'sum by (namespace) (count_over_time({cluster="rk8s", job="rk8s-pods", namespace=~"$namespace"}[$__auto]))',
        "{{namespace}}", 0, 0),
     ts(INF, "Error-ish pod lines by namespace",
        'sum by (namespace) (count_over_time({cluster="rk8s", job="rk8s-pods", namespace=~"$namespace"} |~ `(?i)(error|fail|panic)` [$__auto]))',
        "{{namespace}}", 12, 0),
     ts(INF, "Node journal volume",
        'sum by (host) (count_over_time({cluster="rk8s", job="systemd-journal"}[$__auto]))',
        "{{host}}", 0, 8, w=12, h=6),
     logs(INF, "Cluster events (filter with search)",
          '{cluster="rk8s", job="loki.source.kubernetes_events"} |= `$search`',
          12, 8, w=12, h=6),
     logs(INF, "Pod lines",
          '{cluster="rk8s", job="rk8s-pods", namespace=~"$namespace", pod=~"$pod"} |= `$search`',
          0, 14)],
    "rk8s ship-don't-store: pod logs, node journals, and cluster events via the Alloy DaemonSet — igou-openshift#382.")

# ---------------- ocp Application Logs ----------------
boards["ocp-application-logs"] = board(
    "ocp Application Logs", "ocp-application-logs", APP_IN,
    [var_query(APP, "namespace", "Namespace",
               'label_values({log_type="application"}, kubernetes_namespace_name)'),
     var_query(APP, "pod", "Pod",
               'label_values({log_type="application", kubernetes_namespace_name=~"$namespace"}, kubernetes_pod_name)'),
     var_text("search", "Line contains")],
    [ts(APP, "Volume by namespace",
        'sum by (kubernetes_namespace_name) (count_over_time({log_type="application", kubernetes_namespace_name=~"$namespace"}[$__auto]))',
        "{{kubernetes_namespace_name}}", 0, 0),
     ts(APP, "Error-ish lines by namespace",
        'sum by (kubernetes_namespace_name) (count_over_time({log_type="application", kubernetes_namespace_name=~"$namespace"} |~ `(?i)(error|fail|panic|fatal)` [$__auto]))',
        "{{kubernetes_namespace_name}}", 12, 0),
     bargauge(APP, "Noisiest pods (range)",
        'topk(10, sum by (kubernetes_pod_name) (count_over_time({log_type="application", kubernetes_namespace_name=~"$namespace", kubernetes_pod_name=~"$pod"}[$__range])))',
        "{{kubernetes_pod_name}}", 0, 8, w=12),
     bargauge(APP, "Noisiest namespaces (range)",
        'topk(10, sum by (kubernetes_namespace_name) (count_over_time({log_type="application", kubernetes_namespace_name=~"$namespace"}[$__range])))',
        "{{kubernetes_namespace_name}}", 12, 8, w=12,
        desc="Chronic top-talkers are retention/prune candidates."),
     logs(APP, "Pod lines",
          '{log_type="application", kubernetes_namespace_name=~"$namespace", kubernetes_pod_name=~"$pod"} |= `$search`',
          0, 14, prettify=True)],
    "ocp user-namespace pod logs (application tenant) — igou-openshift#382.")

# ---------------- ocp Infrastructure Logs ----------------
boards["ocp-infrastructure-logs"] = board(
    "ocp Infrastructure Logs", "ocp-infrastructure-logs", INF_IN,
    [var_query(INF, "node", "Node",
               'label_values({log_type="infrastructure"}, kubernetes_host)'),
     var_query(INF, "namespace", "Infra namespace",
               'label_values({log_type="infrastructure", kubernetes_namespace_name=~".+"}, kubernetes_namespace_name)'),
     var_text("search", "Line contains")],
    [ts(INF, "Node journal volume",
        'sum by (kubernetes_host) (count_over_time({log_type="infrastructure", kubernetes_namespace_name="", kubernetes_host=~"$node"}[$__auto]))',
        "{{kubernetes_host}}", 0, 0,
        desc="journald streams have no namespace label — empty-label matcher isolates them (index-cheap)."),
     ts(INF, "Infra pod volume by namespace",
        'sum by (kubernetes_namespace_name) (count_over_time({log_type="infrastructure", kubernetes_namespace_name=~"$namespace"}[$__auto]))',
        "{{kubernetes_namespace_name}}", 12, 0),
     ts(INF, "Error-ish node journal lines",
        'sum by (kubernetes_host) (count_over_time({log_type="infrastructure", kubernetes_namespace_name="", kubernetes_host=~"$node"} |~ `(?i)(error|fail|panic|oom)` [$__auto]))',
        "{{kubernetes_host}}", 0, 8, w=12, h=6),
     bargauge(INF, "Noisiest infra namespaces (range)",
        'topk(10, sum by (kubernetes_namespace_name) (count_over_time({log_type="infrastructure", kubernetes_namespace_name=~"$namespace"}[$__range])))',
        "{{kubernetes_namespace_name}}", 12, 8, w=12),
     logs(INF, "Node journals",
          '{log_type="infrastructure", kubernetes_namespace_name="", kubernetes_host=~"$node"} |= `$search`',
          0, 14, h=9),
     logs(INF, "Infra pod lines",
          '{log_type="infrastructure", kubernetes_namespace_name=~"$namespace"} |= `$search`',
          0, 23, h=9)],
    "ocp node journals + infrastructure-namespace pod logs. Audit tenant is deliberately Grafana-excluded (admin/CLI only) — igou-openshift#382.")

# ---------------- MikroTik ----------------
MTX = 'host=~"rb5009|crs310|crs317|crs328"'
boards["mikrotik"] = board(
    "MikroTik", "mikrotik", INF_IN,
    [var_query(INF, "host", "Device",
               'label_values({job="syslog", %s}, host)' % MTX),
     var_text("search", "Line contains")],
    [ts(INF, "Volume by device",
        'sum by (host) (count_over_time({job="syslog", %s, host=~"$host"}[$__auto]))' % MTX,
        "{{host}}", 0, 0),
     ts(INF, "Login failures",
        'sum by (host) (count_over_time({job="syslog", %s, host=~"$host"} |= `login failure` [$__auto]))' % MTX,
        "{{host}}", 12, 0, w=6, h=8,
        desc="Feeds the RouterOSLoginFailures alert (>3 in 15m)."),
     ts(INF, "Interface link events",
        'sum by (host) (count_over_time({job="syslog", %s, host=~"$host"} |~ `link (up|down)` [$__auto]))' % MTX,
        "{{host}}", 18, 0, w=6, h=8,
        desc="Port flapping shows here — the 92d syslog retention exists for this."),
     ts(INF, "DHCP lease events",
        'sum by (host) (count_over_time({job="syslog", %s, host=~"$host"} |~ `(?i)dhcp` [$__auto]))' % MTX,
        "{{host}}", 0, 8, w=12, h=6),
     ts(INF, "Severity (warnings and up)",
        'sum by (level) (count_over_time({job="syslog", %s, host=~"$host", level=~"warning|err.*|crit.*"}[$__auto]))' % MTX,
        "{{level}}", 12, 8, w=12, h=6, bars=True, overrides=LEVEL_OVERRIDES,
        desc="Indexed level matcher inside the selector; stacked by severity."),
     logs(INF, "Device lines",
          '{job="syslog", %s, host=~"$host"} |= `$search`' % MTX,
          0, 14)],
    "RouterOS fleet syslog (rb5009 + crs310/317/328) — igou-openshift#382.")

# ---------------- Hermes ----------------
HERMES_ERR = 'sum (count_over_time({job="systemd-journal", host="hermes"} |~ `(?i)(error|fail|denied)` [%s]))'
boards["hermes"] = board(
    "Hermes", "hermes-logs", INF_IN,
    [var_query(INF, "unit", "Unit",
               'label_values({job="systemd-journal", host="hermes"}, unit)'),
     var_text("search", "Line contains")],
    [stat(INF, "Journal lines (range)",
          'sum (count_over_time({job="systemd-journal", host="hermes"}[$__range]))',
          0, 0, desc="Neutral by design — red is reserved for errors."),
     stat(INF, "Error-ish lines (range)", HERMES_ERR % "$__range", 6, 0,
          thresholds=[{"color": "green", "value": None},
                      {"color": "#FF9830", "value": 25},
                      {"color": "#F2495C", "value": 100}],
          desc="Same expression as the error trend below, as a glance tile."),
     ts(INF, "Journal volume by unit",
        'sum by (unit) (count_over_time({job="systemd-journal", host="hermes", unit=~"$unit"}[$__auto]))',
        "{{unit}}", 0, 4),
     ts(INF, "sudo invocations",
        'sum (count_over_time({job="systemd-journal", host="hermes"} |= `sudo` |= `COMMAND=` [$__auto]))',
        "sudo", 12, 4, w=6, h=8,
        desc="The agent VM is hardened; sudo use should be operator sessions only."),
     ts(INF, "sshd sessions and auth",
        'sum (count_over_time({job="systemd-journal", host="hermes", unit=~"sshd.*"} |~ `(?i)(accepted|failed|session opened)` [$__auto]))',
        "sshd", 18, 4, w=6, h=8),
     ts(INF, "Shipper + user-scope services",
        'sum by (unit) (count_over_time({job="systemd-journal", host="hermes", unit=~".*(hermes|alloy|user@).*"}[$__auto]))',
        "{{unit}}", 0, 12, w=12, h=6,
        desc="The hermes agent runs as systemd USER units, which journald tags under user@1001.service — only alloy.service is a system unit."),
     ts(INF, "Error-ish lines", HERMES_ERR % "$__auto",
        "errors", 12, 12, w=12, h=6),
     logs(INF, "hermes journal",
          '{job="systemd-journal", host="hermes", unit=~"$unit"} |= `$search`',
          0, 18)],
    "The hermes agent VM's journal: sudo/sshd security panels + its own service units — igou-openshift#382.")

# ---------------- KubeVirt VMs ----------------
VMSEL = 'kubernetes_pod_name=~"virt-launcher-.*"'
boards["kubevirt-vms"] = board(
    "KubeVirt VMs", "kubevirt-vms",
    APP_IN + INF_IN,
    [var_query(APP, "namespace", "VM namespace",
               'label_values({log_type="application", %s}, kubernetes_namespace_name)' % VMSEL),
     var_query(APP, "pod", "virt-launcher pod",
               'label_values({log_type="application", kubernetes_namespace_name=~"$namespace", %s}, kubernetes_pod_name)' % VMSEL),
     var_text("search", "Line contains")],
    [ts(APP, "virt-launcher volume by VM pod",
        'sum by (kubernetes_pod_name) (count_over_time({log_type="application", kubernetes_namespace_name=~"$namespace", %s}[$__auto]))' % VMSEL,
        "{{kubernetes_pod_name}}", 0, 0),
     ts(APP, "Error-ish launcher lines",
        'sum by (kubernetes_pod_name) (count_over_time({log_type="application", kubernetes_namespace_name=~"$namespace", %s} |~ `(?i)(error|fail)` [$__auto]))' % VMSEL,
        "{{kubernetes_pod_name}}", 12, 0,
        desc="Launcher/libvirt errors: stuck volume attach, migration, device issues."),
     logs(APP, "virt-launcher lines (qemu/libvirt/hypervisor)",
          '{log_type="application", kubernetes_namespace_name=~"$namespace", kubernetes_pod_name=~"$pod"} |= `$search`',
          0, 8, h=10),
     logs(INF, "Guest journals (where shipped: hermes)",
          '{job="systemd-journal", host="hermes"} |= `$search`',
          0, 18, h=8)],
    "KubeVirt VM host-side logs (virt-launcher pods) across namespaces; guest journals appear where the guest ships them — igou-openshift#382.")

# ---------------- sands-of-time ----------------
SOT = '{log_type="application", kubernetes_namespace_name="sands-of-time"}'
SOT_ERR = 'sum (count_over_time(%s |~ `(?i)(error|fail|traceback|exception)` [%%s]))' % SOT
boards["sands-of-time"] = board(
    "sands-of-time", "sands-of-time-logs", APP_IN,
    [var_query(APP, "pod", "Pod",
               'label_values(%s, kubernetes_pod_name)' % SOT),
     var_text("search", "Line contains")],
    [stat(APP, "Lines (range)",
          'sum (count_over_time(%s[$__range]))' % SOT,
          0, 0, desc="Neutral by design — red is reserved for errors."),
     stat(APP, "Error-ish lines (range)", SOT_ERR % "$__range", 6, 0,
          thresholds=[{"color": "green", "value": None},
                      {"color": "#FF9830", "value": 10},
                      {"color": "#F2495C", "value": 50}],
          desc="Same expression as the error trend below, as a glance tile."),
     ts(APP, "Volume by pod",
        'sum by (kubernetes_pod_name) (count_over_time(%s[$__auto]))' % SOT.replace("}", ", kubernetes_pod_name=~\"$pod\"}"),
        "{{kubernetes_pod_name}}", 0, 4),
     ts(APP, "Error-ish lines", SOT_ERR % "$__auto",
        "errors", 12, 4, w=6, h=8),
     ts(APP, "HTTP requests",
        'sum (count_over_time(%s |~ `(GET|POST|PUT|DELETE) /` [$__auto]))' % SOT,
        "requests", 18, 4, w=6, h=8,
        desc="API access lines incl. the hermes ATL cron reads."),
     logs(APP, "sands-of-time lines",
          '%s |= `$search`' % SOT.replace("}", ", kubernetes_pod_name=~\"$pod\"}"),
          0, 12, prettify=True)],
    "sands-of-time app logs (application tenant) — igou-openshift#382.")

for name, b in boards.items():
    path = f"{OUT}/{name}.json"
    with open(path, "w") as f:
        json.dump(b, f, indent=2)
        f.write("\n")
    print("wrote", path)
