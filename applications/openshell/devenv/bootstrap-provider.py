"""Register the devenv provider using existing Keycloak and 1Password credentials.

Requires openshell==0.0.116 and PyYAML. Credentials remain in memory.
"""
from pathlib import Path
import subprocess

import grpc
import yaml
from google.protobuf.json_format import ParseDict
from openshell import ClientCredentialsAuth, SandboxClient, TlsConfig
from openshell._proto import openshell_pb2 as pb


def secret(reference):
    return subprocess.check_output(['op', 'read', reference], text=True).strip()


def main():
    auth = ClientCredentialsAuth(
        issuer='https://keycloak.apps.ocp.igou.systems/realms/igou',
        client_id='swarmer-openshell',
        client_secret=secret('op://lab_agents/swarmer/OPENSHELL_CLIENT_SECRET'),
        audience='openshell-cli',
    )
    client = SandboxClient(
        'openshell.apps.ocp.igou.systems:443', tls=TlsConfig(),
        client_credentials=auth, timeout=60,
    )
    try:
        source = Path(__file__).parent.parent / 'provider-profiles/opencode-go-devenv.yaml'
        data = yaml.safe_load(source.read_text())
        data['category'] = 'PROVIDER_PROFILE_CATEGORY_INFERENCE'
        data['binaries'] = [{'path': value} for value in data['binaries']]
        profile = ParseDict(data, pb.ProviderProfile())
        request = pb.ImportProviderProfilesRequest(workspace='')
        request.profiles.add(profile=profile, source='igou-openshift')
        try:
            client._stub.ImportProviderProfiles(request, timeout=60)
        except grpc.RpcError as error:
            if error.code() != grpc.StatusCode.ALREADY_EXISTS:
                raise
            existing = client._stub.GetProviderProfile(
                pb.GetProviderProfileRequest(id=profile.id, workspace=''), timeout=60,
            )
            # Use the stored revision for optimistic concurrency.
            profile.resource_version = existing.profile.resource_version
            update = pb.UpdateProviderProfilesRequest(
                workspace='', id=profile.id,
                expected_resource_version=profile.resource_version,
                profile=pb.ProviderProfileImportItem(profile=profile, source='igou-openshift'),
            )
            client._stub.UpdateProviderProfiles(update, timeout=60)
        request = pb.CreateProviderRequest(workspace='default')
        request.provider.metadata.name = profile.id
        request.provider.type = profile.id
        request.provider.credentials['OPENAI_API_KEY'] = secret(
            'op://lab_agents/opencode-go-subscription-key/password'
        )
        try:
            client._stub.CreateProvider(request, timeout=60)
        except grpc.RpcError as error:
            if error.code() != grpc.StatusCode.ALREADY_EXISTS:
                raise
            client._stub.UpdateProvider(
                pb.UpdateProviderRequest(provider=request.provider, workspace='default'),
                timeout=60,
            )
        print('Configured opencode-go-devenv in the default workspace.')
    finally:
        client.close()


if __name__ == '__main__':
    main()
