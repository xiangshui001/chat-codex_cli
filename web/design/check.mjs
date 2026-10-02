import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { Script } from 'node:vm';

const root = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(root, 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
if (scripts.length !== 1) throw new Error('Expected one inline preview script');
new Script(scripts[0][1], { filename: 'index.html' });
for (const name of ['dashboard', 'tasks', 'models', 'hosts', 'evidence', 'reviews', 'members']) {
  if (!html.includes(`${name}:`)) throw new Error(`Missing route: ${name}`);
}
if (/<(?:script|link|img)[^>]+(?:src|href)=["']https?:/i.test(html)) {
  throw new Error('Offline preview must not load remote assets');
}
if (!html.includes('Copyright (c) 2026 DeepSeek')) throw new Error('Missing upstream notice');
for (const file of ['contracts.ts', 'DSH_ADAPTATION.md', 'NOTICE.md', 'third-party/DEEPSEEK-LICENSE.txt']) {
  readFileSync(join(root, file), 'utf8');
}
console.log('Preview script syntax, seven routes, offline assets and notices: OK');
