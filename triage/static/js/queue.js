// The queue: every reporting, ordered the way an operator should work it.
//
// Ordering comes from the server (priority, then never-opened, then score).
// The row's job is to answer three questions without a click: how urgent, has
// anyone touched it, and why did the machine put it here.

import * as api from './api.js';
import { CHANNELS, PRIORITIES, STATUSES, esc, timeAgo, toast, $ } from './util.js';
import { openDetail } from './detail.js';

let onSelect = () => {};

export function init(handlers = {}) {
  onSelect = handlers.onSelect || onSelect;

  const f = api.state.filters;
  const debounce = (fn, ms = 220) => {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  };

  $('#searchBox').addEventListener('input', debounce((e) => {
    f.q = e.target.value.trim(); refresh();
  }));
  $('#filterPriority').addEventListener('change', (e) => { f.priority = e.target.value; refresh(); });
  $('#filterChannel').addEventListener('change', (e) => { f.channel = e.target.value; refresh(); });
  $('#filterUnack').addEventListener('change', (e) => { f.unacknowledged = e.target.checked; refresh(); });
  $('#filterFalse').addEventListener('change', (e) => { f.showFalse = e.target.checked; refresh(); });
  $('#btnRefresh').addEventListener('click', () => refresh(true));
}

export async function refresh(announce = false) {
  const [list, counts] = await Promise.all([api.listReportings(), api.stats()]);
  api.state.reportings = list.reportings;
  renderStats(counts);
  renderList(list.reportings);
  $('#tabCountQueue').textContent = list.count;
  if (announce) toast(`${list.count} reportings`, 'ok');
  return list;
}

function renderStats(s) {
  const p = s.by_priority || {};
  const f = api.state.filters;
  const tile = (cls, n, label, active, onClick) => {
    const node = document.createElement('button');
    node.className = `stat stat-${cls}` + (active ? ' is-on' : '');
    node.innerHTML = `<span class="stat-n">${n || 0}</span><span class="stat-l">${label}</span>`;
    node.addEventListener('click', onClick);
    return node;
  };

  const row = $('#statRow');
  row.replaceChildren(
    tile('action', p.action_required, 'Action required',
      f.priority === 'action_required',
      () => setPriorityFilter('action_required')),
    tile('verify', p.verification_required, 'Verification required',
      f.priority === 'verification_required',
      () => setPriorityFilter('verification_required')),
    tile('aware', p.situational_awareness, 'Situational awareness',
      f.priority === 'situational_awareness',
      () => setPriorityFilter('situational_awareness')),
    tile('unack', s.unacknowledged, 'Never opened', f.unacknowledged, () => {
      f.unacknowledged = !f.unacknowledged;
      $('#filterUnack').checked = f.unacknowledged;
      refresh();
    }),
  );

  // The handover tab wears the count of things nobody has looked at, because
  // that is the number that decides whether you need to read the briefing.
  const badge = $('#tabBadgeHandover');
  badge.textContent = s.unacknowledged || 0;
  badge.hidden = !s.unacknowledged;
}

function setPriorityFilter(value) {
  const f = api.state.filters;
  f.priority = f.priority === value ? '' : value;
  $('#filterPriority').value = f.priority;
  refresh();
}

function chips(r) {
  const out = [];
  if (!r.acknowledged_by && r.status !== 'false_reporting') {
    out.push('<span class="chip chip-unseen">Never opened</span>');
  }
  if (r.cluster_flagged_false) {
    out.push('<span class="chip chip-alert">Group assessed false</span>');
  }
  if (r.status === 'false_reporting') {
    out.push('<span class="chip chip-alert">False reporting</span>');
  }
  if (r.priority_overridden) {
    out.push('<span class="chip chip-human">Set by an operator</span>');
  }
  if (r.disagreement) {
    out.push('<span class="chip chip-alert" title="' + esc(r.disagreement) + '">Rules ≠ model</span>');
  }
  if (r.cluster_size > 1) {
    out.push(`<span class="chip chip-cluster">${r.cluster_size} related</span>`);
  }
  if (r.forward_count) {
    out.push(`<span class="chip chip-ok">Forwarded ×${r.forward_count}</span>`);
  }
  if (!['new', 'acknowledged'].includes(r.status)) {
    out.push(`<span class="chip">${esc(STATUSES[r.status] || r.status)}</span>`);
  }
  if (r.has_media) out.push(`<span class="chip">${r.media_count} attachment${r.media_count > 1 ? 's' : ''}</span>`);
  return out.join('');
}

function row(r) {
  const node = document.createElement('article');
  node.className = 'rep' + (r.status === 'false_reporting' ? ' is-false' : '')
                 + (r.id === api.state.selectedId ? ' is-selected' : '');
  node.dataset.priority = r.priority;
  node.dataset.id = r.id;

  const where = r.location_text
    ? esc(r.location_text) + (r.location_precise ? '' : ' <span title="Location inferred from the wording, not supplied">(inferred)</span>')
    : '<span title="Cannot be tasked to a crew without a location">no location</span>';

  node.innerHTML = `
    <div class="rep-stripe"></div>
    <div class="rep-inner">
      <div class="rep-top">
        <span class="pri pri-${r.priority}">${PRIORITIES[r.priority]?.short || r.priority}</span>
        ${chips(r)}
      </div>
      <div class="rep-text">
        ${r.summary ? `<span class="sum">${esc(r.summary)}</span> — ` : ''}${esc(r.excerpt)}
      </div>
      <div class="rep-meta">
        <span>${esc(CHANNELS[r.channel] || r.channel)}${r.source_system ? ' · ' + esc(r.source_system) : ''}</span>
        <span>${where}</span>
        <span>${timeAgo(r.received_at)}</span>
        ${r.assigned_to ? `<span>→ ${esc(r.assigned_to)}</span>` : ''}
      </div>
      ${r.rationale ? `<div class="rep-why"><b>Why:</b> ${esc(r.rationale)}</div>` : ''}
    </div>`;

  node.addEventListener('click', () => select(r.id));
  return node;
}

function renderList(rows) {
  const list = $('#queueList');
  if (!rows.length) {
    list.innerHTML = '<div class="empty">No reportings match these filters.</div>';
    return;
  }
  const frag = document.createDocumentFragment();
  rows.forEach((r) => frag.appendChild(row(r)));
  list.replaceChildren(frag);
}

export async function select(id) {
  api.state.selectedId = id;
  document.querySelectorAll('.rep').forEach((n) => {
    n.classList.toggle('is-selected', n.dataset.id === id);
  });
  onSelect(id);
  await openDetail(id);
}
