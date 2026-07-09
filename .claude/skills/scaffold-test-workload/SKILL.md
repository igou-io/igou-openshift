---
name: scaffold-test-workload
description: Scaffold a new test workload under test-workloads/ with namespace, NetworkAttachmentDefinition, pod or deployment, and optionally Service/Route. Supports macvlan, ipvlan, OVN-K localnet CNI types and static/DHCP/whereabouts/OVN IPAM modes.
argument-hint: <workload-name>
allowed-tools: Read, Write, Bash(kustomize build *), Bash(ls *), Bash(cat *)
---

# Scaffold a new test workload

Scaffold a new test workload under `test-workloads/` following the exact conventions of this repo.

## Workload name

The workload to scaffold is: **$ARGUMENTS**

If `$ARGUMENTS` is empty, ask the user for the workload name before proceeding.

## Information to gather

Before generating any files, collect the following. If the user provided details inline, proceed directly. Otherwise ask in a single message — do not ask one question at a time.

| Field | Description | Default |
|-------|-------------|---------|
| `workload-name` | Directory name under `test-workloads/` | from `$ARGUMENTS` |
| `namespace` | Kubernetes namespace | same as `workload-name` |
| `cni-type` | CNI plugin: `macvlan`, `ipvlan-l2`, `ipvlan-l3`, `ovn-k-localnet`, `bridge` | `macvlan` |
| `ipam-type` | IPAM mode: `static`, `dhcp`, `whereabouts`, `ovn` (OVN-K only), `none` | `static` |
| `master-interface` | Host interface for macvlan/ipvlan NADs | `enp2s0f1.45` |
| `vlan-id` | VLAN ID (for OVN-K localnet NADs) | `45` |
| `nad-name` | NetworkAttachmentDefinition name | auto-generated from cni-type + network details |
| `workload-type` | `pod` (sleep infinity debug pod) or `deployment` (nginx with Service/Route) | `pod` |
| `static-ip` | Static IP with CIDR (only if ipam-type=static) | — (required if static) |
| `static-mac` | Static MAC address (optional, only if ipam-type=static) | — |
| `static-gateway` | Gateway IP (only if ipam-type=static) | `10.10.45.1` |
| `whereabouts-range` | IP range with CIDR (only if ipam-type=whereabouts) | — (required if whereabouts) |
| `whereabouts-gateway` | Gateway IP (only if ipam-type=whereabouts) | `10.10.45.1` |
| `include-route` | Include Service and Route (only if workload-type=deployment) | `yes` |

## File generation

Create directory `test-workloads/<workload-name>/` and generate the files below.

### Conventions (apply to every file)
- 2-space indentation
- YAML 1.2 booleans: `true`/`false` only
- No `---` prefix on kustomization.yaml (kustomize convention)
- All other YAML files do NOT need `---` prefix (test-workloads convention — match existing workloads)
- Pods and containers must have restricted security context (seccompProfile RuntimeDefault, allowPrivilegeEscalation false, runAsNonRoot true, drop ALL capabilities)

### 1. `namespace.yaml`

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: <namespace>
```

### 2. `nad-vlan45.yaml` (or `nad.yaml` if no VLAN involved)

Generate based on `cni-type` and `ipam-type`:

#### macvlan with static IPAM:
```yaml
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: <nad-name>
  namespace: <namespace>
spec:
  config: |
    {
      "cniVersion": "0.3.1",
      "name": "<nad-name>",
      "type": "macvlan",
      "master": "<master-interface>",
      "linkInContainer": false,
      "mode": "bridge",
      "ipam": {
        "type": "static",
        "routes": [
          {
            "dst": "0.0.0.0/0",
            "gw": "<static-gateway>"
          }
        ]
      }
    }
```

#### macvlan with DHCP:
```yaml
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: <nad-name>
  namespace: <namespace>
spec:
  config: |
    {
      "cniVersion": "0.3.1",
      "name": "<nad-name>",
      "type": "macvlan",
      "master": "<master-interface>",
      "linkInContainer": false,
      "mode": "bridge",
      "ipam": {
        "type": "dhcp"
      }
    }
