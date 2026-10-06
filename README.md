# igou-openshift

GitOps manifests and Helm charts for my OpenShift cluster. ArgoCD manages the
cluster from [`clusters/ocp/`](clusters/ocp/), with a single control-plane node on
a Minisforum MS-01 and additional workers.

## Repository

- [`applications/`](applications/) — user applications.
- [`components/`](components/) — reusable platform components and operators.
- [`clusters/ocp/`](clusters/ocp/) — cluster configuration and application registry.
- [`groups/`](groups/) — component groups.
- [`.helm/charts/`](.helm/charts/) — local Helm charts.
- [`test-workloads/`](test-workloads/) — networking and VM test scenarios.
- [`inactive/`](inactive/README.md) — unused workloads kept for future reuse.

## Contributing

Follow [CODE_STANDARDS.md](CODE_STANDARDS.md) and run `make test` before pushing.
It covers lint, manifest naming, lifecycle checks, rendering, and schema validation.
[AGENTS.md](AGENTS.md) provides instructions for coding agents.

## Documentation

Shared runbooks and architecture notes live in
[igou-docs](https://github.com/igou-io/igou-docs/blob/main/Home.md).
Component and application READMEs stay beside their manifests.
