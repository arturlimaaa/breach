// No browser: the pages touch the DOM only through getElementById, so a fake DOM and a file-backed fetch run them as-is.
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import vm from 'node:vm';

const SITE = import.meta.dirname;
const FIXTURES = join(SITE, 'fixtures');
const fixture = async path => JSON.parse(await readFile(join(FIXTURES, path), 'utf8'));
const codes = html => [...html.matchAll(/<code>([^<]*)<\/code>/g)].map(m => m[1]);

async function render(page, run) {
  const html = await readFile(join(SITE, page), 'utf8');
  const elements = {}, fetches = [];
  const base = pathToFileURL(join(SITE, page));
  const context = vm.createContext({
    URLSearchParams,
    location: { search: `?run=${run}` },
    setInterval: () => 0,
    document: { getElementById: id => (elements[id] ??= { className: '', innerHTML: '', textContent: '' }) },
    // A missing file answers like http.server's 404: not ok, and a body that is not JSON.
    fetch: url => {
      const response = readFile(new URL(url, base), 'utf8').catch(() => '')
        .then(text => ({ ok: text !== '', json: async () => JSON.parse(text) }));
      fetches.push(response);
      return response;
    },
  });
  for (const [, src, inline] of html.matchAll(/<script(?: src="([^"]+)")?>([\s\S]*?)<\/script>/g)) {
    vm.runInContext(src ? await readFile(join(SITE, src), 'utf8') : inline, context);
  }
  await Promise.all(fetches);
  await new Promise(resolve => setImmediate(resolve));
  return elements;
}

test('every fixture parses', async () => {
  const files = (await readdir(FIXTURES, { recursive: true })).filter(f => f.endsWith('.json')).sort();
  await Promise.all(files.map(fixture));
  assert.deepEqual(files, [
    'certified/status.json', 'demoted/status.json', 'demoted/store.json',
    'proof.json', 'revising/status.json', 'status.json', 'store.json',
  ]);
});

test('the results table puts the worst case first, one row per episode, and the aggregate last', async () => {
  const proof = await fixture('proof.json');
  const { results } = await render('index.html', '../site/fixtures');
  const rows = [...results.innerHTML.matchAll(/<tr class="([^"]*)"><td>([^<]*)<\/td>/g)].map(m => [m[1], m[2]]);
  const worst = proof.worst_case.episode;
  assert.deepEqual(rows, [
    ['worst', worst],
    ...proof.episodes.filter(e => e.id !== worst).map(e => ['', e.id]),
    ['aggregate', 'aggregate'],
  ]);
});

test('a demoted or recertified rule shows its predecessor before it', async () => {
  for (const run of ['', '/demoted']) {
    const [status, store] = await Promise.all([`.${run}/status.json`, `.${run}/store.json`].map(fixture));
    const { plan } = await render('index.html', `../site/fixtures${run}`);
    const after = store.find(r => r.rule_id === status.rule.rule_id);
    assert.deepEqual(codes(plan.innerHTML.split('<div class="revision">')[1] ?? ''), [after.revision_of, after.rule_id], run);
  }
});

test('the rule cards show every stored rule, grouped by status', async () => {
  const store = await fixture('store.json');
  const { rules } = await render('index.html', '../site/fixtures');
  assert.deepEqual(
    { groups: [...rules.innerHTML.matchAll(/<h3>(\w+)/g)].map(m => m[1]), ids: codes(rules.innerHTML).sort() },
    { groups: ['certified', 'hypothesis'], ids: store.map(r => r.rule_id).sort() },
  );
});

test('a run with no files says so in place', async () => {
  const run = '../site/fixtures/missing';
  const page = await render('index.html', run);
  const banner = await render('banner.html', run);
  assert.deepEqual(
    [...['results', 'plan', 'rules'].map(id => page[id].innerHTML), banner.plan.textContent],
    [
      `<p class="missing">runs/${run}/proof.json is missing or not valid JSON.</p>`,
      `<p class="missing">runs/${run}/status.json is missing or not valid JSON.</p>`,
      `<p class="missing">runs/${run}/store.json is missing or not valid JSON.</p>`,
      `waiting for ../runs/${run}/status.json`,
    ],
  );
});

test('the banner renders each rule status', async () => {
  const lines = async dir => {
    const e = await render('banner.html', `../site/fixtures${dir}`);
    return [e.head.textContent, e.plan.textContent, e.action.textContent, e.rule.textContent, e.rule.className];
  };
  assert.deepEqual(await Promise.all(['', '/certified', '/demoted', '/revising'].map(lines)), [
    [
      'BREACH + NEMOTRON | 00:02.633 | step 13/250', 'PLAN: stone_pickaxe, now mine log', 'ACTION: probe stick',
      'RULE: craft:stick@grid/stick-count-2 → stick +2 ✓ recertified (2)', 'recertified',
    ],
    [
      'BREACH + NEMOTRON | 00:00.418 | step 11/250', 'PLAN: stone_pickaxe, now craft stick', 'ACTION: craft planks',
      'RULE: craft:planks → log -1, planks +4 ✓ certified (18)', 'certified',
    ],
    [
      'BREACH + NEMOTRON | 00:00.455 | step 12/250', 'PLAN: stone_pickaxe', 'ACTION: craft stick (mismatch)',
      'RULE: craft:stick@grid/stick-count-2 → predicted stick +4, observed stick +2 → demoted', 'demoted',
    ],
    [
      'BREACH + NEMOTRON | 00:02.597 | step 12/250', 'PLAN: stone_pickaxe', 'ACTION: craft stick (mismatch)',
      'RULE: craft:stick@grid/stick-count-2 → revising (Nemotron, 2.1 s)', 'revising',
    ],
  ]);
});

test('pages load nothing from the network and their markup holds no numbers', async () => {
  const offenders = [];
  for (const name of (await readdir(SITE)).filter(f => /\.(html|css|js)$/.test(f))) {
    const text = await readFile(join(SITE, name), 'utf8');
    if (/https?:\/\//.test(text)) offenders.push(`${name}: external URL`);
    const markup = text.replace(/<(script|style)\b[\s\S]*?<\/\1>|<[^>]*>/g, '');
    if (name.endsWith('.html') && /\d/.test(markup)) offenders.push(`${name}: digit in markup`);
  }
  assert.deepEqual(offenders, []);
});
