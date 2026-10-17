# Public services web test

A single nginx replica returns `public-services web test` on HTTP port 8080.
It runs under the restricted SCC with a read-only root filesystem and no API
token. The ClusterIP Service is `public-web-test.public-services.svc:8080`.

The existing `.helm/charts/tailscale-public-services` chart owns the namespace
and its guardrails. Install those first with an empty service catalog:

```bash
helm template public-services .helm/charts/tailscale-public-services \
  --namespace public-services > /tmp/public-services-guardrails.yaml
oc apply -f /tmp/public-services-guardrails.yaml
oc apply -k test-workloads/public-services-web
oc rollout status deployment/public-web-test -n public-services
```

The namespace denies ingress and egress except DNS. This fixture has no Route
or public listener; a later Tailscale endpoint needs its own narrow ingress
policy. For a local application check:

```bash
oc port-forward -n public-services service/public-web-test 18080:8080
curl --fail http://127.0.0.1:18080/
```

Port forwarding checks the server through the API; it does not test the
Tailscale/VPS path or bypass denial for ordinary network clients.

Remove only the fixture, preserving the shared namespace and guardrails:

```bash
oc delete -k test-workloads/public-services-web
```
