# draw.io

Self-hosted draw.io editor and the official draw.io MCP App server, deployed as
the `drawio` ArgoCD Application in namespace `drawio`.

- Editor: <https://drawio.apps.ocp.igou.systems>
- Streamable HTTP MCP: <https://drawio-mcp.apps.ocp.igou.systems/mcp>
- MCP health: <https://drawio-mcp.apps.ocp.igou.systems/health>

The MCP tools are `create_diagram`, `search_shapes`, and `get_drawio_reference`.
Clients supporting MCP Apps can render the interactive viewer; other clients
receive a link to the local editor. Both workloads are stateless: save editable
`.drawio` files in the owning repository or download them from the editor.

`configure-mcp.mjs` copies the upstream MCP source into an emptyDir and rewrites
the hardcoded public editor/viewer origins to this deployment. This also updates
the MCP App resource CSP. Image updates must preserve that behavior; verify both
the returned editor URL and resource URLs after upgrading. The image itself and
its dependencies are unchanged.

Ingress is limited to the OpenShift router; pod egress is denied. External icon
search is disabled, while the bundled shape library remains available. The MCP
server's best-effort viewer version check times out without affecting requests.
The browser may still fetch external fonts or externally referenced images.
These lab-only routes have no authentication; do not expose them publicly without
an authentication gateway.

Validate with `make test`. Operational guidance and T3 setup are in the
`Drawio and Agent MCP on OpenShift` note in `igou-docs`.
