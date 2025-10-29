# Hello World Tekton Pipeline

## Overview

A simple Tekton pipeline that demonstrates:
- Hello and goodbye tasks in sequence
- Manual CLI execution
- Webhook-triggered execution via EventListener

## Prerequisites

- OpenShift Pipelines (Tekton) operator installed
- `tkn` CLI installed
- `oc` CLI configured with appropriate permissions
- Access to create resources in the namespace

## Components

- **Pipeline**: `hello-goodbye` - Runs hello and goodbye tasks in sequence
- **Tasks**: `hello-task` and `goodbye-task`
- **EventListener**: `hello-listener` - Webhook endpoint
- **TriggerBinding**: Extracts username from webhook payload
- **TriggerTemplate**: Creates PipelineRun from webhook
- **Route**: Exposes EventListener externally

## Pipeline Parameters

- `username` (string): Name to greet in the pipeline

## Create Objects

```bash
oc apply -k .
```

## Run Pipeline Manually via CLI

```bash
tkn pipeline start hello-goodbye -p username="Ran via cli"
```

## Run Pipeline via Event Listener (Webhook)

Get the EventListener URL and trigger the pipeline:

```bash
# Get the EventListener URL
EL_URL=$(oc get route el-hello-listener -o jsonpath='{.spec.host}')

# Trigger the pipeline
curl -v -H 'content-Type: application/json' \
  -d '{"username": "Tekton"}' \
  https://${EL_URL}
```

## View Pipeline Runs

**Via CLI:**

```bash
# List all pipeline runs
tkn pipelinerun list

# View logs of latest run
tkn pipelinerun logs -f

# View specific run
tkn pipelinerun logs <pipelinerun-name> -f

# Describe a specific run
tkn pipelinerun describe <pipelinerun-name>
```

**Via OpenShift Console:**
- Navigate to **Pipelines** → **PipelineRuns**

## Expected Output

The pipeline should:
1. Print "Hello World"
2. Print "Goodbye, \<username\>!"

```bash
$ tkn pipelinerun logs hello-goodbye-run-vqnpm
[hello : echo] Hello World

[goodbye : goodbye] Goodbye Ran via cli!
```

## Troubleshooting

**EventListener not accessible:**

```bash
# Check route
oc get route el-hello-listener

# Check EventListener pod
oc get pods -l eventlistener=hello-listener

# Check EventListener logs
oc logs -l eventlistener=hello-listener
```

**Pipeline fails:**

```bash
# Describe the pipeline run
tkn pipelinerun describe <pipelinerun-name>

# View logs
tkn pipelinerun logs <pipelinerun-name>

# Check task pods
oc get pods | grep hello-goodbye
```

**Webhook returns 404 or 500:**

```bash
# Check EventListener is ready
oc get eventlistener hello-listener

# Check TriggerBinding and TriggerTemplate
oc get triggerbinding,triggertemplate
```

## Cleanup

Remove all resources:

```bash
oc delete -k .
```

## Files

- `hello-goodbye-pipeline.yml` - Main pipeline definition
- `hello-task.yml`, `goodbye-task.yml` - Task definitions
- `hello-listener-eventlistener.yml` - Webhook listener
- `hello-binding-triggerbinding.yml` - Extract webhook data
- `hello-template-triggertemplate.yml` - Create PipelineRun
- `el-hello-listener-route.yml` - External route
- `kustomization.yaml` - Kustomize configuration
