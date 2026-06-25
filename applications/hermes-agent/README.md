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

## Firecrawl Connectivity Test

Run these commands inside the Hermes VM after egress syncs. Hermes may reach
`firecrawl-api` on TCP 3002 only; support services (Redis, RabbitMQ, Postgres,
Playwright) must remain unreachable.

```bash
export FIRECRAWL_URL=http://firecrawl-api.firecrawl.svc.cluster.local:3002

curl -fsS "$FIRECRAWL_URL/v0/health/liveness"

curl -fsS -X POST "$FIRECRAWL_URL/v2/scrape" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","formats":["markdown"]}' \
  | jq -r '.data.markdown'

curl -fsS -X POST "$FIRECRAWL_URL/v2/scrape" \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","formats":["markdown"]}' \
  | jq -e '.success == true and (.data.markdown | length) > 0'
```

Expected:

- `/v0/health/liveness` returns `{"status":"ok"}`.
- The scrape response includes markdown containing `Example Domain`.
- The final `jq` command exits `0`.

Negative checks (should fail with connection timeout or refused):

```bash
curl -fsS --connect-timeout 3 http://firecrawl-redis.firecrawl.svc.cluster.local:6379 || true
curl -fsS --connect-timeout 3 http://firecrawl-playwright.firecrawl.svc.cluster.local:3000/health || true
curl -fsS --connect-timeout 3 http://firecrawl-rabbitmq.firecrawl.svc.cluster.local:5672 || true
curl -fsS --connect-timeout 3 http://firecrawl-nuq-postgres.firecrawl.svc.cluster.local:5432 || true
```
