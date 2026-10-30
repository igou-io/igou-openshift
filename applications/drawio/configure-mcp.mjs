// The official MCP image has no setting for its editor/viewer origin.
// Adapt its bundled source on an emptyDir; keep the upstream image untouched.
import { cpSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';

const origin = new URL(process.env.DRAWIO_BASE_URL).origin;
const source = '/app/mcp-app-server/src';
const target = '/configured-src';
cpSync(source, target, { recursive: true });

let replacements = 0;
for (const file of readdirSync(target)) {
  if (!file.endsWith('.js')) continue;
  const filename = `${target}/${file}`;
  const original = readFileSync(filename, 'utf8');
  const configured = original.replace(/https:\/\/(app|viewer)\.diagrams\.net/g, () => {
    replacements++;
    return origin;
  });
  writeFileSync(filename, configured);
}

// Fail visibly if an upstream refactor removes the adaptation points.
if (replacements === 0) throw new Error('No draw.io origins found in MCP source');
console.log(`Configured ${replacements} editor/viewer origins as ${origin}`);
