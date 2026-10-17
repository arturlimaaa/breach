// No browser: the pages touch the DOM only through getElementById and properties of what it returns,
// so a fake DOM and a file-backed fetch run them as-is.
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

// `served` answers a file name with an object, or with a string as the raw body, instead of reading the run directory.
async function render(page, run, served = {}) {
  const html = await readFile(join(SITE, page), 'utf8');
  const elements = {}, fetches = [];
  const base = pathToFileURL(join(SITE, page));
  const context = vm.createContext({
    URLSearchParams,
    location: { search: `?run=${run}` },
    setInterval: () => 0,
    document: { getElementById: id => (elements[id] ??= { className: '', innerHTML: '', textContent: '', querySelector: () => null }) },
    // A missing file answers like http.server's 404: not ok, and a body that is not JSON.
    fetch: url => {
      const name = url.split('/').pop(), value = served[name];
      const body = name in served ? Promise.resolve(typeof value === 'string' ? value : JSON.stringify(value))
        : readFile(new URL(url, base), 'utf8').catch(() => '');
      const response = body.then(text => ({ ok: text !== '', json: async () => JSON.parse(text), text: async () => text }));
      fetches.push(response);
      return response;
    },
  });
  for (const [, src, inline] of html.matchAll(/<script(?: src="([^"]+)")?>([\s\S]*?)<\/script>/g)) {
    vm.runInContext(src ? await readFile(join(SITE, src), 'utf8') : inline, context);
  }
  // A fetch can start another (watch.html reads manifest.json, then the log), so wait until none is new.
  for (let seen = -1; seen < fetches.length;) {
    seen = fetches.length;
    await Promise.all(fetches);
    await new Promise(resolve => setImmediate(resolve));
  }
  return elements;
}

const jsonl = async path => (await readFile(join(FIXTURES, path), 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));

test('every fixture parses', async () => {
  const files = (await readdir(FIXTURES, { recursive: true })).filter(f => /\.jsonl?$/.test(f)).sort();
  await Promise.all(files.map(f => f.endsWith('.jsonl') ? jsonl(f) : fixture(f)));
  assert.deepEqual(files, [
    'certified/status.json', 'demoted/status.json', 'demoted/store.json', 'manifest.json', 'proof.json',
    'revising/status.json', 'status.json', 'stick-count-2-hc-s1.jsonl', 'store.json',
  ]);
});

const tableRows = html => [...html.matchAll(/<tr class="([^"]*)">(.*?)<\/tr>/g)]
  .map(([, cls, cells]) => [cls, ...[...cells.matchAll(/<td>([^<]*)<\/td>/g)].map(m => m[1])]);
const results = async (served = {}) => {
  const html = (await render('index.html', '../site/fixtures', served)).results.innerHTML;
  const [headline, episodes] = html.split('<h3>Episodes').map(tableRows);
  const lines = [...(html.match(/<ul>(.*?)<\/ul>/)?.[1] ?? '').matchAll(/<li>(.*?)<\/li>/g)].map(m => m[1].replace(/<[^>]*>/g, ''));
  return { headline, lines, episodes };
};

test('the headline table puts each worst row first, then each system\'s means with its aggregate last', async () => {
  const { headline } = await results();
  assert.deepEqual(headline.map(r => r.slice(0, 3)), [
    ['worst', 'B', 'worst'], ['worst', 'D', 'worst'],
    ['', 'B', 'HC'], ['aggregate', 'B', 'all'],
    ['', 'D', 'HC'], ['', 'D', 'HS'], ['aggregate', 'D', 'all'],
  ]);
});

test('the episode table lists each system\'s worst case first, then every other episode once', async () => {
  const proof = await fixture('proof.json');
  const { episodes } = await results();
  const worst = Object.entries(proof.worst_case).filter(([, w]) => w.episode).map(([system, w]) => ['worst-case', system, w.episode]);
  assert.deepEqual(
    { first: episodes.slice(0, worst.length).map(r => r.slice(0, 3)), marked: episodes.slice(worst.length).filter(r => r[0]).length, all: episodes.map(r => `${r[1]}/${r[2]}`).sort() },
    { first: worst, marked: 0, all: proof.episodes.map(e => `${e.system}/${e.id}`).sort() },
  );
});

