---
# Hermes Agent

## SearXNG Connectivity Test

Run these commands inside the Hermes VM after the guest configuration points
Hermes at the in-cluster SearXNG service:

```bash
export SEARXNG_URL=http://searxng.searxng.svc.cluster.local:8080

curl -fsS "$SEARXNG_URL/healthz"

curl -fsS --get "$SEARXNG_URL/search" \
  --data-urlencode q=OpenShift \
  --data-urlencode format=json \
  | jq '.results | length'

curl -fsS --get "$SEARXNG_URL/search" \
  --data-urlencode q=OpenShift \
  --data-urlencode format=json \
  | jq -r '.results[0] | "\(.title)\n\(.url)"'
```

Expected:

- `/healthz` returns `OK`.
- The JSON result count is greater than `0`.
- The first result has a non-empty `title` and `url`.

To verify Hermes is configured to detect SearXNG, inspect the guest-side Hermes
configuration source managed by Ansible/AAP and confirm these values are active:

```bash
grep -R "search_backend\\|SEARXNG_URL" /etc /opt /var/lib/hermes 2>/dev/null
```

Expected configured values:

```text
SEARXNG_URL=http://searxng.searxng.svc.cluster.local:8080
web.search_backend=searxng
```
