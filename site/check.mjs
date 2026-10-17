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

const tableRows = html => [...html.matchAll(/<tr class="([^"]*)">(.*?)<\/tr>/g)]
  .map(([, cls, cells]) => [cls, ...[...cells.matchAll(/<td>([^<]*)<\/td>/g)].map(m => m[1])]);
const resultTables = async () => (await render('index.html', '../site/fixtures')).results.innerHTML.split('<h3>Episodes').map(tableRows);

test('the headline table leads with each worst row, then the means, then each aggregate', async () => {
  const [headline] = await resultTables();
  assert.deepEqual(headline, [
    ['worst', 'B', 'worst', '5', '0%', '73', '5', '54', '100%', '–', 'never', '0', '0'],
    ['worst', 'D', 'worst', '10', '100%', '60', '5', '0', '0%', '11', '21', '2', '5130'],
    ['', 'B', 'HC', '5', '40%', '64', '5', '29.8', '20%', '–', 'never', '0', '0'],
    ['', 'D', 'HC', '5', '100%', '37.2', '5', '0', '0%', '11', '21', '1.2', '2863.2'],
    ['', 'D', 'HS', '5', '100%', '28.8', '0', '–', '–', '–', '–', '0', '0'],
    ['aggregate', 'B', 'all', '5', '40%', '64', '5', '29.8', '20%', '–', 'never', '0', '0'],
    ['aggregate', 'D', 'all', '10', '100%', '33', '5', '0', '0%', '11', '21', '0.6', '1431.6'],
  ]);
});

test('the episode table lists each system\'s worst case first, then every other episode once', async () => {
  const proof = await fixture('proof.json');
  const [, rows] = await resultTables();
  assert.deepEqual(
    { first: rows.slice(0, 2).map(r => r.slice(0, 3)), marked: rows.slice(2).filter(r => r[0]).length, all: rows.map(r => `${r[1]}/${r[2]}`).sort() },
    {
      first: [['worst-case', 'B', 'crafting_table-swap-planks-log-hc-s1'], ['worst-case', 'D', 'stone_pickaxe-swap-cobblestone-log-hc-s1']],
      marked: 0,
      all: proof.episodes.map(e => `${e.system}/${e.id}`).sort(),
    },
  );
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
