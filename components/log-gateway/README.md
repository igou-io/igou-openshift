# log-gateway

Central ingest point for **everything that logs from outside the ocp
cluster** (igou-openshift#382): a single Grafana Alloy Deployment behind
the MetalLB VIP **10.10.150.16** (`syslog.igou.systems`).

| Port | Proto | What |
|------|-------|------|
| 514  | udp | RFC3164 (`bsd-syslog`) from appliances: RouterOS ×4, Synology DSM, Home Assistant, UniFi |
| 601  | tcp | RFC3164 over TCP (spare — devices all speak UDP; can't share 514 with UDP, see the Service comment) |
| 1514 | udp | RFC5424 (IETF) for senders whose format is fixed upstream: TrueNAS (syslog-ng `syslog()` driver) |
| 3500 | tcp | Loki push API from Alloy host agents (vscode, upsmonitor, rpi-builder, hermes) and the rk8s Alloy DaemonSet. igou.io is excluded by design — the VPS must not initiate connections into the LAN |

Everything is written to the LokiStack `infrastructure` tenant
(`components/../clusters/ocp/openshift-logging/`) with
`source=external`; the gateway's ServiceAccount token is the **only**
credential for external ingest (`log-gateway-infrastructure-writer`
ClusterRole). Devices and hosts send unauthenticated on the trusted LAN,
fenced by the NetworkPolicy to `10.10.0.0/16`.

Useful LogQL entry points: `{job="syslog"}` (devices, `host` label from
the syslog hostname), `{source="external"}` (all of it),
`{cluster="rk8s"}` (rk8s DaemonSet streams).

Notes:

- `externalTrafficPolicy: Local` + control-plane pinning: the VIP is
  advertised only from the node running the pod, and client source IPs
  survive for the NetworkPolicy ipBlock. Config changes need a manual
  `rollout restart` (the ConfigMap is not hash-suffixed).
- TLS syslog (RFC5424-over-TLS) is a deliberate v1 non-goal on the
  trusted VLAN; the Alloy listener supports it later without redesign.
- The pre-#382 device target (`10.10.9.16:9000`, CEF) had nothing
  listening — there was deliberately no migration listener here; devices
  cut over in igou-inventory (host_vars + DNS) in the same phase.
