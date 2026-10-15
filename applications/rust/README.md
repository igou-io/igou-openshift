# Rust dedicated server

Facepunch Rust, one persistent server in namespace `rust`. The only Service
is `rust` (`ClusterIP`), exposing gameplay UDP/28015 and queries UDP/28017.
There is no LAN or public endpoint. RCON listens on pod loopback TCP/28016.

`kustomization.yaml` uses app-template 4.6.2, restricted SCC security settings,
a 50Gi SSD PVC, and the digest-pinned `ghcr.io/igou-io/rust-server` image built
in `igou-containers/apps/rust-server`. SteamCMD anonymously installs app 258550
on first use. Cached installations start without an update or full validation;
updates require explicit maintenance while stopped. Server state lives under
`/data/rust/server/homelab/`, preserving the initial deployment's layout.

`server.cfg` holds non-secret game settings. The RCON password comes from
`op://lab_openshift/rust-rcon/rcon-password` through External Secrets. Startup
links the non-secret server.cfg into the server identity directory. Rust needs
the RCON password as a startup argument; the Python wrapper redacts the password
from both output streams before forwarding them to container logs. The password
is not written to the persistent volume.

Readiness runs `rust-server probe` for an A2S_INFO UDP query. The image handles
SIGTERM by requesting `server.save` and `quit` through local WebRCON, with a
90-second deadline inside the 120-second pod termination grace. Tini reaps
orphans. No liveness probe kills the server during a slow save. UBI 9 was tested
and rejected: the current Unity player needs glibc 2.35; UBI 9 has 2.34. Debian
13 slim supports the game and SteamCMD's 32-bit bootstrap in one package stack.

Operational commands, image/update policy and verification evidence
are in the `Rust Game Server on OpenShift` runbook in `igou-docs`.