```

#### macvlan with whereabouts:
```yaml
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: <nad-name>
  namespace: <namespace>
spec:
  config: |
    {
      "cniVersion": "0.3.1",
      "name": "<nad-name>",
      "type": "macvlan",
      "master": "<master-interface>",
      "linkInContainer": false,
      "mode": "bridge",
      "ipam": {
        "type": "whereabouts",
        "range": "<whereabouts-range>",
        "gateway": "<whereabouts-gateway>",
        "routes": [
          {
            "dst": "0.0.0.0/0",
            "gw": "<whereabouts-gateway>"
          }
        ]
      }
    }
```

#### ipvlan-l2 or ipvlan-l3:
Same structure as macvlan but with `"type": "ipvlan"` and `"mode": "l2"` or `"mode": "l3"`. No `"linkInContainer"` field.

#### ovn-k-localnet:
```yaml
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: <nad-name>
  namespace: <namespace>
spec:
  config: |
    {
      "cniVersion": "0.3.1",
      "name": "trunk-network",
      "type": "ovn-k8s-cni-overlay",
      "topology": "localnet",
      "netAttachDefName": "<namespace>/<nad-name>",
      "vlanID": <vlan-id>
    }
```

Note: OVN-K localnet NADs do NOT include IPAM in the NAD config — IPs are assigned via pod annotations.

### 3. `pod.yaml` (if workload-type=pod)

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: <workload-name>-test
  namespace: <namespace>
  annotations:
    k8s.v1.cni.cncf.io/networks: |-
      [
        {
          "name": "<nad-name>"<static-ip-and-mac-fields>
        }
      ]
spec:
  securityContext:
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: tools
      image: registry.redhat.io/openshift4/ose-tools-rhel9:latest
      command: ["sleep", "infinity"]
      securityContext:
        allowPrivilegeEscalation: false
        runAsNonRoot: true
        capabilities:
          drop:
            - ALL
```

For static IPAM, include `"ips": ["<static-ip>"]` in the network annotation. If `static-mac` is set, also include `"mac": "<static-mac>"`.

For DHCP/whereabouts/OVN, the network annotation only needs `"name"`.

### 4. `deployment.yaml` (if workload-type=deployment)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
  namespace: <namespace>
  labels:
    app: nginx
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
      annotations:
        k8s.v1.cni.cncf.io/networks: |-
          [
            {
              "name": "<nad-name>"<static-ip-and-mac-fields>
            }
          ]
    spec:
      securityContext:
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: nginx
          image: quay.io/hummingbird/nginx:1.28.2@sha256:abafaf282a8b910057ad5963f4ffb84866f55e3f794ecb3e8816f15c6a9c0cbe
          ports:
            - containerPort: 8080
          securityContext:
            allowPrivilegeEscalation: false
            runAsNonRoot: true
            capabilities:
              drop:
                - ALL
```

### 5. `service.yaml` (only if workload-type=deployment and include-route=yes)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx
  labels:
    app: nginx
spec:
  selector:
    app: nginx
  ports:
    - port: 80
      targetPort: 8080
      protocol: TCP
```

### 6. `route.yaml` (only if workload-type=deployment and include-route=yes)

```yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: nginx
  labels:
    app: nginx
spec:
  to:
    kind: Service
    name: nginx
  port:
    targetPort: 8080
  tls:
    termination: edge
```

### 7. `kustomization.yaml`

List resources in creation order: namespace, NAD, pod/deployment, then service and route if present.

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: <namespace>
resources:
  - namespace.yaml
  - nad-vlan45.yaml  # or nad.yaml
  - pod.yaml  # or deployment.yaml
  # - service.yaml  (if generated)
  # - route.yaml    (if generated)
```

## Validation

After writing all files, run:
```bash
kustomize build test-workloads/<workload-name>/
```

If kustomize build fails, diagnose and fix the issue before reporting completion.

## Completion report

After successful validation, report:
1. Files created (list with paths)
2. Kustomize build result (pass or error details)
3. How to apply: `oc apply -k test-workloads/<workload-name>/`
4. How to verify: `oc get pods -n <namespace>` and check network annotations
