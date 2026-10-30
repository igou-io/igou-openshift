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
NetworkPolicy permits router ingress only on 4180 and egress only to cluster
DNS and Keycloak's HTTPS router address. Browsers may still fetch external fonts
or referenced images. Session cookies are Secure, HttpOnly and SameSite=Lax.

Validate with `make test`. Operational guidance is in the `Drawio on OpenShift`
note in `igou-docs`.
