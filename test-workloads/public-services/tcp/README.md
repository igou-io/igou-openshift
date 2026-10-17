# TCP workload

Kubernetes `agnhost serve-hostname` listens on raw TCP 9000 and sends its pod
hostname to each connection. HTTP and UDP serving are disabled. This folder
owns the Deployment, ClusterIP Service `tcp-hostname`, Tailscale Service
`tcp-hostname-public`, and the endpoint ingress policy.

The pod uses a digest-pinned image, restricted security settings, a read-only
root filesystem, and no API token. Readiness and liveness use TCP socket probes.
The tailnet hostname is `ocp-public-tcp-hostname`; its tag is
`tag:ocp-public-tcp-hostname`.

The matching VPS example is `igou-kubernetes/examples/public-services/tcp/`.
Its native `TCPRoute` maps public TCP 27010 to this endpoint's TCP 9000.
After rollout and DNS setup, connect from outside the tailnet:

```bash
nc -w 3 tcp-test.igou.io 27010 < /dev/null
```

Expect the answering pod's hostname. For a local application check, forward
`service/tcp-hostname` TCP 9000 to a local port with `oc port-forward`.
Shared prerequisites and install commands are in `../README.md`.
