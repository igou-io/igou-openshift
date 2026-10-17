# UDP workload

Kubernetes `agnhost netexec` listens on UDP 9000. Send `echo hello` to receive
`hello`, `hostname` to identify the answering pod, or `clientip` to see the
address observed by the server. This folder owns the Deployment, ClusterIP
Service `udp-echo`, Tailscale Service `udp-echo-public`, and endpoint ingress policy.

The pod uses a digest-pinned image, restricted security settings, a read-only
root filesystem, and no API token. HTTP 8080 serves only the health handler
through `--http-override=/healthz`; both Services expose UDP 9000 only.
The tailnet hostname is `ocp-public-udp-echo`; its tag is `tag:ocp-public-udp-echo`.

The matching VPS example is `igou-kubernetes/examples/public-services/udp/`.
Its native `UDPRoute` maps public UDP 27018 to this endpoint on UDP 9000.
After rollout and DNS setup, check from outside the tailnet:

```bash
printf 'echo hello\n' | nc -u -w 3 udp-test.igou.io 27018
printf 'hostname\n' | nc -u -w 3 udp-test.igou.io 27018
```

Expect `hello` and the pod's hostname. A successful send alone does not verify
the path; UDP needs a reply. API port forwarding supports TCP only and cannot
check this UDP Service. Shared prerequisites and install commands are in
`../README.md`.
