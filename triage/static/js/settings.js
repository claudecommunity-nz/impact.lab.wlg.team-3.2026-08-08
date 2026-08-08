// Settings: engine status, ruleset generation, destinations, input adapters
// and raw YAML editing. Everything the triage logic depends on is editable
// here, because the whole point is that the responder owns the rules.

import * as api from './api.js';
import { esc, toast, $ } from './util.js';

const FILES = [
  ['triage_rules', 'Triage rules'],
  ['settings', 'Settings'],
  ['destinations', 'Destinations'],
  ['sources', 'Input sources'],
];

let currentFile = 'triage_rules';
let draftYaml = null;

export function init() {
  const tabs = $('#configTabs');
  FILES.forEach(([name, label]) => {
    const b = document.createElement('button');
    b.className = 'config-tab' + (name === currentFile ? ' is-on' : '');
    b.textContent = label;
    b.dataset.file = name;
    b.addEventListener('click', () => loadFile(name));
    tabs.appendChild(b);
  });

  $('#btnSaveConfig').addEventListener('click', saveFile);
  $('#btnRetriage').addEventListener('click', async () => {
    const res = await api.retriageAll();
    toast(`Re-triaged: ${res.changed} changed, ${res.unchanged} unchanged, `
        + `${res.skipped} left alone (operator overrides and false reportings).`, 'ok');
    (await import('./queue.js')).refresh();
  });
  $('#btnReseed').addEventListener('click', async () => {
    if (!confirm('Wipe everything and reload the demo corpus?')) return;
    const res = await api.reseed();
    toast(`Reloaded ${res.loaded} reportings.`, 'ok');
    (await import('./queue.js')).refresh();
    (await import('./app.js')).refreshShift();
  });

  $('#btnGenRules').addEventListener('click', generate);
  $('#btnApplyRules').addEventListener('click', applyDraft);
}

export async function show() {
  await Promise.all([engineCard(), destCard(), adapterCard(), loadFile(currentFile)]);
}

// ------------------------------------------------------------ engine card

async function engineCard() {
  const [health, rules, llm] = await Promise.all([
    api.health(), api.rulesets(), api.llmStatus(),
  ]);
  $('#engineStatus').innerHTML = `
    <dt>Mode</dt><dd>${esc(health.engine_mode)}</dd>
    <dt>Active ruleset</dt><dd>${esc(rules.name || '—')} (v${rules.version}) · ${rules.rule_count} rules</dd>
    <dt>Drafted by</dt><dd>${esc(rules.generated_by || 'manual')}</dd>
    <dt>Declared hazard</dt><dd>${esc(rules.event?.hazard_type || 'all_hazards')}</dd>
    <dt>Response timeline</dt><dd>${esc(rules.event?.response_timeline || 'not declared')}</dd>
    <dt>Thresholds</dt><dd>action ≥ ${rules.thresholds?.action_required} ·
      verification ≥ ${rules.thresholds?.verification_required}</dd>
    <dt>Local model</dt><dd>
      <span class="led ${llm.available ? 'on' : ''}"></span>
      ${esc(llm.model)} at ${esc(llm.base_url)}
      ${llm.available ? (llm.model_present ? '· ready' : '· NOT PULLED') : '· unavailable'}
    </dd>
    <dt>Reportings held</dt><dd>${health.reportings}</dd>`;
}

// -------------------------------------------------------- destinations card

async function destCard() {
  const list = await api.destinations();
  $('#destList').innerHTML = list.map((d) => `
    <div class="dest">
      <div class="dest-h">
        <span class="dest-t">${esc(d.name)}</span>
        <span class="chip">${esc(d.type)}</span>
        <span class="dest-a">${esc(d.address || d.url || '')}</span>
        ${d.enabled === false ? '<span class="chip chip-alert">disabled</span>' : ''}
      </div>
      ${d.description ? `<div class="dest-d">${esc(d.description)}</div>` : ''}
    </div>`).join('');
}

// ------------------------------------------------------------ adapter card

async function adapterCard() {
  const list = await api.adapters();
  $('#adapterList').innerHTML = list.map((a) => `
    <div class="adapter">
      <div class="adapter-h">
        <span class="adapter-t">${esc(a.name)}</span>
        <span class="chip">${esc(a.channel)}</span>
      </div>
      ${a.description ? `<div class="adapter-d">${esc(a.description)}</div>` : ''}
      <div class="adapter-e">POST ${esc(a.endpoint)}</div>
      <div class="adapter-d">Maps ${a.fields.length} fields${a.collections.length ? ` and ${a.collections.join(', ')}` : ''}.</div>
    </div>`).join('');
}

// ------------------------------------------------------------ YAML editing

async function loadFile(name) {
  currentFile = name;
  document.querySelectorAll('.config-tab').forEach((t) => {
    t.classList.toggle('is-on', t.dataset.file === name);
  });
  const cfg = await api.getConfig(name);
  $('#configEditor').value = cfg.text;
  $('#configStatus').textContent = `config/${name}.yaml`;
}

async function saveFile() {
  try {
    await api.saveConfig(currentFile, $('#configEditor').value);
    $('#configStatus').textContent = `Saved config/${currentFile}.yaml`;
    toast('Saved. Re-triage the queue to apply it to reportings already in.', 'ok');
    engineCard();
    if (currentFile === 'destinations') {
      destCard();
      (await import('./detail.js')).init({});
    }
    if (currentFile === 'sources') adapterCard();
  } catch { /* toast already shown */ }
}

// -------------------------------------------------------- ruleset drafting

async function generate() {
  const hazard = $('#genHazard').value.trim();
  const timeline = $('#genTimeline').value.trim();
  if (!hazard || !timeline) {
    toast('Describe the hazard and your response timeline first.', 'err');
    return;
  }
  const btn = $('#btnGenRules');
  btn.disabled = true;
  $('#genStatus').textContent = 'Drafting with the local model — this takes 30–60 seconds…';
  try {
    const res = await api.generateRules({
      hazard_type: hazard, response_timeline: timeline,
      extra: $('#genExtra').value.trim() || null, apply: false,
    });
    draftYaml = res.yaml;
    $('#genYaml').textContent = res.yaml;
    $('#genResult').hidden = false;
    $('#genStatus').textContent = `Drafted ${res.ruleset.rules.length} rules. Read them before applying.`;
  } catch {
    $('#genStatus').textContent = 'Generation failed.';
  } finally {
    btn.disabled = false;
  }
}

async function applyDraft() {
  if (!draftYaml) return;
  if (!confirm('Apply this ruleset and re-triage the queue?\n\n'
             + 'Operator overrides and false reportings are left alone.')) return;
  await api.saveConfig('triage_rules', draftYaml);
  const res = await api.retriageAll();
  toast(`Ruleset applied. ${res.changed} reportings changed priority.`, 'ok');
  $('#genResult').hidden = true;
  await engineCard();
  await loadFile('triage_rules');
  (await import('./queue.js')).refresh();
}
