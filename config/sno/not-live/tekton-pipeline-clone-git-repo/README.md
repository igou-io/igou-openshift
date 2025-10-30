This directory contains a minimal Tekton example that clones a Git repo and prints the README.

Objects:
- Namespace: `tekton-pipeline-clone-git-repo-namespace.yml`
- Task: `show-readme-task.yml` (prints README.md from the cloned repo)
- Pipeline: `clone-read-pipeline.yml` (uses `git-clone` task and `show-readme` task)
- TriggerBinding: `clone-read-triggerbinding.yml` (expects `git-url` and `git-revision`)
- TriggerTemplate: `clone-read-triggertemplate.yml` (creates a `PipelineRun` for the pipeline)
- EventListener: `clone-read-eventlistener.yml` (wires the binding and template)
- Route: `el-clone-read-route.yml` (exposes the EventListener service externally)
- External Task reference: `git-clone` from Tekton Catalog (pinned in `kustomization.yaml`)

Example curl to trigger the EventListener:

```
curl -v \
  -H 'Content-Type: application/json' \
  -d '{
        "git-url": "https://github.com/igou-io/igou-openshift.git"
      }' \
  https://el-clone-read-tekton-pipeline-clone-git-repo.apps.sno.igou.systems
```