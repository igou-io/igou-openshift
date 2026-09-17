# IT Tools

[IT Tools](https://github.com/sharevb/it-tools) is a collection of browser-based
utilities for common developer and operations tasks. It is deployed as the
upstream static frontend at:

https://it-tools.apps.ocp.igou.systems

## Deployment

- Upstream repository: https://github.com/sharevb/it-tools
- Image source: `ghcr.io/sharevb/it-tools`
- Pinned stable version: `2026.7.11`
- Pinned manifest digest: `sha256:5d79e8c7fbf39d6473c282b9c4f86ff85c4900ec22ef766ae3c6f0f9ca8dbb37`
- Container port: `8080/TCP`
- Service: `80/TCP` to container port `8080`
- Ingress: edge-TLS at `it-tools.apps.ocp.igou.systems`

IT Tools is stateless and has no PVC, database, credentials, or companion
service. The core frontend is intentionally deployed without authentication;
authentication, if needed later, is a separate concern. Optional upstream
companion services for network helpers, document conversion, downloads, and
similar features are not deployed.

The Deployment is intended to run under the normal OpenShift `restricted-v2`
SCC with an OpenShift-assigned arbitrary UID. It does not set a fixed UID,
privileged mode, host namespaces, or added capabilities. Service-account token
automount is disabled because the workload has no Kubernetes API access.

## Network policy

All pod ingress and egress is denied by default. The only ingress exception is
TCP/8080 from the OpenShift router's host-network namespace. There is no pod
runtime egress allow policy. Requests made directly by browser-based tools are
browser egress, not pod egress, so the core frontend does not need network access
from its namespace.

## Updating the image

Select a newer stable, non-prerelease upstream tag and resolve its manifest
digest with registry tooling, for example:

```bash
skopeo inspect docker://ghcr.io/sharevb/it-tools:<tag> | jq -r .Digest
```

Update the `tag` value in `kustomization.yaml` to keep the tag and digest in
Renovate-compatible `tag@sha256:<digest>` form. Do not use `latest` or a
locally maintained derivative image.

## Local validation

Render the application with Helm support enabled and run the repository gate:

```bash
kustomize build --enable-helm applications/it-tools
make test
```

Inspect the rendered Deployment, Service, Ingress, and NetworkPolicies rather
than relying only on command exit status.

## Post-merge live verification

These checks require the Git change to be merged and reconciled; they have not
been performed by the Git-side implementation:

1. Confirm the ArgoCD Application is `Synced` and `Healthy`.
2. Confirm the pod is admitted by normal `restricted-v2`, without custom or
   `anyuid` SCC access, and has an OpenShift-assigned runtime UID.
3. Confirm no service-account token is mounted.
4. Confirm nginx listens on `8080` and Service forwarding works.
5. Confirm `https://it-tools.apps.ocp.igou.systems` loads and HTTP redirects to
   HTTPS.
6. Confirm refreshing a deep SPA route does not return an nginx 404.
7. Exercise UUID generation, JSON formatting, hashing, and encoding.
8. Check the browser console for asset-loading or COOP/COEP failures.
9. Confirm unrelated namespaces cannot reach the pod directly while router
   ingress works.
10. Confirm pod egress remains denied and the core frontend still functions.
11. Recreate the pod and confirm no required state is lost.
12. Test `readOnlyRootFilesystem: true`. Retain it only if the exact pinned
    image works with the minimum required writable `emptyDir` paths; otherwise
    document the exact runtime write requirement before leaving the baseline
    root filesystem writable.
