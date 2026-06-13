# Connecting to your namespace on the OpenShift cluster

A guide for a **first‑time, onboarded user**. By "onboarded" we mean an
administrator has already:

1. **added your device/identity to the tailnet** (you can sign in to Tailscale), and
2. **created your namespace and an access grant** that maps your tailnet identity to
   your namespace's group (`<your‑namespace>-operator`).

If either of those isn't true yet, stop here and ask the administrator — the steps
below won't work without them.

> **How access works (in one sentence).** The Kubernetes API is **not** exposed on the
> public internet; it's reachable only over the tailnet, through the Tailscale
> operator's *API‑server proxy*, which authenticates you by your Tailscale identity and
> *impersonates* you into your namespace group. So your **Tailscale login is your
> cluster login** — there's no separate password or token.

There are two halves to this guide. **Part A** runs on *your* machine (Tailscale +
kubeconfig). **Part B** is everything you do once connected — and every command in
Part B has been verified against the live cluster.

---

## TL;DR

```bash
# one-time, on your machine:
tailscale up                                        # join the tailnet
tailscale configure kubeconfig tailscale-operator   # write a kubeconfig for the cluster
oc whoami                                           # -> your tailnet identity

# then, every day:
oc config set-context --current --namespace=<your-namespace>
oc get pods
oc apply -f deploy.yaml
```

Your **namespace** and **identity** were given to you by the admin, e.g. namespace
`alice-dev`, identity `alice@example.com`. Substitute your own throughout.

---

## Prerequisites

| Tool | Why | Get it | Check |
|------|-----|--------|-------|
| **Tailscale** | the only network path to the cluster API | <https://tailscale.com/download> | `tailscale version` |
| **`oc`** (OpenShift CLI) | talk to the cluster (the cluster is OpenShift **4.21**; `kubectl` also works for most things, but `oc` adds `whoami`, `oc new-app`, routes, etc.) | <https://mirror.openshift.com/pub/openshift-v4/clients/ocp/> (pick a 4.x build) | `oc version --client` |

MagicDNS is enabled on the tailnet, so the short name `tailscale-operator` resolves
once you're connected — you don't need a full `*.ts.net` address.

---

## Part A — connect (runs on your machine)

