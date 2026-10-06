# GitOps repository cleanup

Goal: make validation consistent, document workload lifecycle, and reduce copied
Helm values without changing rendered resources.

1. Align `Makefile` and `.github/workflows/validate.yml`; add manifest naming and
   regression checks, and render each Kustomization once during schema validation.
2. Audit the current `clusters/ocp` dependency graph and document managed,
   rollback, and dormant workloads in `docs/workload-lifecycle.md`. Archive only
   confirmed retirements; removal from the app registry alone is not evidence.
3. Trim upstream defaults in External Secrets, Minecraft, and Ollama. Compare
   parsed renders at the pinned chart versions before and after each change.
4. Update repository guidance and the igou-docs architecture reference, run
   `make test`, inspect the diff, and open a draft pull request.

Constraints: preserve existing checkout edits with an isolated worktree; retain
image pins, security/storage behavior, sync waves, and controller-owned fields.
Use block-style YAML. No live cluster changes are part of this cleanup.
