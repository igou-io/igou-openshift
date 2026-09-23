"""One-time Swarmer/OpenShell workspace bootstrap from the devcontainer.

Run after GitOps sync with the `ocp` credential profile active. Requires `op`
access to the lab_agents vault. No credential is written to disk or stdout.
"""

import base64
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

import yaml


APP = "https://swarmer.apps.ocp.igou.systems/api/v1"
ISSUER = "https://keycloak.apps.ocp.igou.systems/realms/igou"
PROFILE = Path(__file__).parent / "provider-profiles/opencode-go-for-swarmer.yaml"
MODEL = "gpt-5.6-luna"


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


def api(token: str, method: str, path: str, body: dict | None = None) -> dict | list:
    request = urllib.request.Request(
        APP + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def main() -> None:
    server = command("oc", "whoami", "--show-server")
    identity = command("oc", "whoami")
    if server != "https://api.ocp.igou.systems:6443" or identity != "system:admin":
        raise SystemExit("Activate the ocp profile for the intended cluster first")

    token = command("oc", "-n", "openshell", "create", "token", "swarmer-admin", "--duration=1h")
    workspaces = api(token, "GET", "/workspaces")
    workspace = next((item for item in workspaces if item["namespace"] == "swarmer-lab"), None)
    if workspace is None:
        workspace = api(token, "POST", "/workspaces", {
            "display_name": "swarmer-lab",
            "description": "OpenShell integration and OpenCode Go subscription test",
        })
    workspace_id = workspace["id"]

    cert_data = json.loads(command(
        "oc", "-n", "openshell", "get", "secret", "openshell-client-cert-manager-tls", "-o", "json"
    ))["data"]
    pem = lambda name: base64.b64decode(cert_data[name]).decode()
    client_secret = command("op", "read", "op://lab_agents/swarmer/OPENSHELL_CLIENT_SECRET")
    gateway = {
        "gateway_url": "https://openshell.openshell.svc:8080",
        "auth_mode": "oidc",
        "oidc_issuer": ISSUER,
        "oidc_client_id": "swarmer-openshell",
        "oidc_audience": "openshell-cli",
        "client_secret": client_secret,
        "tls_ca": pem("ca.crt"),
        "tls_cert": pem("tls.crt"),
        "tls_key": pem("tls.key"),
        "tls_verify": True,
    }
    api(token, "POST", f"/workspaces/{workspace_id}/gateway", gateway)
    probe = api(token, "POST", "/workspaces/gateway/test-connection", {
        "workspace_id": workspace_id,
        "gateway_url": gateway["gateway_url"],
        "auth_mode": "oidc",
        "tls_ca": gateway["tls_ca"],
        "tls_cert": gateway["tls_cert"],
        "tls_key": gateway["tls_key"],
    })
    if probe["status"] != "ok":
        raise RuntimeError("OpenShell gateway connection failed")

    form = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": "swarmer-openshell",
        "client_secret": client_secret,
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(
        ISSUER + "/protocol/openid-connect/token", data=form
    ), timeout=30) as response:
        openshell_token = json.load(response)["access_token"]

    profile = yaml.safe_load(PROFILE.read_text())
    key = command("op", "read", "op://lab_agents/opencode-go-subscription-key/password")
    pod = command(
        "oc", "-n", "openshell", "get", "pod", "-l", "app.kubernetes.io/name=swarmer",
        "-o", "jsonpath={.items[0].metadata.name}",
    )
    pod_code = """
import asyncio, json, sys
from swarmer.openshell_client import GatewayConfig, get_client_for_config, import_provider_profiles, ensure_provider
p = json.load(sys.stdin)
c = get_client_for_config(GatewayConfig(
    gateway_url='https://openshell.openshell.svc:8080', auth_mode='bearer',
    tls_ca='/auth/openshell/ca.crt', tls_cert='/auth/openshell/tls.crt',
    tls_key='/auth/openshell/tls.key', bearer_token=p['token'], workspace_id=p['workspace_id']))
async def main():
    await import_provider_profiles([p['profile']], client=c)
    await ensure_provider(f"swarmer-ws-{p['workspace_id']}-openai", p['profile']['id'], {},
                          credentials={'OPENAI_API_KEY': p['key']}, client=c)
    c.close()
asyncio.run(main())
"""
    subprocess.run(
        ["oc", "-n", "openshell", "exec", "-i", pod, "--", "python3", "-c", pod_code],
        input=json.dumps({
            "token": openshell_token, "key": key, "profile": profile,
            "workspace_id": workspace_id,
        }),
        text=True,
        check=True,
    )

    config = {
        "provider": {
            "openai": {
                "npm": "@ai-sdk/openai",
                "name": "OpenCode Go",
                "options": {
                    "baseURL": "https://opencode.ai/zen/go/v1",
                    "apiKey": "{env:OPENAI_API_KEY}",
                },
                "models": {MODEL: {"name": "GPT 5.6 Luna"}},
            }
        }
    }
    api(token, "POST", f"/workspaces/{workspace_id}/env-vars", {
        "key": "OPENCODE_CONFIG_CONTENT", "value": json.dumps(config, separators=(",", ":")),
    })
    api(token, "POST", f"/workspaces/{workspace_id}/secrets/credentials", {
        "openai_configured": True, "shared": True,
    })
    print(f"Workspace {workspace_id} configured for OpenCode Go; gateway version {probe['gateway_version']}")


if __name__ == "__main__":
    main()
