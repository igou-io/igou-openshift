# Shared Hermes HTTP/HTTPS egress proxy

This application provides the cluster-local Squid proxy used by the three
Hermes instances. HTTP-aware processes in the Hermes agents, generated
sessions, authentication pods, GitHub App brokers, and SRE docs-sync job
inherit:

```text
HTTP_PROXY=http://squid-proxy.squid-proxy.svc.cluster.local:3128
HTTPS_PROXY=http://squid-proxy.squid-proxy.svc.cluster.local:3128
```

The equivalent lowercase variables are set as well. `NO_PROXY`/`no_proxy`
keeps localhost, Kubernetes service DNS, the Kubernetes API, and each
instance's checked-in internal dependencies on their direct NetworkPolicy-
controlled paths. There is no wrapper or alternate Cursor invocation;
`cursor-agent` and other HTTP-aware clients use the standard environment.

Squid currently allows arbitrary public HTTP on TCP/80 and HTTPS CONNECT on
TCP/443. It denies private, cluster-internal, loopback, link-local, CGNAT,
multicast, reserved, and IPv6 special-use destinations before the public
allow. TLS is passed through without interception or SSL bumping. Future
per-workload or per-domain allowlists can be added in Squid without changing
the workload-level proxy architecture.

The proxy is registered at sync wave `19`, before the Hermes applications at
wave `20`. Its NetworkPolicies allow TCP/3128 only from the intended Hermes
agents, generated sessions, scale-to-zero `auth-login` pods, GitHub App brokers,
and SRE docs-sync job. Squid has no Route, LoadBalancer, NodePort, hostPort,
or hostNetwork exposure.

## Phase A operation

Phase A deploys and wires the proxy while retaining the existing direct Hermes
external egress rules as rollback protection. This allows proxy behavior and
application health to be verified before the separate Phase B cutover.

Phase B will remove direct external HTTP/HTTPS access only after verification
proves that external traffic works through Squid, internal `.svc` traffic
bypasses it successfully, and Squid rejects internal destinations.

## Failure checks

Inspect the proxy and its logs before changing any live object:

```bash
oc get pods,deploy,svc -n squid-proxy
oc describe deployment/squid-proxy -n squid-proxy
oc logs deployment/squid-proxy -n squid-proxy
```

From an allowed Hermes session or `auth-login` shell, verify both public
protocols and the denied internal path:

```bash
curl --noproxy '' --proxy http://squid-proxy.squid-proxy.svc.cluster.local:3128 http://example.com
curl --noproxy '' --proxy http://squid-proxy.squid-proxy.svc.cluster.local:3128 https://example.com
curl --noproxy '' --proxy http://squid-proxy.squid-proxy.svc.cluster.local:3128 https://127.0.0.1
```

The first two requests should reach public destinations; the last should be
rejected by Squid. Check the access log for the expected request and confirm
unrelated internal Hermes traffic is absent because it bypasses the proxy.

## Rollback

Phase A rollback is a Git revert of the PR. ArgoCD then removes the Squid
registration and policies while the existing direct Hermes egress remains in
place. Do not remove those direct rules as part of the Phase A rollback; that
is the separately verified Phase B cutover.
