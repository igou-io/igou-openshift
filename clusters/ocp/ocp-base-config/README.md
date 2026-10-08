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

Complete the first two steps **before merging the enabled login configurations**.
The root application deploys base config at wave 8 and Keycloak at wave 21;
wave ordering is not a substitute for provisioning the live client first.

1. In the existing Keycloak `igou` realm, provision the six confidential clients
   listed below using `components/rhbk/igou-keycloakrealmimport.yaml` as the
   exact client configuration. Enable Standard flow, disable Direct access
   grants and Service accounts, and include default scopes `profile` and `email`.
   For AAP, Shelfmark and Calibre-Web Automated, include the `groups` mapper
   with short group names emitted in ID tokens and userinfo. Store each generated
   secret in the concealed `client_secret` field of its listed 1Password item.
   Create realm client scope `groups` and attach it as an optional scope to
   `shelfmark`, which requests it automatically. Ensure Shelfmark has a local
   admin with a password through its Users settings before enabling OIDC.
   Do not change existing client secrets or user passwords.
2. Verify issuer discovery is reachable with trusted TLS:

   ```bash
   curl --fail --silent --show-error \
     https://keycloak.apps.ocp.igou.systems/realms/igou/.well-known/openid-configuration
   ```

3. Merge and sync `rhbk`, `ocp-base-config`, `forgejo`, `quay-operator` and
   `shelfmark`. The ExternalSecrets project the
   same item into `keycloak-openshift-secret` in `keycloak` for bootstrap imports
   and `openshift-keycloak` in `openshift-config` for OAuth. `clientSecret` is
   the required OAuth Secret key. The KeycloakRealmImport records the new client
   for recovery; it does **not** reconcile the existing realm. Never delete the
   realm to add clients. The application bootstrap bundle reads each application's
   item, and `keycloak-aap-secret` reads `lab_aap/aap-keycloak` through the
   existing `onepassword-lab-aap` store. Run the existing AAP config-as-code
   workflow after merging the companion inventory change, following
   `igou-inventory/docs/keycloak-aap-sso.md`. Activate CWA's database-backed
   OAuth settings through its admin UI, following
   `applications/calibre-web-automated/README.md`.
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
   Test Grafana, ArgoCD, Dev Spaces and RHACS too: each already uses OpenShift OAuth.
   CLI users use browser login, with `KUBECONFIG` set by their environment:

   ```bash
   oc login https://api.ocp.igou.systems:6443 --web
   oc whoami
   ```

   Browser OIDC supports the Keycloak session and MFA. Username/password CLI
   login is not enabled for the Keycloak client.

6. Link existing Forgejo accounts by proving their local credentials. In Quay,
   sign in locally and attach Keycloak through the existing account's settings
   before testing a fresh SSO session; check repository ownership and organization
   access. Verify AAP `igou` is an administrator and `dev1` retains sandbox-only
   access. Check Shelfmark's `admins` mapping and CWA's existing shelves and
   permissions. Retain application-local recovery login and machine credentials.

| Client ID | 1Password vault/item | Exact redirect URI(s) |
|-----------|----------------------|-----------------------|
| `openshift` | `lab_openshift/openshift-keycloak` | `https://oauth-openshift.apps.ocp.igou.systems/oauth2callback/keycloak` |
| `forgejo` | `lab_openshift/forgejo-keycloak` | `https://forgejo.apps.ocp.igou.systems/user/oauth2/keycloak/callback` |
| `quay` | `lab_openshift/quay-keycloak` | `https://quay.apps.ocp.igou.systems/oauth2/keycloak/callback`, `/callback/attach` and `/callback/cli` on the same `/oauth2/keycloak` path |
| `shelfmark` | `lab_openshift/shelfmark-keycloak` | `https://shelfmark.apps.ocp.igou.systems/api/auth/oidc/callback` |
| `aap` | `lab_aap/aap-keycloak` | `https://automation.apps.ocp.igou.systems/api/gateway/social/complete/keycloak/` |
| `calibre-web-automated` | `lab_openshift/calibre-web-automated-keycloak` | `https://calibre-web-automated.apps.ocp.igou.systems/login/generic/authorized` |

## Application coverage

| Service | Login path |
|---------|------------|
| OpenShift console and CLI | OpenShift OAuth → Keycloak |
| Grafana | Existing OpenShift OAuth proxy → Keycloak |
| ArgoCD | Existing Dex OpenShift connector → Keycloak |
| Dev Spaces | Existing OpenShift OAuth → Keycloak |
| RHACS | Existing OpenShift OAuth → Keycloak |
| RHDH and OpenShell | Existing direct Keycloak integration |
| Forgejo and Quay | Direct Keycloak clients; link existing accounts |
| Shelfmark | Direct Keycloak client; `admins` grants administrator |
| AAP, AAP portal and Automation Orchestrator | Gateway OIDC through inventory config-as-code; `admins` grants superuser |
| Calibre-Web Automated | Direct Keycloak client; activate OAuth through its admin UI |

Applications with their own login system do not inherit cluster authentication.
Other workloads retain their existing authentication. Adding third-party plugins
or an authentication gateway requires a separate integration. Browser SSO also
does not replace API tokens, registry robot credentials, or Git SSH keys.

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
