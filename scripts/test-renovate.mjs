// Run in the CI-pinned Renovate image; no registry credentials or cluster access.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const load = (file) => import(pathToFileURL(`/usr/local/renovate/dist/${file}`));
const { init } = await load('logger/index.js');
await init();
const { CustomDatasource } = await load('modules/datasource/custom/index.js');
const { extractPackageFile } = await load('modules/manager/custom/regex/index.js');
const { applyPackageRules } = await load('util/package-rules/index.js');
const { doAutoReplace } = await load('workers/repository/update/branch/auto-replace.js');
const { GlobalConfig } = await load('config/global.js');
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'redhat-ee-renovate-'));
GlobalConfig.set({ localDir: temporary, platform: 'local' });

try {
  const config = JSON.parse(await fs.readFile('renovate.json', 'utf8'));
  const manager = config.customManagers.find((item) => item.datasourceTemplate === 'custom.redhat-ee');
  const file = 'clusters/ocp/pac-tenants/values.yaml';
  const content = await fs.readFile(file, 'utf8');
  const extracted = extractPackageFile(content, file, manager);
  assert.equal(extracted.deps.length, 1);
  const dep = extracted.deps[0];
  const policy = await applyPackageRules({ ...dep, packageName: dep.depName,
    manager: 'custom.regex', packageFile: file, updateType: 'patch',
    automerge: true, packageRules: config.packageRules });
  assert.equal(policy.automerge, false);
  assert.equal(policy.minimumReleaseAge, null);
  assert.deepEqual(policy.schedule, ['at any time']);

  const digest = `sha256:${'a'.repeat(64)}`;
  const repo = { repository: 'ansible-automation-platform-27/ee-minimal-rhel9',
    published: true, push_date: '2026-10-28T12:00:00+00:00',
    manifest_list_digest: digest,
    tags: [{ name: '2.20' }, { name: '2.20-1793000000' }, { name: '1793000000' }] };
  const fixture = { data: [
    { architecture: 'amd64', repositories: [repo] },
    { architecture: 'arm64', repositories: [repo] },
  ] };
  const datasource = new CustomDatasource();
  const lookup = () => datasource.getReleases({ datasource: 'custom.redhat-ee',
    packageName: 'redhat-ee', customDatasources: config.customDatasources });
  datasource.http.getJsonUnchecked = async () => ({ body: fixture });
  const result = await lookup();
  assert.equal(result.releases.length, 1, 'Select only the current amd64 vendor image');
  assert.equal(result.releases[0].version, '2.20-1793000000');
  assert.equal(result.releases[0].newDigest, digest);
  assert.equal(result.releases[0].releaseTimestamp, '2026-10-28T12:00:00.000Z');
  const updated = await doAutoReplace({ ...manager, ...extracted, ...dep,
    depIndex: 0, packageFile: file, manager: 'regex', newValue: result.releases[0].version,
    newDigest: result.releases[0].newDigest }, content, false);
  assert.equal(updated, content.replace(`version=${dep.currentValue}`, 'version=2.20-1793000000')
    .replace(dep.currentDigest, digest), 'Update the recorded vendor build tag and digest together');

  for (const bad of [{ data: [] }, { data: [fixture.data[1]] },
    { data: [fixture.data[0], fixture.data[0]] },
    { data: [{ architecture: 'amd64', repositories: [{ ...repo, manifest_list_digest: undefined }] }] }]) {
    datasource.http.getJsonUnchecked = async () => ({ body: bad });
    assert.equal(await lookup(), null, 'Reject missing or ambiguous vendor metadata');
  }
  console.log('Red Hat EE catalog extraction, tag/digest replacement and manual-review policy passed.');
} finally {
  await fs.rm(temporary, { recursive: true, force: true });
}
