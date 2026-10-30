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

The image is digest-pinned and runs under OpenShift's `restricted-v2` SCC without
a service-account token. NetworkPolicy permits router ingress on port 8080 and
denies pod egress. Browsers may still fetch external fonts or referenced images.
The internal lab route has no authentication.

Validate with `make test`. Operational guidance is in the `Drawio on OpenShift`
note in `igou-docs`.
