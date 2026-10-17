# HTTP workload

nginx returns `public-services web test` on TCP 8080. This folder owns its
Deployment, response ConfigMap, ClusterIP Service `public-web-test`, Tailscale
Service `public-web-test-public`, and the endpoint ingress policy.

The pod uses restricted security settings, a read-only root filesystem, and
no API token. The Tailscale hostname is `ocp-public-web-test`; its tag is
`tag:ocp-public-web-test`.

The matching VPS example is `igou-kubernetes/examples/public-services/http/`.
Its native `HTTPRoute` publishes HTTPS `https://web-test.igou.io/` and forwards
to this endpoint on TCP 8080. After rollout, check:

```bash
curl --fail https://web-test.igou.io/
```

For a local application check, run API port forwarding in a separate terminal:

```bash
oc port-forward -n public-services service/public-web-test 18080:8080
```

```bash
curl --fail http://127.0.0.1:18080/
```

Expect `public-services web test`. Port forwarding checks the server through
the API; it does not verify the public path. Shared prerequisites and install
commands are in `../README.md`.
