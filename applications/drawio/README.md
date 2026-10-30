# draw.io

Self-hosted draw.io editor, deployed as the `drawio` ArgoCD Application in
namespace `drawio`: <https://drawio.apps.ocp.igou.systems>.

Agents create and edit native `.drawio` XML files directly in the repository
that owns the diagram. Open those files in the editor for visual review. Use
the official [generation reference](https://www.drawio.com/docs/reference/diagram-generation/)
for XML structure, styles, validation, and links that open diagrams in the editor.
No MCP server or client configuration is required.

The editor is stateless; save files in the owning repository or download them
from the browser. There is no shared document store or PVC.

GitHub storage uses the dedicated `david-igou-drawio` GitHub App, installed for
the private `david-igou/drawio-diagrams` repository. Open
<https://drawio.apps.ocp.igou.systems/?mode=github>, authorize as `david-igou`,
then choose the repository, branch and diagram path. Changes are GitHub commits;
agents pull and push the same branch between editing turns. This does not expose
an agent's uncommitted working files or provide live collaborative editing.

`lab_openshift/drawio-github` supplies `client_id` and `client_secret` through
the `drawio-github` ExternalSecret. Only the editor container mounts the files
in `WEB-INF`; the client secret is never included in browser configuration.
The callback is `https://drawio.apps.ocp.igou.systems/github2` and needs only
browser access from the LAN/VPN. Webhooks are disabled.

The pinned image disables GitHub in its generated `PreConfig.js`.
`github-storage.sh` runs after the upstream entrypoint to enable it, set the
public client ID and replace the bundled installation links with
`DRAWIO_GITHUB_APP_URL`. After credential rotation, restart the editor through
the normal rollout workflow because the files use Secret subPath mounts.

The editor is protected by oauth2-proxy using the existing Keycloak `igou` realm.
The confidential `drawio` client requires its `access` role, assigned to the
`igou` and `agents` users. Other realm users do not get editor access. Browser
login uses authorization code flow with PKCE; password grants and service
accounts are disabled for this client. Local file authoring needs no login.

The client and cookie secrets come from `lab_openshift/drawio-keycloak` through
External Secrets. `components/rhbk/igou-keycloakrealmimport.yaml` records the
client, role and assignments for bootstrap; its one-shot import does not update
an existing realm. Live client/role changes must also be made through Keycloak
administration and kept aligned with that record.

Both images are digest-pinned and run under OpenShift's `restricted-v2` SCC
without service-account tokens. The public Service targets the auth proxy on
port 4180; only the proxy reaches the editor on loopback port 8080.
NetworkPolicy permits router ingress only on 4180. It combines with the
namespace EgressFirewall to permit DNS, Keycloak's HTTPS router address and
GitHub HTTPS for the OAuth token exchange. Browsers may still fetch external
fonts or referenced images. Session cookies are Secure, HttpOnly and SameSite=Lax.

Validate with `make test`. Operational guidance is in the `Drawio on OpenShift`
note in `igou-docs`.