> The two `tailscale …` commands below run on your own laptop/workstation and need the
> Tailscale client, so they are documented from the Tailscale Kubernetes‑operator docs
> and this cluster's operator configuration rather than executed in this repo. Part B
> (everything after you're connected) is verified live.

### A1. Join the tailnet

```bash
tailscale up
tailscale status
```

`tailscale status` should list **you** as active and show a machine named
**`tailscale-operator`** — that's the cluster's API‑server proxy. If you don't see it,
you're either not signed in to the right tailnet or your device hasn't been authorized;
ask the admin.

### A2. Write your kubeconfig

```bash
tailscale configure kubeconfig tailscale-operator
```

This adds a context named `tailscale-operator` to `~/.kube/config`, points it at
`https://tailscale-operator` (a name that only resolves while you're connected to the
tailnet), makes it your current context, and wires in Tailscale as the auth mechanism —
**no token or password**.

- If `tailscale configure` is "unknown command", update your Tailscale client.
- If the proxy has a different name, find the API‑server‑proxy machine in the Tailscale
  admin console → **Machines**, or ask the admin, and pass that name instead.

---

## Part B — verified usage (runs against the cluster)

### B1. Confirm you're connected and correctly scoped

```bash
oc config current-context     # -> tailscale-operator
oc whoami                     # -> your identity
oc auth whoami                # -> your username + groups
```

Real output (verified by impersonating a tenant exactly the way the proxy does):

```text
$ oc whoami
alice@example.com

$ oc auth whoami
ATTRIBUTE   VALUE
Username    alice@example.com
Groups      [demo-tenant-operator system:authenticated]
```

Your username is your tailnet identity; your groups are your namespace's
`*-operator` group (which is what grants your access) plus `system:authenticated`.

Set your namespace as the default so you can drop `-n` from every command:

```bash
oc config set-context --current --namespace=<your-namespace>
```

> Don't use `oc project <ns>` — it tries to *read* the Project object first, which your
> role intentionally can't do, so it errors. `oc config set-context … --namespace` is a
> purely local change and always works.

A fresh namespace is empty:

```text
$ oc get pods
No resources found in demo-tenant namespace.
```

### B2. See your resource budget

```bash
oc get resourcequota tenant-quota
oc describe limitrange tenant-limits
```

```text
$ oc get resourcequota tenant-quota
NAME           REQUEST                                                                                 LIMIT
tenant-quota   configmaps: 2/30, persistentvolumeclaims: 0/5, pods: 0/20, requests.cpu: 0/1,
               requests.memory: 0/2Gi, requests.storage: 0/20Gi, secrets: 2/30, services: 0/10         limits.cpu: 0/2, limits.memory: 0/4Gi
```

Defaults are **1 cpu / 2 Gi of requests**, **2 cpu / 4 Gi of limits**, **20 pods**,
**5 PVCs**, **20 Gi storage**. Containers that don't set requests/limits inherit the
`LimitRange` defaults. Need more? See [Asking the admin](#asking-the-admin-for-changes).

### B3. Deploy an app

> **Important — Pod Security.** Your namespace enforces the **restricted** Pod Security
> Standard and OpenShift's `restricted-v2` SCC. Every pod must: run as **non‑root**,
> **not** hard‑code `runAsUser` (the cluster assigns one from your namespace's UID
> range), **drop ALL** capabilities, set `seccompProfile: RuntimeDefault`, and
> `allowPrivilegeEscalation: false`. The manifest below is compliant — copy its
> `securityContext` for your own workloads.

`deploy.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hello
  labels: { app: hello }
spec:
  replicas: 1
  selector: { matchLabels: { app: hello } }
  template:
    metadata: { labels: { app: hello } }
    spec:
      containers:
        - name: hello
          image: registry.access.redhat.com/ubi9/ubi-minimal
          command: ["/bin/sh", "-c", "while true; do echo \"hello at $(date '+%T')\"; sleep 30; done"]
          ports: [{ containerPort: 8080 }]
          securityContext:           # <-- required by this cluster's policy
            allowPrivilegeEscalation: false
            runAsNonRoot: true
            capabilities: { drop: ["ALL"] }
            seccompProfile: { type: RuntimeDefault }
```

```bash
oc apply -f deploy.yaml
oc rollout status deploy/hello
```

```text
$ oc apply -f deploy.yaml
deployment.apps/hello created

$ oc rollout status deploy/hello
Waiting for deployment "hello" rollout to finish: 0 of 1 updated replicas are available...
deployment "hello" successfully rolled out
```

### B4. Inspect, log, exec

```bash
oc get pods -o wide
oc logs deploy/hello -f          # Ctrl-C to stop following
oc exec deploy/hello -- id
oc describe pod -l app=hello
```

```text
$ oc get pods -o wide
NAME                     READY   STATUS    RESTARTS   AGE   IP            NODE                ...
hello-5f677c7cf6-wvfmc   1/1     Running   0          2s    10.130.2.55   hpg5.igou.systems   ...

$ oc exec deploy/hello -- id
uid=1001220000(1001220000) gid=0(root) groups=0(root),1001220000
```

Two things to notice, both expected:

- The pod is scheduled on **`hpg5`** (or `p330`) — your namespace is pinned to that
  worker pool. You can't land on the control‑plane or the on‑demand GPU "burst" node.
- The container runs as **`uid=1001220000`**, a non‑root UID the cluster assigned from
  your namespace's range — this is why you must not hard‑code `runAsUser`.

### B5. Reach your app

**Over the tailnet (recommended for remote access)** — port‑forward tunnels through the
same proxy; nothing is exposed publicly:

```bash
oc port-forward svc/hello 8080:8080
# then browse http://localhost:8080 on your machine
```

**As an OpenShift Route (for an HTTP app you want reachable on the cluster's domain):**

```bash
oc expose deploy/hello --port=8080                       # creates a Service
oc create route edge hello --service=hello --port=8080   # public-ish HTTPS route
oc get route hello -o jsonpath='{.spec.host}{"\n"}'
```

```text
$ oc get route hello -o jsonpath='{.spec.host}'
hello-demo-tenant.apps.ocp.igou.systems
```

(The example `hello` workload only prints to stdout, so a browser would get a 503 —
swap in a real HTTP server image to actually serve the route.)

### B6. Clean up

```bash
oc delete deploy,svc,route hello
```

---

## What you can and can't do

**You have full control inside your namespace** — deployments, statefulsets, daemonsets,
jobs/cronjobs, pods (incl. `logs`/`exec`/`port-forward`/`cp`), services, routes,
ingresses, configmaps, secrets, PVCs, HPAs, PodDisruptionBudgets, deploymentconfigs.

**By design you cannot:**

| Action | What you'll see |
|--------|-----------------|
| Touch another namespace or cluster‑scoped objects | `Error from server (Forbidden): nodes is forbidden: User "alice@example.com" cannot list resource "nodes" … at the cluster scope` |
| Edit your own NetworkPolicy / ResourceQuota / LimitRange (read‑only) | `Error from server (Forbidden): networkpolicies.networking.k8s.io "default-deny-all" is forbidden: User "alice@example.com" cannot patch resource "networkpolicies" … in the namespace "…"` |
| Create RBAC (Roles/RoleBindings) — i.e. grant yourself more | `Forbidden` |
| Create secondary networks (`NetworkAttachmentDefinition`, `UserDefinedNetwork`) | `Forbidden` (RBAC), or a ValidatingAdmissionPolicy denial |
| Schedule onto the control‑plane or the GPU "burst" node (toleration / nodeSelector / affinity for `workload=burst`) | `… ValidatingAdmissionPolicy 'remote-tenant-no-burst' … denied request: remote tenants may not tolerate the burst taint` |
| Exceed your quota | `Error from server (Forbidden): … exceeded quota: tenant-quota, requested: requests.cpu=2, … limited: requests.cpu=1` |

These denials are the lockdown working as intended — they're not bugs. Read your own
guardrails any time with `oc get networkpolicy`, `oc get resourcequota tenant-quota`,
`oc describe limitrange tenant-limits`.

**Egress:** your pods may reach the public internet (443/80), cluster DNS, and each
other — but **not** the LAN or other namespaces. To reach a specific internal host/port,
ask the admin to add an egress allowance to your tenant entry.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `oc` hangs, or `Unable to connect to the server: dial tcp: lookup tailscale-operator: no such host` | You're not on the tailnet. `tailscale up`, then `tailscale status`. The kubeconfig server only resolves over the tailnet. |
| `error: You must be logged in to the server (Unauthorized)` | Wrong context or your grant isn't active. `oc config use-context tailscale-operator`, then `oc whoami`. If `whoami` fails, ask the admin to confirm your ACL grant maps you to `impersonate.groups: ["<your-namespace>-operator"]`. |
| `Forbidden: … at the cluster scope` / `… in the namespace "X"` | Expected for anything outside your namespace or a guardrail. Add `-n <your-namespace>`; don't try other namespaces. |
| Pod won't start; events show `unable to validate against any security context constraint … runAsUser: Invalid value: 1000: must be in the ranges: [1001220000, …]` | Remove `runAsUser` from your spec (let the cluster assign it) and keep the rest of the `securityContext` from [B3](#b3-deploy-an-app). |
| `oc apply` of a Deployment succeeds but **no pods** appear | Same Pod Security cause as above, surfacing on the ReplicaSet. Check `oc describe rs -l app=…` / `oc get events`. |
| `exceeded quota: tenant-quota` | You hit your budget. Scale down, or request a bump. |
| You need session/audit recording of your kubectl commands | That's a tailnet‑side setting — ask the admin. |

---

## Asking the admin for changes

Some things are intentionally outside your control. Open a request to the administrator
for any of:

- a **new namespace** or a second environment,
- a **quota / limit** increase,
- an **extra egress** allowance (a specific internal host:port),
- a **different role** (e.g. read‑only `view`, or built‑in `edit`),
- **kubectl session recording** for your namespace,
- **off‑boarding** (removing your access).

The admin side of this — how namespaces, guardrails, and grants are created — lives in
[`.helm/charts/remote-tenant/README.md`](../../.helm/charts/remote-tenant/README.md) and
the design spec under `docs/superpowers/specs/`.

---

## Cheat sheet

```bash
# connect (your machine)
tailscale up
tailscale configure kubeconfig tailscale-operator

# orient
oc whoami                                  # who am I
oc auth whoami                             # my groups
oc config set-context --current --namespace=<your-namespace>

# work (inside your namespace)
oc get pods -o wide
oc apply -f deploy.yaml                    # restricted-v2-compliant pods only
oc rollout status deploy/<name>
oc logs -f deploy/<name>
oc exec deploy/<name> -- <cmd>
oc port-forward svc/<name> 8080:8080       # reach your app over the tailnet
oc expose deploy/<name> --port=8080 && oc create route edge <name> --service=<name>

# limits
oc get resourcequota tenant-quota
oc describe limitrange tenant-limits
oc get networkpolicy
```
