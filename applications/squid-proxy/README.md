# Squid Cursor egress proxy

This application provides a cluster-internal, HTTPS-only Squid CONNECT proxy
for the Cursor CLI used by `hermes-developer` and `hermes-sre`. It is not a
general Hermes egress gateway: only `cursor-agent-proxy` receives the proxy
environment, while `codex`, `claude`, `opencode`, `curl`, package managers, and
ordinary shell commands stay on their existing paths.

## Phase A operation

The proxy is registered at sync wave `19`, before both Hermes applications at
wave `20`. Its NetworkPolicies allow TCP/3128 only from Hermes session pods and
the scale-to-zero `auth-login` pods. Squid allows CONNECT to the current Cursor
documented hostname boundaries and update/download endpoints on TCP/443 only.
HTTP/80, non-Cursor destinations, private ranges, and loopback/link-local
destinations are denied.

Use the wrapper in either Hermes namespace for every Cursor CLI operation:

```bash
cursor-agent-proxy login
cursor-agent-proxy status
cursor-agent-proxy -p --force --trust --sandbox disabled --model cursor-grok-4.5-medium '<spec>'
```

Phase A intentionally retains the temporary broad external EgressFirewall
allow in both Hermes namespaces. Remove those rules only in a separate Phase B
change after the end-to-end proxy checks succeed.

## Failure checks

Inspect the proxy and its logs before changing any live object:

```bash
oc get pods,deploy,svc -n squid-proxy
oc describe deployment/squid-proxy -n squid-proxy
oc logs deployment/squid-proxy -n squid-proxy
```

From an allowed Hermes session or `auth-login` shell, verify the intended and
denied paths:

```bash
curl --noproxy '' --proxy http://squid-proxy.squid-proxy.svc.cluster.local:3128 https://api2.cursor.sh
curl --noproxy '' --proxy http://squid-proxy.squid-proxy.svc.cluster.local:3128 https://example.com
curl --noproxy '' --proxy http://squid-proxy.squid-proxy.svc.cluster.local:3128 https://127.0.0.1
```

The first request should reach Cursor; the latter two should be rejected by
Squid. Check the access log for the CONNECT destination and confirm unrelated
Hermes traffic is absent.

## Rollback

Phase A rollback is a Git revert of the PR. ArgoCD then removes the
`squid-proxy` registration, policies, wrapper mounts, and ConfigMaps while the
temporary Hermes EgressFirewall allows continue to preserve existing Cursor
connectivity. Do not remove those broad allows as part of the Phase A rollback;
that is the separately verified Phase B cutover.
