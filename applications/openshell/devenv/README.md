# Devenv sandboxes with GLM Flash

This image adds OpenShell policy and a local model adapter to the pinned
`igou-devenv` image. It includes Codex and Claude Code. Set the gateway chart's
`server.sandboxImage` to its published digest; keep the gateway server image
on the matching NVIDIA release. Existing sandboxes and callers that specify
their own image are unaffected, including Omnigent's managed host image.

## Build and publish

Run from the igou-openshift root with registry credentials activated:

```bash
use local-quay
podman build -t quay.apps.ocp.igou.systems/igou-io/openshell-devenv:20260924-glm \
  applications/openshell/devenv
podman push quay.apps.ocp.igou.systems/igou-io/openshell-devenv:20260924-glm
skopeo inspect --format '{{.Digest}}' \
  docker://quay.apps.ocp.igou.systems/igou-io/openshell-devenv:20260924-glm
```

Update `server.sandboxImage` in the parent kustomization with that digest,
validate with `make test`, and deploy through the `openshell` ArgoCD application.
The gateway's existing `quay-local-pull` pull secret covers this registry.

## Configure the provider

The `opencode-go-devenv` provider belongs to the `default` workspace. It grants
the adapter's Python executable access to `opencode.ai:443`. The gateway
stores the OpenCode Go key encrypted; the image contains no credentials.

From a credentialed workstation, bootstrap or rotate the provider:

```bash
uv venv .venv-openshell
uv pip install --python .venv-openshell/bin/python openshell==0.0.116 PyYAML
.venv-openshell/bin/python applications/openshell/devenv/bootstrap-provider.py
```

The script uses the existing `swarmer-openshell` Keycloak administrator client
and reads `op://lab_agents/opencode-go-subscription-key/password` into memory.
It imports the versioned profile and creates or updates the workspace provider.
Re-run it after restoring the gateway database or rotating the key. Other
workspaces need their own provider instance and appropriate membership.

## Run agents

Authenticate to the configured `ocp` gateway, then create a sandbox with the
provider attached:

```bash
openshell --gateway ocp sandbox create --name devenv-glm \
  --provider opencode-go-devenv -- sleep infinity
openshell --gateway ocp sandbox exec --name devenv-glm -- \
  codex-glm exec --skip-git-repo-check --sandbox danger-full-access \
  'Create a Python function and run a test for it in /sandbox.'
openshell --gateway ocp sandbox exec --name devenv-glm -- \
  claude-glm --print --permission-mode bypassPermissions \
  'Review the Python function in /sandbox and run its test.'
openshell --gateway ocp sandbox delete devenv-glm
```

These flags allow unattended client tool use inside the outer OpenShell sandbox.
The writable project/home directory is `/sandbox`; `/home/igou` supplies the
read-only devenv tools. Outbound access remains governed by OpenShell. Git
remotes, package registries, and cluster APIs need separate policy and credentials.

Both wrappers select `glm-5.3-flash` and start an ephemeral LiteLLM listener
on loopback. OpenCode Go serves this model through Chat Completions; Codex
requires Responses and Claude Code requires Messages. The adapter translates
these protocols and exits with the client. Codex web search and unsupported
reasoning parameters are disabled. A successful chat response alone does not
verify file editing or command execution; test those after changing the image,
model, provider profile, or adapter version.

Direct `codex` and `claude` commands retain their normal configuration. Use
`codex-glm` and `claude-glm` for this provider and model.
