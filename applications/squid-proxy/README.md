# Shared Hermes HTTP/HTTPS egress proxy

This application provides the cluster-local Squid proxy used by the three
Hermes instances. HTTP-aware processes in the Hermes agents, generated
sessions, authentication pods, GitHub App brokers, and SRE docs-sync job
inherit:

```text
HTTP_PROXY=http://squid-proxy.squid-proxy.svc.cluster.local:3128
HTTPS_PROXY=http://squid-proxy.squid-proxy.svc.cluster.local:3128
```

The equivalent lowercase variables are set as well. `NO_PROXY`/`no_proxy` is
the same minimal value everywhere:

```text
localhost,127.0.0.1,::1,.cluster.local,172.30.0.1,api.ocp.igou.systems,10.10.9.10
```

The `.cluster.local` suffix covers Kubernetes service names. The explicit
`172.30.0.1` entry keeps in-cluster Kubernetes clients on the direct API service
path; without it, clients try to tunnel the private service IP through Squid and
receive `403 Forbidden`. The `api.ocp.igou.systems` and `10.10.9.10` entries keep
the external OCP API name and the checked-in SRE Thanos HTTPS route
(`thanos-querier-openshift-monitoring.apps.ocp.igou.systems`), respectively, on
their direct paths; the latter is the documented OCP/apps-router VIP. There is
no wrapper or alternate Cursor invocation; `cursor-agent` and other HTTP-aware
clients use the standard environment.

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

## Enforced egress architecture

Hermes-associated workloads may reach DNS, their explicitly approved internal
services, and Squid on TCP/3128. Their NetworkPolicies deny generic direct
public traffic on TCP/80, TCP/443, and non-standard ports. Approved internal
traffic stays direct and is excluded from the proxy by `NO_PROXY`.

Squid is the public web egress choke point. It alone may initiate public TCP/80
and TCP/443 connections, while both its NetworkPolicy and destination ACLs deny
private, cluster-internal, loopback, and special-use networks. Clients that do
not honor `HTTP_PROXY`/`HTTPS_PROXY` do not have generic Internet access. Squid
access logs provide visibility into proxied HTTP/HTTPS traffic without TLS
interception.

## Failure checks

Inspect the proxy and its logs before changing any live object:

```bash
oc get pods,deploy,svc -n squid-proxy
oc describe deployment/squid-proxy -n squid-proxy
oc logs deployment/squid-proxy -n squid-proxy
```

From an allowed Hermes session or `auth-login` shell, verify both public
protocols, direct-egress enforcement, and the denied internal proxy path:

```bash
curl --noproxy '' --proxy http://squid-proxy.squid-proxy.svc.cluster.local:3128 http://example.com
curl --noproxy '' --proxy http://squid-proxy.squid-proxy.svc.cluster.local:3128 https://example.com
curl --noproxy '*' http://example.com
curl --noproxy '*' https://example.com
curl --noproxy '' --proxy http://squid-proxy.squid-proxy.svc.cluster.local:3128 https://127.0.0.1
```

The first two requests should reach public destinations. Both direct requests
and the proxied loopback request must fail. Check the access log for the proxied
requests and confirm unrelated internal Hermes traffic is absent because it
bypasses Squid.

## Rollback

If the enforced boundary breaks required traffic, Git-revert the Phase B PR.
ArgoCD will restore the Phase A direct-egress fallbacks while leaving the
working Squid deployment and proxy environment in place.
