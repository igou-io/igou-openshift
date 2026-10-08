# Forgejo login

Forgejo uses the Keycloak `igou` realm through the Helm chart's `gitea.oauth`
configuration. The chart creates or updates the `keycloak` authentication source
at startup, with confidential client `forgejo` and callback:

```text
https://forgejo.apps.ocp.igou.systems/user/oauth2/keycloak/callback
```

`forgejo-keycloak` ExternalSecret reads `client_secret` from the same-named
1Password item in `lab_openshift`. It produces the chart's required `key` and
`secret` keys. Create the live Keycloak client and item before deploying.

`ACCOUNT_LINKING: login` requires proving access to an existing local account
before linking it. Sign in using Keycloak and link the existing `igou` or `dev1`
account using its current local credentials. Repository ownership, organization
membership, API tokens and SSH keys then stay with that account. Automatic OAuth
registration is disabled: this integration signs in the existing accounts.

The local login form remains available. Git SSH keys and Forgejo API tokens are
still used for Git and automation; browser SSO does not replace those credentials.

Chart version `17.1.6` supports `gitea.oauth.existingSecret` and reconciles auth
sources from its configure script. See the
[Forgejo configuration reference](https://forgejo.org/docs/latest/admin/config-cheat-sheet/#oauth2-client-oauth2_client)
for account-linking behavior and `clusters/ocp/ocp-base-config/README.md` for the
shared rollout sequence.
