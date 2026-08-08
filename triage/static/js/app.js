// Bootstrap: tabs, the shift bar, and the polling loop.

import * as api from './api.js';
import * as queue from './queue.js';
import * as detail from './detail.js';
import * as mapView from './map.js';
import * as handover from './handover.js';
import * as auditView from './audit.js';
import * as settings from './settings.js';
import { stamp, timeAgo, toast, $, $$ } from './util.js';

let activeTab = 'queue';
let poll = null;

// Jumping to a reporting from the map, the audit log or the handover always
// lands in the same place: the queue, with the detail pane open.
async function openReporting(id) {
  showTab('queue');
  await queue.select(id);
  document.querySelector(`.rep[data-id="${id}"]`)
    ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
}

function showTab(name) {
  activeTab = name;
  $$('.tab').forEach((t) => t.classList.toggle('is-active', t.dataset.tab === name));
  $$('.panel').forEach((p) => p.classList.toggle('is-active', p.id === `panel-${name}`));
  if (name === 'map') mapView.show();
  if (name === 'audit') auditView.show();
  if (name === 'settings') settings.show();
}

export async function refreshShift() {
  const { open } = await api.shifts();
  api.state.shift = open;
  if (open) {
    // Keep the client's operator aligned with whoever is actually on shift, so
    // audit events are not attributed to the last person who used this browser.
    if (open.operator !== api.state.operator) api.setOperator(open.operator);
    $('#shiftOperator').textContent = open.operator;
    $('#shiftSince').textContent = `since ${stamp(open.started_at)} · ${timeAgo(open.started_at).replace(' ago', '')}`;
  } else {
    $('#shiftOperator').textContent = api.state.operator;
    $('#shiftSince').textContent = 'no shift open — click to start one';
  }
}

async function changeOperator() {
  const name = prompt(
    'Who is on shift?\n\n'
    + 'Everything you do from here is recorded against this name and grouped\n'
    + 'into this shift for the handover briefing.',
    api.state.operator);
  if (!name || !name.trim()) return;
  const role = prompt('Role:', api.state.shift?.role || 'Duty controller') || 'Duty controller';
  api.setOperator(name.trim());
  await api.startShift(name.trim(), role, `${name.trim()} came on shift.`);
  await refreshShift();
  toast(`${name.trim()} is on shift. Any previous shift was closed.`, 'ok');
  auditView.loadShifts();
}

async function tick() {
  if (activeTab === 'queue') await queue.refresh();
  else if (activeTab === 'map') await mapView.refresh();
}

async function boot() {
  $$('.tab').forEach((t) => t.addEventListener('click', () => showTab(t.dataset.tab)));
  $('#shiftOperator').addEventListener('click', changeOperator);

  queue.init({});
  detail.init({ afterChange: ({ silent } = {}) => { if (!silent) queue.refresh(); } });
  mapView.init({ onOpen: openReporting });
  handover.init({ onOpen: openReporting });
  auditView.init({ onOpen: openReporting });
  settings.init();

  await refreshShift();

  const health = await api.health();
  if (!health.reportings) {
    toast('No reportings yet. Load the demo corpus from Settings, or POST to /api/v1/ingest.');
  }
  await queue.refresh();

  // config/settings.yaml owns this. It was hard-coded to 10 here, which is far
  // too slow to watch a replay: the whole night arrives in under two minutes.
  let seconds = 2;
  try {
    const cfg = await api.getConfig('settings');
    const configured = Number(cfg?.parsed?.ui?.refresh_seconds);
    if (Number.isFinite(configured) && configured > 0) seconds = configured;
  } catch { /* the default above is fine */ }
  poll = setInterval(tick, seconds * 1000);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { clearInterval(poll); }
    else { tick(); poll = setInterval(tick, seconds * 1000); }
  });
}

boot();
