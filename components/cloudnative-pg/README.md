# CloudNativePG operator

The `stable-v1` Subscription installs the certified CloudNativePG OLM bundle.
Cluster-specific namespace, network policies, and Barman plugin wiring live in
`clusters/ocp/cloudnative-pg/`.

## Public-image pull secret

The upstream CSV hardcodes `cnpg-pull-secret` in the controller Deployment's
`imagePullSecrets` (confirmed in `cloudnative-pg.v1.30.1`). The controller image
is public on `ghcr.io/cloudnative-pg/cloudnative-pg`. The Subscription API does
not support an `imagePullSecrets` override, and patching the generated
Deployment would be reverted by OLM.

`cnpg-pull-secret-secret.yaml` provides an empty Docker registry configuration,
`{"auths":{}}`. It contains no credentials and grants no registry access. Public
image pulls continue to use anonymous access or the node's existing credentials.
This satisfies the upstream bundle's reference and prevents
`FailedToRetrieveImagePullSecret` without replacing OLM or patching each CSV
version. It is created at sync wave -1, before the Subscription.

CNPG can copy the operator's pull secret into database namespaces. An empty
configuration does not add private-registry credentials to database pods. If a
private registry becomes necessary, replace this credential-free manifest with
an ExternalSecret backed by 1Password; never add credentials here.

This resolves issue #406's missing-secret warning through a supported resource
rather than its initially proposed reference removal. Removing the hardcoded
reference requires an upstream bundle change or a separately planned migration
away from OLM.

After rollout, confirm the operator and database clusters remain healthy and
that new `FailedToRetrieveImagePullSecret` events stop. Do not retrieve Secret
data for verification.
