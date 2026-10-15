# Rust dedicated server

Facepunch Rust, one persistent server in namespace `rust`. The only Service
is `rust` (`ClusterIP`), exposing gameplay UDP/28015 and queries UDP/28017.
There is no LAN or public endpoint. RCON listens on pod loopback TCP/28016.

`kustomization.yaml` uses app-template 4.6.2, restricted SCC security settings,
a 50Gi SSD PVC, and a digest-pinned runtime built by `rust-runtime` BuildConfig.
SteamCMD anonymously installs/updates app 258550 in the init container on each
pod start. Server state lives under `/data/rust/server/homelab/`.

`server.cfg` holds non-secret game settings. The RCON password comes from
`op://lab_openshift/rust-rcon/rcon-password` through External Secrets. Startup
writes the effective server.cfg onto memory-backed emptyDir and links it into
the server identity directory; the password is never passed in process args.

Readiness performs an A2S_INFO UDP query. The preStop hook requests
`server.save` followed by `quit` through local WebRCON, with a 120-second
termination grace period. No liveness probe kills the server during a slow save.

Operational commands, initial image bootstrap and live verification evidence
are in the `Rust Game Server on OpenShift` runbook in `igou-docs`.
