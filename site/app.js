const run = new URLSearchParams(location.search).get('run') || 'latest';
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
const num = v => v == null ? '–' : typeof v === 'boolean' ? (v ? 'yes' : 'no')
  : typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(1) : esc(v);
const pct = v => typeof v === 'number' ? `${Math.round(v * 100)}%` : v;
const delta = d => Object.entries(d || {}).sort(([, a], [, b]) => a - b).map(([k, n]) => `${k} ${n > 0 ? '+' : ''}${n}`).join(', ');
const load = name => fetch(`../runs/${run}/${name}`, { cache: 'no-store' }).then(r => r.ok ? r.json() : null).catch(() => null);
const missing = name => `<p class="missing">runs/${esc(run)}/${name} is missing or not valid JSON.</p>`;

const SUMMARY = ['system', 'set', 'episodes', 'success', 'actions_per_success', 'contradicted', 'actions_after_contradiction',
  'immediate_repeat', 'recovery_latency_mean', 'recovery_latency_worst', 'text_model_calls', 'tokens'];
// Task, seed, server and change are left out: the episode id names them, and with them the metrics overflow a laptop screen.
const EPISODE = ['system', 'id', 'success', 'actions', 'contradictions', 'actions_after_contradiction',
  'immediate_repeat', 'recovery_latency', 'text_model_calls', 'tokens'];

const tr = (cls, cells) => `<tr class="${cls}">${cells.map(c => `<td>${num(c)}</td>`).join('')}</tr>`;
const table = (cols, rows) => `<div class="scroll"><table><thead><tr>${cols.map(k => `<th>${k === 'id' ? 'episode' : k.replaceAll('_', ' ')}</th>`).join('')}</tr></thead>
<tbody>${rows.join('')}</tbody></table></div>`;
// Formatted as breach.proof's table: rates as percentages, and "never" when a contradicted episode never matched again.
const summary = (r, cls) => tr(cls, SUMMARY.map(k => k === 'success' || k === 'immediate_repeat' ? pct(r[k])
  : k === 'recovery_latency_worst' && r.unrecovered ? 'never' : r[k]));
const episode = (e, cls) => tr(cls, EPISODE.map(k => k === 'recovery_latency' && e.contradictions && e[k] == null ? 'never' : e[k]));

const recovery = w => w.episode == null ? 'no contradiction' : `worst case <code>${esc(w.episode)}</code>, ${w.recovery_latency == null
  ? 'never recovered' : `recovered after ${num(w.recovery_latency)} action${w.recovery_latency === 1 ? '' : 's'}`}`;

function results(p) {
  const eps = p.episodes || [], rows = p.rows || [], worst = p.worst_case || {}, aggregate = p.aggregate || {};
  // Systems share episode ids, so a worst case is a (system, id) pair.
  const isWorst = e => worst[e.system]?.episode === e.id;
  const systems = [...new Set([...rows.map(r => r.system), ...Object.keys(aggregate)])];
  const summaries = [...rows.filter(r => r.set === 'worst').map(r => summary(r, 'worst')),
    ...systems.flatMap(s => [...rows.filter(r => r.system === s && r.set !== 'worst').map(r => summary(r, '')),
      ...(aggregate[s] ? [summary({ system: s, set: 'all', ...aggregate[s] }, 'aggregate')] : [])])];
  const gaps = ['rows', 'worst_case', 'aggregate'].filter(k => !p[k]);
  return `<p>Worst rows first, then each system's means by task set, with <code>all</code> over every episode.
${gaps.length ? `<span class="missing">proof.json has no ${gaps.join(', ')}.</span>` : ''}</p>
${table(SUMMARY, summaries)}
<ul>${Object.entries(worst).map(([s, w]) => `<li><code>${esc(s)}</code>: ${recovery(w)}.</li>`).join('')}</ul>
<h3>Episodes (${eps.length}), each system's worst case first</h3>
${table(EPISODE, [...eps.filter(isWorst).map(e => episode(e, 'worst-case')), ...eps.filter(e => !isWorst(e)).map(e => episode(e, ''))])}`;
}

const card = r => `<div class="card ${esc(r.status)}"><code>${esc(r.rule_id)}</code> <span class="delta">${esc(delta(r.delta))}</span>
<small>${esc(r.status)} · scope ${esc(r.scope)} · ${(r.evidence || []).length} evidence${r.tool ? ` · tool ${esc(r.tool)}` : ''}${r.near ? ` · near ${esc(r.near)}` : ''} · ${esc(r.source)}${r.revision_of ? ` · revises ${esc(r.revision_of)}` : ''}</small></div>`;

function revision(id, store) {
  const after = Array.isArray(store) ? store.find(r => r.rule_id === id) : null;
  const before = after && store.find(r => r.rule_id === after.revision_of);
  return before ? `<div class="revision">${card(before)}<span>→</span>${card(after)}</div>`
    : `<p class="missing">No before and after: store.json has no ${esc(id)} with a revision_of in the store.</p>`;
}

function plan(s, store) {
  const r = s.rule || {}, m = s.model || {};
  const latency = m.last_latency_ms == null ? '–' : `${(m.last_latency_ms / 1000).toFixed(1)} s`;
  return `<p><code>${esc(s.episode)}</code> on <code>${esc(s.server)}</code>, goal <code>${esc(s.goal)}</code>, step ${num(s.step)} of ${num(s.budget)}, updated ${esc(s.updated)}.</p>
<p class="rule ${esc(r.status)}">Rule <code>${esc(r.rule_id)}</code> ${esc(r.status)}, ${num(r.evidence)} evidence${r.note ? `: ${esc(r.note)}` : ''}. Nemotron calls ${num(m.calls)}, last ${latency}.</p>
<ol class="plan">${(s.plan || []).map(p => `<li class="${esc(p.status)}"><code>${esc(p.rule_id)}</code> ${esc(p.action)} ${esc(p.target)}</li>`).join('')}</ol>
${['demoted', 'recertified'].includes(r.status) ? revision(r.rule_id, store) : ''}`;
}

function rules(store) {
  const order = [...new Set(['certified', 'hypothesis', 'demoted', ...store.map(r => r.status)])];
  return order.map(status => store.filter(r => r.status === status)).filter(group => group.length)
    .map(group => `<h3>${esc(group[0].status)} (${group.length})</h3><div class="cards">${group.map(card).join('')}</div>`).join('')
    || '<p>The store has no rules.</p>';
}

// One bad file blanks only its own section.
function section(id, data, name, render) {
  try {
    $(id).innerHTML = data ? render(data) : missing(name);
  } catch (err) {
    $(id).innerHTML = `<p class="missing">${name} could not be rendered: ${esc(err.message)}</p>`;
  }
}

$('run').textContent = run;
Promise.all(['status.json', 'proof.json', 'store.json'].map(load)).then(([status, proof, store]) => {
  section('results', proof, 'proof.json', results);
  section('plan', status, 'status.json', s => plan(s, store));
  section('rules', Array.isArray(store) && store, 'store.json', rules);
});