test('results format numbers as breach.proof does and give one worst-case line per system', async () => {
  const proof = {
    episodes: [
      { system: 'B', id: 'b-hc-s1', success: true, actions: 20, contradictions: 2, actions_after_contradiction: 1, immediate_repeat: 1, recovery_latency: null, text_model_calls: 0, tokens: 0 },
      { system: 'D', id: 'd-hc-s1', success: true, actions: 30, contradictions: 1, actions_after_contradiction: 0, immediate_repeat: 0, recovery_latency: 7, text_model_calls: 1, tokens: 1500 },
    ],
    rows: [
      { system: 'B', set: 'worst', episodes: 1, success: 1, actions_per_success: 20, contradicted: 1, actions_after_contradiction: 1, immediate_repeat: 1, recovery_latency_mean: null, recovery_latency_worst: null, unrecovered: 1, text_model_calls: 0, tokens: 0 },
      { system: 'D', set: 'HC', episodes: 2, success: 0.5, actions_per_success: 30, contradicted: 1, actions_after_contradiction: 0, immediate_repeat: 0, recovery_latency_mean: 7.5, recovery_latency_worst: 7, unrecovered: 0, text_model_calls: 0.5, tokens: 750 },
    ],
    worst_case: { A: { episode: null, recovery_latency: null }, B: { episode: 'b-hc-s1', recovery_latency: null }, D: { episode: 'd-hc-s1', recovery_latency: 7 } },
    aggregate: {},
  };
  assert.deepEqual(await results({ 'proof.json': proof }), {
    headline: [
      ['worst', 'B', 'worst', '1', '100%', '20', '1', '1', '100%', '–', 'never', '0', '0'],
      ['', 'D', 'HC', '2', '50%', '30', '1', '0', '0%', '7.5', '7', '0.5', '750'],
    ],
    lines: ['A: no contradiction.', 'B: worst case b-hc-s1, never recovered.', 'D: worst case d-hc-s1, recovered after 7 actions.'],
    episodes: [
      ['worst-case', 'B', 'b-hc-s1', 'yes', '20', '2', '1', '1', 'never', '0', '0'],
      ['worst-case', 'D', 'd-hc-s1', 'yes', '30', '1', '0', '0', '7', '1', '1500'],
    ],
  });
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

const stepRows = html => [...html.matchAll(/<tr class="([^"]*)"><td>([^<]*)<\/td>[\s\S]*?<td class="([^"]*)">([^<]*)<\/td><\/tr>/g)]
  .map(([, cls, step, tone, verdict]) => ({ step: Number(step), test: cls === 'test', tone, verdict }));
const lines = steps => steps.map(t => JSON.stringify({ action: 'move', target: 'east', predicted: {}, observed: {}, verdict: 'match', test: false, ...t })).join('\n');

test('the step log shows the newest transitions first, at most thirty', async () => {
  const logged = async (run, served) => stepRows((await render('watch.html', run, served)).log.innerHTML).map(r => r.step);
  const long = lines(Array.from({ length: 35 }, (_, i) => ({ step: i + 1 })));
  assert.deepEqual(
    { fixture: await logged('../site/fixtures'), long: await logged('../site/fixtures/missing', { 't1.jsonl': long }) },
    { fixture: (await jsonl('stick-count-2-hc-s1.jsonl')).map(t => t.step).reverse(), long: Array.from({ length: 30 }, (_, i) => 35 - i) },
  );
});

test('step verdicts take the banner\'s colors, and test steps are marked', async () => {
  const banner = await readFile(join(SITE, 'banner.html'), 'utf8');
  const color = cls => (cls && banner.match(new RegExp(`\\.${cls}\\b[^{]*\\{ color: (#\\w+)`))?.[1]) || null;
  const log = lines([
    { step: 1, action: 'mine', target: 'log', predicted: { log: 1 }, observed: { log: 1 } },
    { step: 2, action: 'probe', target: 'stick', predicted: { stick: 2 }, observed: { stick: 2 }, test: true },
    { step: 3, action: 'craft', target: 'stick', predicted: { planks: -2, stick: 4 }, observed: { planks: -2, stick: 2 }, verdict: 'mismatch' },
    { step: 4, action: 'mine', target: 'stone', predicted: { cobblestone: 1 }, verdict: 'quarantined' },
    { step: 5, action: 'look', target: null, verdict: 'ignored' },
  ]);
  const page = await render('watch.html', '../site/fixtures/missing', { 't1.jsonl': log });
  assert.deepEqual(stepRows(page.log.innerHTML).map(r => [r.step, r.test, r.verdict, color(r.tone)]), [
    [5, false, 'ignored', null],
    [4, false, 'quarantined', '#fbbf24'],
    [3, false, 'mismatch', '#f87171'],
    [2, true, 'match', '#4ade80'],
    [1, false, 'match', '#4ade80'],
  ]);
});

test('the watch page says when there is no status and no steps yet', async () => {
  const page = await render('watch.html', '../site/fixtures/missing');
  assert.deepEqual([page.status.innerHTML, page.log.innerHTML, page.viewer.src], [
    '<p class="missing">No status yet.</p>',
    '<p class="missing">No steps yet in <code>t1.jsonl</code>.</p>',
    'http://127.0.0.1:3007',
  ]);
});

test('pages load nothing from another origin but the viewer, and their markup holds no numbers', async () => {
  const offenders = [];
  for (const name of (await readdir(SITE)).filter(f => /\.(html|css|js)$/.test(f))) {
    const text = await readFile(join(SITE, name), 'utf8');
    // The adapter's viewer, framed by watch.html, is the one other origin.
    const urls = (text.match(/https?:\/\/[^\s'"`)]+/g) ?? []).filter(url => !(name === 'watch.html' && url === 'http://127.0.0.1:3007'));
    offenders.push(...urls.map(url => `${name}: ${url}`));
    const markup = text.replace(/<(script|style)\b[\s\S]*?<\/\1>|<[^>]*>/g, '');
    if (name.endsWith('.html') && /\d/.test(markup)) offenders.push(`${name}: digit in markup`);
  }
  assert.deepEqual(offenders, []);
});
