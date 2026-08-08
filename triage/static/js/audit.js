// The audit tab: one stream of everything that has happened, filterable by
// shift. Machine events are dimmed so human decisions read first.

import * as api from './api.js';
import { actionWords, esc, stamp, $ } from './util.js';

let onOpen = () => {};

const ACTIONS = [
  'acknowledged', 'priority_overridden', 'status_changed', 'marked_false',
  'cluster_flagged_false', 'note_added', 'assigned', 'forwarded',
  'forward_failed', 'linked_duplicate', 'ingested', 'triaged', 'retriaged',
  'shift_started', 'shift_ended', 'handover_generated', 'config_changed',
  'ruleset_generated',
];

export function init(handlers = {}) {
  onOpen = handlers.onOpen || onOpen;

  const sel = $('#auditAction');
  ACTIONS.forEach((a) => {
    sel.appendChild(new Option(actionWords(a).replace(/^\w/, (c) => c.toUpperCase()), a));
  });

  $('#auditShift').addEventListener('change', refresh);
  $('#auditAction').addEventListener('change', refresh);
  $('#auditHumans').addEventListener('change', refresh);
  $('#btnAuditRefresh').addEventListener('click', refresh);
}

export async function loadShifts() {
  const { shifts } = await api.shifts();
  const sel = $('#auditShift');
  const keep = sel.value;
  sel.replaceChildren(new Option('All activity (most recent first)', ''));
  shifts.forEach((s) => {
    const label = `${s.operator} · ${stamp(s.started_at)}${s.ended_at ? ' → ' + stamp(s.ended_at) : ' (open)'}`;
    sel.appendChild(new Option(label, s.id));
  });
  sel.value = keep;
}

export async function refresh() {
  const { events } = await api.auditFeed({
    shiftId: $('#auditShift').value || null,
    action: $('#auditAction').value || null,
    humansOnly: $('#auditHumans').checked,
  });

  const list = $('#auditList');
  if (!events.length) {
    list.innerHTML = '<div class="empty">Nothing recorded for this filter.</div>';
    return;
  }

  list.innerHTML = events.map((e) => {
    const change = (e.from_value || e.to_value)
      ? ` <span class="tl-chg">${esc(e.from_value ?? '—')} → ${esc(e.to_value ?? '—')}</span>` : '';
    return `<div class="aud" data-open="${esc(e.reporting_id || '')}">
      <div class="aud-when">${stamp(e.at)}</div>
      <div class="aud-who ${e.is_human ? '' : 'machine'}">${esc(e.actor)}</div>
      <div>
        <div class="aud-act">${esc(actionWords(e.action))}${change}</div>
        ${e.note ? `<div class="aud-note">“${esc(e.note)}”</div>` : ''}
        ${e.excerpt ? `<div class="aud-ref">${esc(e.reporting_id)} — ${esc(e.excerpt)}</div>` : ''}
      </div>
    </div>`;
  }).join('');

  list.querySelectorAll('[data-open]').forEach((node) => {
    const id = node.dataset.open;
    if (!id) return;
    node.addEventListener('click', () => onOpen(id));
  });
}

export async function show() {
  await loadShifts();
  await refresh();
}
