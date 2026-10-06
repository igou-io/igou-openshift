# igou-openshift

Manifests and chart I use to configure my single-master Openshift cluster

Running on a minisforum MS-01

Can be deployed OKD or OCP, depending on what I'm working on

## Manifest file conventions

Authored static Kubernetes and OpenShift object manifests under `applications/`,
`components/`, `clusters/`, `groups/`, and `test-workloads/` contain exactly one
object per file and use `<metadata.name>-<kind-token>.yaml`. Object names are
lowercased for filenames and non-filename separators such as `:` become `-`.
Kind tokens are the lowercase Kubernetes kind, with `pv` and `pvc` as the
approved aliases for `PersistentVolume` and `PersistentVolumeClaim`.

The convention does not apply to non-object configuration such as
`kustomization.yaml`, Helm values, `Chart.yaml`, or application data. Vendored
chart content, Helm templates, and the templated files under
`test-workloads/windows-vms/examples/` are also excluded.
`make validate-manifest-files` is part of `make test` and CI.

## Validation

Use the existing devenv tools (`kustomize`, `helm`, and `kubeconform`) and install
the Python validation dependencies in a local environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
source .venv/bin/activate
make test
```

CI runs the same `make test` gate: YAML lint, Helm lint, manifest filenames,
Hermes proxy bypass, validation regression tests, and Kustomize builds with
schema validation. Each Kustomization is rendered once; its successful output
is passed to kubeconform. Temporary renders are removed after validation.
Kustomize Components are validated through their consuming Kustomizations.

For faster iteration, `make validate-kustomize` checks rendering only, while
`make validate-schemas` checks both rendering and schemas. Both cover dormant
workloads and test scenarios, exclude archived content and downloaded charts,
and fail immediately on a build error. Existing CRD schema exceptions remain
documented in the Makefile.

## Workload lifecycle and Helm values

See [the lifecycle inventory](docs/workload-lifecycle.md) for dormant workloads,
rollback deployments, and confirmed retirements. The app registry is the source
of truth for managed workloads; absence from it does not establish that live
resources or data have been removed.

Helm values should contain site overrides and explicit compatibility settings,
not a copied upstream values file. Keep image pins, security, resource sizing,
and storage choices visible. When trimming values, compare parsed rendered
objects at the same chart version before and after the change. Review the
upstream defaults again when updating a chart.
