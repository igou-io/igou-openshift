# OpenShift authentication

OpenShift delegates browser login to the Keycloak `igou` realm using the
confidential `openshift` client. The provider is named `keycloak` and its only
redirect URI is:

```text
https://oauth-openshift.apps.ocp.igou.systems/oauth2callback/keycloak
```

The existing `igou` htpasswd provider remains available for recovery. Keycloak
uses `mappingMethod: add` and `preferred_username`, so existing `igou` and `dev1`
users keep their RBAC and Dev Spaces workspaces. Keycloak username assignment is
therefore trusted to identify existing OpenShift users, including administrators.
Keep realm self-registration disabled and username administration restricted.
OpenShift RBAC remains managed by GitOps; this provider does not sync realm groups.

## Initial rollout

Complete the first two steps **before merging the enabled OAuth configuration**.
The root application deploys base config at wave 8 and Keycloak at wave 21;
wave ordering is not a substitute for provisioning the live client first.

1. In the existing Keycloak `igou` realm, create confidential OIDC client
   `openshift` with Standard flow enabled, Direct access grants and Service
   accounts disabled, and the exact redirect URI above. Include default scopes
   `profile` and `email`. Store its generated secret in the concealed
   `client_secret` field of 1Password item `lab_openshift/openshift-keycloak`.
   Do not change existing client secrets or user passwords.
2. Verify issuer discovery is reachable with trusted TLS:

   ```bash
   curl --fail --silent --show-error \
     https://keycloak.apps.ocp.igou.systems/realms/igou/.well-known/openid-configuration
   ```

3. Merge and sync `rhbk` and `ocp-base-config`. The ExternalSecrets project the
   same item into `keycloak-openshift-secret` in `keycloak` for bootstrap imports
   and `openshift-keycloak` in `openshift-config` for OAuth. `clientSecret` is
   the required OAuth Secret key. The KeycloakRealmImport records the new client
   for recovery; it does **not** reconcile the existing realm. Never delete the
   realm to add this client.
4. With the authorized credential profile activated, verify identity and health:

   ```bash
   oc whoami --show-server
   oc whoami
   oc get externalsecret openshift-keycloak -n openshift-config
   oc get externalsecret keycloak-openshift-secret -n keycloak
   oc get clusteroperator authentication
   oc get oauth cluster -o yaml
   ```

5. Choose `keycloak` on the OpenShift login page and sign in as `igou`, then
   `dev1`. Check that each reaches their existing account and intended permissions.
   Test Grafana, ArgoCD and Dev Spaces too: each already uses OpenShift OAuth.
   CLI users use browser login, with `KUBECONFIG` set by their environment:

   ```bash
   oc login https://api.ocp.igou.systems:6443 --web
   oc whoami
   ```

   Browser OIDC supports the Keycloak session and MFA. Username/password CLI
   login is not enabled for the Keycloak client.

## Application coverage

| Service | Login path |
|---------|------------|
| OpenShift console and CLI | OpenShift OAuth → Keycloak |
| Grafana | Existing OpenShift OAuth proxy → Keycloak |
| ArgoCD | Existing Dex OpenShift connector → Keycloak |
| Dev Spaces | Existing OpenShift OAuth → Keycloak |
| RHDH and OpenShell | Existing direct Keycloak integration |
| AAP, Forgejo, Quay and other applications | Separate integration required |

Adding the cluster provider does not automatically change applications with
their own login system. Use a separate Keycloak client and secret for each
application when integrating it; retain each application's existing authorization.

## Recovery and rotation

If Keycloak login fails, select the existing `igou` htpasswd provider. To withdraw
the new provider, set `auth.openID.enabled: false` in this directory's values and
sync `ocp-base-config`; existing RBAC and htpasswd remain in place.

For rotation, update the **live** `openshift` client and the same 1Password item's
`client_secret` together, then verify the ExternalSecrets and authentication
operator reconcile. Editing the import manifest alone will not rotate a client.

OpenShift OIDC and mapping behavior are documented in the
[OpenShift source documentation](https://github.com/openshift/openshift-docs/blob/enterprise-4.21/modules/identity-provider-oidc-CR.adoc)
and [identity mapping reference](https://github.com/openshift/openshift-docs/blob/enterprise-4.21/modules/identity-provider-parameters.adoc).
