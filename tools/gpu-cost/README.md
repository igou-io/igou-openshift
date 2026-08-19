# gpu-cost

CLI answer to "how much money in power did my GPUs consume?". Reads the
measured per-GPU energy counter (`DCGM_FI_DEV_TOTAL_ENERGY_CONSUMPTION`,
millijoules) from thanos-querier and prices it at Dominion Energy VA
Schedule 1 (zip 23236) marginal rates including all per-kWh riders
(filings effective 2026-07-01): summer (Jun–Sep) 14.834 ¢/kWh, winter
(Oct–May) 12.907 ¢/kWh. Windows are split on calendar-month boundaries
(America/New_York) so each month's energy gets that month's rate.

Same rate model and data source as the "OpenShift Energy Cost" Grafana
board (`components/grafana/dashboards/power/energy-cost.json`) — this is
the ad-hoc/scriptable version.

## Usage

```bash
export KUBECONFIG=...   # ocp; token minted via oc (prometheus-k8s SA)
./gpu-cost              # last 24h
./gpu-cost 7d           # <n>h / <n>d / <n>w
./gpu-cost --from 2026-08-15 --to "2026-08-18 17:00"
./gpu-cost 30d --json   # machine-readable
./gpu-cost 7d --summer-rate 0.16   # override $/kWh
```

Output: kWh and USD per GPU per consuming namespace (from the DCGM
`exported_namespace` label), plus totals and average watts.

## Caveats

- Energy is **measured** (DCGM counter), not modeled — but the counter
  resets when casval reboots (burst scale-from-zero); the last
  scrape-to-shutdown sliver is lost. Negligible for session accounting.
- A window larger than the counter's lifetime just returns everything
  the counter saw — it cannot invent pre-boot history.
- `--from`/`--to` accept `YYYY-MM-DD` (midnight local) or
  `YYYY-MM-DD HH:MM`.
- Stdlib-only Python 3.9+ (needs `zoneinfo`), plus `oc` on PATH.
