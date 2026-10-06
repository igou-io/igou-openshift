# Code standards

Keep changes small and follow the existing component or application layout.
These standards apply to authored files throughout the repository, including
inactive workloads and test scenarios.

## YAML and manifest files

- Use block-style YAML collections. Inline `{}` and `[]` are allowed only when empty.
- Put exactly one Kubernetes or OpenShift object in each static manifest file.
- Name object files `<metadata.name>-<kind-token>.yaml`. Lowercase the object name
  and replace separators such as `:` with `-`. Use the lowercase Kind as the token;
  `pv` and `pvc` are the approved aliases for `PersistentVolume` and
  `PersistentVolumeClaim`.
- Update the nearest `kustomization.yaml` when adding or moving manifests.

Object naming applies under `applications/`, `components/`, `clusters/`, `groups/`,
`test-workloads/`, and `inactive/`. Non-object configuration (Kustomizations, Helm
values, chart metadata, and application data), vendored charts, Helm templates,
and `test-workloads/windows-vms/examples/` templated files are excluded.

## GitOps and workload lifecycle

- Register managed workloads in `clusters/ocp/values.yaml`. Set the Application
  source, namespace, sync wave, and controller-owned `ignoreDifferences` deliberately.
- Preserve fields owned by controllers and existing `ignoreDifferences` rules.
- Order dependencies with `argocd.argoproj.io/sync-wave`. Existing manifests also
  use `SkipDryRunOnMissingResource=true` and `ServerSideApply=true` sync options.
  The app-of-apps defaults enable auto-sync, disable auto-prune, and retry indefinitely
  with backoff.
- Keep reusable dormant workloads under `inactive/applications/` or
  `inactive/components/`. Move them back before registering them. Registered
  rollback workloads stay in their existing paths.
- Active Applications and Kustomizations must not reference `inactive/`.
- Reference every authored object manifest from a Kustomization or a local
  Application directory source. Intentionally manual objects need an exact path
  and reason in `scripts/lifecycle-exceptions.yaml`; stale exceptions fail validation.
- Removing an Application entry or source file does not establish that live
  resources or data have been deleted. Record lifecycle decisions in the
  [lifecycle inventory](https://github.com/igou-io/igou-docs/blob/main/reference/igou-openshift%20Workload%20Lifecycle%20and%20Cleanup.md).

Validation follows rendered local Application sources from each `clusters/<name>`
root and their Kustomize dependencies. It rejects missing paths, active references
into `inactive/`, unregistered top-level application/component Kustomizations,
and orphaned objects. Applications in other repositories are outside the local
source-path check. Inactive workloads remain covered by validation and Renovate.

## Helm values, images, and secrets

- Keep site overrides and explicit compatibility settings in Helm values. Keep
  image pins, security settings, resource sizing, and storage choices visible.
  Avoid copying upstream defaults.
- When trimming values, compare parsed rendered objects before and after at the
  same chart version. Review upstream defaults again when updating a chart.
- Pin container images to digests where supported. Preserve existing pins and
  compatibility freezes unless an update has been reviewed.
- Use External Secrets Operator and 1Password references for credentials. Never
  commit secrets, private keys, tokens, or kubeconfig contents.
- Keep always-on components pinned to the control plane where configured. For
  workloads with worker preference, use preferred node affinity excluding
  `node-role.kubernetes.io/control-plane`; the control plane also has the `worker`
  label. This allows fallback to the control plane when workers are unavailable.
  GitOps and RHACS do not expose this affinity setting. Preserve existing placement
  and tolerations when changing chart values.

Kustomizations use `helmCharts`. Render them with `kustomize build --enable-helm`;
`oc apply -k` does not enable Helm rendering. Deploy through GitOps unless direct
application is explicitly authorized.

## Validation

Use the devenv tools `kustomize`, `helm`, and `kubeconform`. Install Python
validation dependencies in a local environment:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
source .venv/bin/activate
make test
```

Run `make test` before pushing. CI uses the same gate: YAML lint, Helm lint,
manifest filenames, Hermes proxy bypass, validation regression tests, lifecycle,
and Kustomize builds with schema validation. Each Kustomization is rendered once;
temporary output is passed to kubeconform and removed afterward. Components are
validated through their consuming Kustomizations.

For focused checks, use `make validate-manifest-files`,
`make validate-kustomize` (rendering and lifecycle), or `make validate-schemas`
(also schemas). Inactive workloads and test scenarios remain included; downloaded
charts are excluded. Build failures stop validation immediately. Kubeconform uses
strict validation for available schemas and skips missing schemas; there are no
explicit kind exclusions.

## Reviewing dependency updates

- Patch/minor chart or image updates can merge after CI passes and rendered
  changes have been reviewed for compatibility.
- Docker major updates require manual review of upstream release notes,
  configuration, probes, security, CRDs, and storage behavior.
- Major Helm chart updates require review of the changelog and values schema.
  Passing CI proves rendering and schema validity, not runtime compatibility.
- Review digest-only updates for stateful, privileged, GPU, storage, and
  networking workloads.
- Keep unrelated dependency changes separate; prefer one component or application per PR.
- For operator, CRD, CNI, storage, MachineConfig, or Cluster API updates, verify
  dependency ordering and CRD compatibility before merging.
- A local `make test` failure blocks merging unless a documented tooling or
  environment difference explains it.

## Documentation

Update the relevant page in [igou-docs](https://github.com/igou-io/igou-docs/blob/main/Home.md)
after changes. Keep component/application READMEs beside their manifests. Shared
runbooks, examples, incident reports, and historical designs belong in the vault.
