---
name: inspect
description: Inspect a Kubernetes namespace using MCP tools to show pod status, network interfaces, events, and resources
argument-hint: <namespace>
allowed-tools: mcp__kubernetes__pods_list_in_namespace, mcp__kubernetes__pods_get, mcp__kubernetes__pods_log, mcp__kubernetes__events_list, mcp__kubernetes__resources_list, mcp__kubernetes__resources_get
---

Inspect the Kubernetes namespace "$ARGUMENTS" using MCP tools. Follow these steps:

1. List all pods in the namespace using `mcp__kubernetes__pods_list_in_namespace`
2. List events in the namespace using `mcp__kubernetes__events_list` (filtered to the namespace)
3. For each pod found, use `mcp__kubernetes__pods_get` to retrieve full pod details — pay attention to:
   - Status and conditions (Ready, ContainersReady, any failures)
   - Container restart counts and state (running, waiting, terminated)
   - Network annotations (`k8s.v1.cni.cncf.io/network-status`) for secondary interface IPs
   - Resource requests/limits (GPU, memory, CPU)
   - Volume mounts and PVC references
4. List key resources in the namespace using `mcp__kubernetes__resources_list`:
   - `apps/v1 Deployment`
   - `v1 Service`
   - `k8s.cni.cncf.io/v1 NetworkAttachmentDefinition`
   - `v1 PersistentVolumeClaim`

Summarize findings in a concise report:
- Pod status (running/pending/error, restarts, age)
- Network interfaces and IPs (primary + any secondary)
- Any warnings or errors from events
- Resource allocation (GPU, storage)
- Issues or anomalies that need attention
