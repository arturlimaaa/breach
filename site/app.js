const run = new URLSearchParams(location.search).get('run') || 'latest';
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);
const num = v => v == null ? '–' : typeof v === 'boolean' ? (v ? 'yes' : 'no')
  : typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(1) : esc(v);
const pct = v => typeof v === 'number' ? `${Math.round(v * 100)}%` : v;
const delta = d => Object.entries(d || {}).sort(([, a], [, b]) => a - b).map(([k, n]) => `${k} ${n > 0 ? '+' : ''}${n}`).join(', ');
const load = name => fetch(`../runs/${run}/${name}`, { cache: 'no-store' }).then(r => r.ok ? r.json() : null).catch(() => null);
const missing = name => `<p class="missing">runs/${esc(run)}/${name} is missing or not valid JSON.</p>`;

// Server and change are left out: the episode id names the change, and with them the metrics overflow a laptop screen.
const COLS = ['id', 'task', 'seed', 'success', 'actions', 'contradictions',
  'actions_after_contradiction', 'immediate_repeat', 'recovery_latency', 'text_model_calls', 'tokens'];

function row(e, cls) {
  // Null latency also means "never contradicted" or "finished without needing the rule again".
  const never = e.contradictions && !e.success && e.recovery_latency == null;
  return `<tr class="${cls}">${COLS.map(k => `<td>${num(k === 'recovery_latency' && never ? 'never' : e[k])}</td>`).join('')}</tr>`;
}

function results(p) {
  const eps = p.episodes || [], worst = p.worst_case?.episode, a = p.aggregate;
  const rows = [...eps.filter(e => e.id === worst).map(e => row(e, 'worst')), ...eps.filter(e => e.id !== worst).map(e => row(e, ''))];
  if (a) rows.push(row({
    id: 'aggregate', success: pct(a.holdout_success), actions: a.actions_per_success,
    actions_after_contradiction: a.actions_after_contradiction, immediate_repeat: pct(a.immediate_repeat_rate),
    recovery_latency: `${num(a.recovery_latency_mean)} mean, ${num(a.recovery_latency_worst)} worst`,
    text_model_calls: a.text_model_calls_per_episode,
  }, 'aggregate'));
  const gaps = [!worst && 'worst_case', !a && 'aggregate'].filter(Boolean);
  return `<p>System <code>${esc(p.system)}</code>, ${eps.length} episodes. Worst case first; the aggregate row holds rates and means.
${gaps.length ? `<span class="missing">proof.json has no ${gaps.join(' or ')}.</span>` : ''}</p>
<div class="scroll"><table><thead><tr>${COLS.map(k => `<th>${k === 'id' ? 'episode' : k.replaceAll('_', ' ')}</th>`).join('')}</tr></thead>
<tbody>${rows.join('')}</tbody></table></div>`;
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
