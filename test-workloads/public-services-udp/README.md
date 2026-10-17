# Public services UDP echo

One pinned Kubernetes `agnhost netexec` replica listens on UDP 9000 in
`public-services`. Send `echo hello` to receive `hello`, `hostname` to identify
the answering pod, or `clientip` to see the address observed by the server.

The pod uses restricted security settings, a read-only root filesystem, and no
API token. HTTP 8080 serves only the health handler through `--http-override`;
the ClusterIP Service and Tailscale endpoint expose only UDP 9000.

Install the shared namespace guardrails as described in
`test-workloads/public-services-web/README.md`, then deploy the fixture:

```bash
oc apply -k test-workloads/public-services-udp
oc rollout status deployment/udp-echo -n public-services
```

The namespace's default-deny policy blocks ordinary clients until the endpoint
policy is installed. The OpenShift chart's `examples/udp-values.yaml` selects
these pods, creating the separate Tailscale Service `udp-echo-public` and its
narrow ingress policy. The VPS chart's matching example maps public UDP 27018
to backend UDP 9000. Configure the endpoint, tailnet grants, DNS, and firewall
before checking from outside the tailnet:

```bash
printf 'echo hello\n' | nc -u -w 3 udp-test.igou.io 27018
printf 'hostname\n' | nc -u -w 3 udp-test.igou.io 27018
```

Expect `hello` and the pod's hostname. UDP checks need a reply; successful
packet transmission alone does not verify the path. API port forwarding
supports TCP and cannot check this UDP Service.

For AAP, the backend catalog example includes `udp-echo` with protocol UDP.
The fixture itself has no share expiration metadata; cleanup removes its
temporary VPS forwarding objects, leaving the pod and stable endpoint intact.

Remove only the fixture:

```bash
oc delete -k test-workloads/public-services-udp
```
