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
`test-workloads/windows-vms/examples/` are also excluded. Run
`make validate-manifest-files` to check the convention.
