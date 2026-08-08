// Settings: engine status, the controller's triage instructions, forwarding
// destinations, input adapters and raw YAML editing. Everything the triage
// logic depends on is editable here — the responder owns the rules.

import * as api from './api.js';
import { URGENCY_LABEL, countdown, esc, stamp, toast, urgencyOf, $ } from './util.js';

const FILES = [
  ['triage_rules', 'Triage rules'],
  ['settings', 'Settings'],
  ['destinations', 'Destinations'],
  ['sources', 'Input sources'],
];

let currentFile = 'triage_rules';

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

  initInstructions();
  initObligations();
}

export async function show() {
  await Promise.all([engineCard(), destCard(), adapterCard(),
                     loadInstructions(), loadObligations(),
                     loadFile(currentFile)]);
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
    <dt>Thresholds</dt><dd>action ≥ ${rules.thresholds?.action_required} ·
      verification ≥ ${rules.thresholds?.verification_required}</dd>
    <dt>Model provider</dt><dd>
      <span class="led ${llm.available ? 'on' : ''}"></span>
      ${esc(llm.provider || 'unknown')} · ${esc(llm.model || '—')}
      ${llm.available ? '· ready' : '· unavailable'}
    </dd>
    <dt>${llm.provider === 'ollama' ? 'Endpoint' : 'API key'}</dt><dd>${esc(
      llm.provider === 'ollama' ? (llm.base_url || '—') : (llm.key_source || 'not configured'))}</dd>
    ${llm.error ? `<dt>Model error</dt><dd class="muted">${esc(llm.error)}</dd>` : ''}
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

// ------------------------------------------------- controller instructions

async function loadInstructions() {
  const info = await api.getInstructions();
  $('#instrEditor').value = info.text || '';
  $('#instrEditor').dataset.template = info.template || '';
  $('#instrStatus').textContent = info.present
    ? `${info.chars} characters · updated ${stamp(info.updated_at)} · ${info.path}`
    : 'No instructions set — the model runs on the scoring rules alone.';
}

async function saveInstructions(retriage) {
  try {
    const info = await api.putInstructions($('#instrEditor').value);
    $('#instrStatus').textContent =
      `${info.chars} characters · saved · ${info.path}`;
    toast('Instructions saved. They apply to every reporting triaged from now on.', 'ok');
    if (retriage) {
      const res = await api.retriageAll();
      toast(`Re-triaged: ${res.changed} changed, ${res.unchanged} unchanged, `
          + `${res.skipped} left alone (operator overrides and false reportings).`, 'ok');
      (await import('./queue.js')).refresh();
    }
  } catch { /* toast already shown */ }
}

function initInstructions() {
  $('#instrFile').addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    try {
      const info = await api.uploadInstructions(file);
      $('#instrEditor').value = info.text || '';
      $('#instrStatus').textContent =
        `${info.chars} characters from ${info.filename} · ${info.path}`;
      toast(`Loaded ${info.filename}. It applies to every reporting triaged from now on.`, 'ok');
    } finally {
      e.target.value = '';   // let the same file be picked again
    }
  });

  $('#btnInstrTemplate').addEventListener('click', () => {
    const editor = $('#instrEditor');
    if (editor.value.trim() && !confirm('Replace what is in the box with the template?')) return;
    editor.value = editor.dataset.template || '';
  });

  $('#btnInstrClear').addEventListener('click', async () => {
    if (!confirm('Remove the triage instructions?\n\nTriage falls back to the scoring rules alone.')) return;
    await api.deleteInstructions();
    await loadInstructions();
    toast('Instructions removed.', 'ok');
  });

  $('#btnInstrSave').addEventListener('click', () => saveInstructions(false));
  $('#btnInstrRetriage').addEventListener('click', () => saveInstructions(true));
}


// ------------------------------------------------- administrative timetable

async function loadObligations() {
  const info = await api.getObligations();
  $('#obEditor').value = info.text || '';
  $('#obStatus').textContent = info.present
    ? `${info.count} obligations · ${info.path}`
    : 'No timetable loaded — the queue shows reportings only.';

  const rows = info.rows || [];
  $('#obList').innerHTML = rows.length ? rows.map((o) => {
    const urg = o.done ? 'done' : urgencyOf(o.due_at);
    return `<div class="ob-item">
      <div class="ob-item-head">
        <span class="ob-tag">${esc(o.short_label)}</span>
        <span class="urg urg-${urg}">${esc(URGENCY_LABEL[urg] || urg)}</span>
        <span class="dim">${esc(stamp(o.due_at))}</span>
        <span class="dim">${esc(o.done ? '' : countdown(o.due_at))}</span>
        ${o.score_bearing ? '<span class="chip chip-alert">Scored</span>' : ''}
      </div>
      <div>${esc(o.label)}</div>
      <div class="ob-item-meta">${
        [o.owner_role, o.audience, o.shift_ref, o.id].filter(Boolean).map(esc).join(' · ')}</div>
    </div>`;
  }).join('') : '';
}

function initObligations() {
  $('#obFile').addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    try {
      const info = await api.uploadObligations(file);
      toast(`Loaded ${info.count} obligations from ${info.filename}.`, 'ok');
      await loadObligations();
      (await import('./queue.js')).refresh();
    } finally {
      e.target.value = '';
    }
  });

  $('#btnObExample').addEventListener('click', async () => {
    const res = await fetch('/static/obligations.example.json');
    const text = await res.text();
    $('#obEditor').value = text;
    await api.putObligations(text);
    toast('Example timetable loaded.', 'ok');
    await loadObligations();
    (await import('./queue.js')).refresh();
  });

  $('#btnObClear').addEventListener('click', async () => {
    if (!confirm('Remove the administrative timetable?')) return;
    await api.deleteObligations();
    await loadObligations();
    toast('Timetable removed.', 'ok');
    (await import('./queue.js')).refresh();
  });

  $('#btnObSave').addEventListener('click', async () => {
    try {
      const info = await api.putObligations($('#obEditor').value);
      toast(`Saved ${info.count} obligations.`, 'ok');
      await loadObligations();
      (await import('./queue.js')).refresh();
    } catch { /* toast already shown */ }
  });
}
