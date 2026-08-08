// The queue: one row per event, in the column order an operator scans.
//
// Received · Location · Category · Potential loss of life · Triage status.
// Deliberately no description column — it is per-reporting, it is long, and a
// consolidated row has several of them. It lives in the expanded view instead,
// which is the only place the individual reportings appear.
//
// Rows that consolidate several reportings carry a disclosure caret. Expanding
// one shows the event description and every source under it.

import * as api from './api.js';
import { CHANNELS, PRIORITIES, URGENCY_LABEL, countdown, esc, stamp,
         timeAgo, toast, urgencyOf, $ } from './util.js';
import { openDetail } from './detail.js';

const LIFE_RISK_ORDER = ['confirmed', 'likely', 'possible', 'none'];
const expanded = new Set();
let rows = [];

export function init() {
  const f = api.state.filters;
  const debounce = (fn, ms = 220) => {
    let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  };

  $('#searchBox').addEventListener('input', debounce((e) => {
    f.q = e.target.value.trim(); refresh();
  }));
  $('#filterPriority').addEventListener('change', (e) => { f.priority = e.target.value; refresh(); });
  $('#filterUnack').addEventListener('change', (e) => { f.unacknowledged = e.target.checked; refresh(); });
  $('#filterDone').addEventListener('change', (e) => { f.includeDone = e.target.checked; refresh(); });
  $('#btnRefresh').addEventListener('click', () => refresh(true));
  $('#btnCsv').addEventListener('click', downloadCsv);
}

function csvQuery() {
  const f = api.state.filters;
  const p = new URLSearchParams();
  if (f.q) p.set('q', f.q);
  if (f.priority) p.set('priority', f.priority);
  if (f.unacknowledged) p.set('unacknowledged', 'true');
  p.set('include_done', 'true');
  return p.toString();
}

function downloadCsv() {
  window.open('/api/v1/consolidated.csv?' + csvQuery(), '_blank');
}

export async function refresh(announce = false) {
  const [list, counts] = await Promise.all([api.consolidated(), api.stats()]);
  rows = list.rows;                       // events and obligations, interleaved
  api.state.groups = list.groups;
  renderStats(counts, list);
  renderTable(rows);
  $('#tabCountQueue').textContent = list.count;
  if (announce) {
    toast(`${list.count} events from ${list.reportings} reportings`
        + (list.obligations ? `, ${list.obligations} obligations outstanding` : ''), 'ok');
  }
  return list;
}

function renderStats(s, list) {
  const p = s.by_priority || {};
  const f = api.state.filters;
  const tile = (cls, n, label, active, onClick) => {
    const node = document.createElement('button');
    node.className = `stat stat-${cls}` + (active ? ' is-on' : '');
    node.innerHTML = `<span class="stat-n">${n || 0}</span><span class="stat-l">${label}</span>`;
    node.addEventListener('click', onClick);
    return node;
  };

  $('#statRow').replaceChildren(
    tile('action', p.action_required, 'Action required',
      f.priority === 'action_required', () => setPriorityFilter('action_required')),
    tile('verify', p.verification_required, 'Verification required',
      f.priority === 'verification_required', () => setPriorityFilter('verification_required')),
    tile('aware', p.situational_awareness, 'Situational awareness',
      f.priority === 'situational_awareness', () => setPriorityFilter('situational_awareness')),
    tile('unack', s.unacknowledged, 'Never opened', f.unacknowledged, () => {
      f.unacknowledged = !f.unacknowledged;
      $('#filterUnack').checked = f.unacknowledged;
      refresh();
    }),
  );

  const ob = list.obligation_summary || {};
  $('#queueCounts').innerHTML =
    `${list.count} event${list.count === 1 ? '' : 's'} · ${list.reportings} reportings`
    + (list.obligations
        ? ` · <span class="ob-count${ob.overdue ? ' is-late' : ''}">${list.obligations} obligation${
            list.obligations === 1 ? '' : 's'}${ob.overdue ? `, ${ob.overdue} overdue` : ''}</span>`
        : '');

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

// ------------------------------------------------------------------ cells

function locationCell(g) {
  if (!g.location) {
    return '<span class="dim" title="Cannot be tasked to a crew without a location">no location</span>';
  }
  const inferred = g.location_precise
    ? ''
    : ' <span class="inferred" title="Inferred from the wording, not supplied by the reporter">inferred</span>';
  return esc(g.location) + inferred;
}

function lifeRiskCell(g) {
  return `<span class="risk risk-${g.life_risk}">${esc(g.life_risk_label)}</span>`;
}

function prioritySelect(g) {
  const opts = Object.entries(PRIORITIES).map(([k, v]) =>
    `<option value="${k}" ${k === g.priority ? 'selected' : ''}>${esc(v.label)}</option>`
  ).join('');
  return `<select class="pri-select pri-${g.priority}" data-priority-for="${esc(g.cluster_id)}"
            title="${g.priority_overridden ? 'Set by an operator' : 'Assigned automatically'}">
            ${opts}</select>`
    + (g.priority_overridden ? '<span class="by-hand" title="Overridden by an operator">✓</span>' : '');
}

function flags(g) {
  const out = [];
  if (!g.acknowledged) out.push('<span class="chip chip-unseen">Never opened</span>');
  if (g.flagged_false) out.push('<span class="chip chip-alert">Assessed false</span>');
  if (g.assigned_to) out.push(`<span class="chip">→ ${esc(g.assigned_to)}</span>`);
  return out.join('');
}

function row(g) {
  const open = expanded.has(g.cluster_id);
  const tr = document.createElement('tr');
  tr.className = 'qrow' + (g.done ? ' is-done' : '') + (open ? ' is-open' : '');
  tr.dataset.priority = g.priority;
  tr.dataset.cluster = g.cluster_id;

  tr.innerHTML = `
    <td class="c-expand">
      <button class="caret${g.consolidated ? ' has-many' : ''}"
              data-toggle="${esc(g.cluster_id)}"
              title="${g.consolidated
                ? `${g.sources} reportings consolidated — click to read them`
                : 'Click to read the reporting'}"
              aria-expanded="${open}">${open ? '▾' : '▸'}${
        g.consolidated ? `<span class="n">${g.sources}</span>` : ''}</button>
    </td>
    <td class="c-time" title="${esc(stamp(g.received_at))}">
      ${esc(stamp(g.received_at))}<span class="ago">${esc(timeAgo(g.received_at))}</span>
    </td>
    <td class="c-loc">${locationCell(g)}</td>
    <td class="c-cat">${esc(g.category_label)}</td>
    <td class="c-risk">${lifeRiskCell(g)}</td>
    <td class="c-pri">${prioritySelect(g)}</td>
    <td class="c-flags">${flags(g)}</td>
    <td class="c-act">
      <button class="btn btn-sm ${g.done ? 'btn-ghost' : 'btn-done'}"
              data-done-for="${esc(g.cluster_id)}" data-done="${g.done}">
        ${g.done ? 'Reopen' : 'Mark done'}</button>
    </td>`;
  return tr;
}

function detailRow(g) {
  const tr = document.createElement('tr');
  tr.className = 'qrow-detail';
  // On a single-source row the description and the source text are the same
  // words. Print them once and let the source card carry only its provenance.
  const echoes = (m) => !g.consolidated
    && (m.description || '').trim() === (g.description || '').trim();
  const members = g.members.map((m) => `
    <div class="src" data-open-reporting="${esc(m.id)}">
      <div class="src-head">
        <span class="chip">${esc(CHANNELS[m.channel] || m.channel)}</span>
        ${m.source_system ? `<span class="dim">${esc(m.source_system)}</span>` : ''}
        <span class="dim">${esc(stamp(m.received_at))}</span>
        <span class="pri pri-${m.priority}">${esc(PRIORITIES[m.priority]?.short || m.priority)}</span>
        ${m.acknowledged_by ? '' : '<span class="chip chip-unseen">Never opened</span>'}
        ${m.has_media ? '<span class="chip">media</span>' : ''}
      </div>
      ${echoes(m) ? '' : `<div class="src-text">${esc(m.description || '(no text)')}</div>`}
      <div class="src-meta">
        ${m.location ? esc(m.location) : 'no location'} ·
        ${esc(m.status)} ·
        ${m.permalink ? `<a href="${esc(m.permalink)}" target="_blank" rel="noopener">source ↗</a>` : 'no source link'}
        · <span class="link">open full record →</span>
      </div>
    </div>`).join('');

  tr.innerHTML = `
    <td></td>
    <td colspan="7" class="detail-cell">
      <div class="ev-desc">
        <span class="ev-label">What happened</span>
        ${esc(g.description || '(no description)')}
      </div>
      <div class="ev-sources">
        <span class="ev-label">${g.consolidated
          ? `${g.sources} reportings consolidated — same place, same register, same category`
          : 'Source'}</span>
        ${members}
      </div>
    </td>`;
  return tr;
}

function renderTable(list) {
  const body = $('#queueBody');
  if (!list.length) {
    body.innerHTML = '<tr><td colspan="8" class="empty">Nothing matches these filters.</td></tr>';
    return;
  }
  const frag = document.createDocumentFragment();
  list.forEach((r) => {
    const isOb = r.kind === 'obligation';
    frag.appendChild(isOb ? obligationRow(r) : row(r));
    if (expanded.has(r.cluster_id)) {
      frag.appendChild(isOb ? obligationDetail(r) : detailRow(r));
    }
  });
  body.replaceChildren(frag);
  wire(body);
  tickCountdowns();
}

// ------------------------------------------------------- obligation rows

/**
 * An administrative obligation: due at a time rather than triggered by an
 * event. Pink so it never reads as a reporting, and placed by how close its
 * deadline is — but the server caps it below every action-required reporting,
 * so paperwork can't outrank someone in the water.
 */
function obligationRow(o) {
  const open = expanded.has(o.cluster_id);
  const tr = document.createElement('tr');
  tr.className = 'qrow qrow-ob' + (o.done ? ' is-done' : '') + (open ? ' is-open' : '');
  tr.dataset.urgency = o.urgency;
  tr.dataset.cluster = o.cluster_id;
  tr.dataset.due = o.due_at || '';

  tr.innerHTML = `
    <td class="c-expand">
      <button class="caret" data-toggle="${esc(o.cluster_id)}"
              title="Click for the detail" aria-expanded="${open}">${open ? '▾' : '▸'}</button>
    </td>
    <td class="c-time" title="Due ${esc(stamp(o.due_at))}">
      ${esc(stamp(o.due_at))}
      <span class="ago countdown" data-due="${esc(o.due_at || '')}">${esc(o.countdown)}</span>
    </td>
    <td class="c-loc">
      <span class="ob-tag">${esc(o.short_label)}</span>
      ${esc(o.label)}
    </td>
    <td class="c-cat">${esc(o.owner_role || '—')}</td>
    <td class="c-risk">
      <span class="urg urg-${o.urgency}" data-urg-for="${esc(o.cluster_id)}">${
        esc(o.urgency_label)}</span>
    </td>
    <td class="c-pri"><span class="ob-kind">Administrative obligation</span></td>
    <td class="c-flags">
      ${o.score_bearing ? '<span class="chip chip-alert">Scored</span>' : ''}
      ${o.audience && o.audience !== 'internal'
        ? `<span class="chip">${esc(o.audience)}</span>` : ''}
      ${o.shift_ref ? `<span class="chip">${esc(o.shift_ref)}</span>` : ''}
    </td>
    <td class="c-act">
      <button class="btn btn-sm ${o.done ? 'btn-ghost' : 'btn-done'}"
              data-ob-done="${esc(o.id)}" data-done="${o.done}">
        ${o.done ? 'Reopen' : 'Mark done'}</button>
    </td>`;
  return tr;
}

function obligationDetail(o) {
  const tr = document.createElement('tr');
  tr.className = 'qrow-detail qrow-detail-ob';
  const facts = [
    ['Due', stamp(o.due_at)],
    ['Owner', o.owner_role],
    ['Audience', o.audience],
    ['Shift', o.shift_ref],
    ['Type', o.type],
    ['Scored', o.score_bearing ? 'Yes — late submission counts against the response' : 'No'],
    ['Reference', o.id],
  ].filter(([, v]) => v).map(([k, v]) =>
    `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('');

  tr.innerHTML = `
    <td></td>
    <td colspan="7" class="detail-cell">
      <div class="ev-desc ev-desc-ob">
        <span class="ev-label">Obligation</span>
        ${esc(o.label)}
        ${o.notes ? `<div class="ob-notes">${esc(o.notes)}</div>` : ''}
      </div>
      <dl class="d-grid">${facts}</dl>
      ${o.done ? `<div class="ob-done">Discharged by ${esc(o.done_by || 'unknown')}
        at ${esc(stamp(o.done_at))}${o.done_note ? ` — “${esc(o.done_note)}”` : ''}</div>` : ''}
    </td>`;
  return tr;
}

/** Re-render the countdown text every second without refetching. */
export function tickCountdowns() {
  document.querySelectorAll('.countdown[data-due]').forEach((el) => {
    const due = el.dataset.due;
    if (!due) return;
    el.textContent = countdown(due);
  });
  document.querySelectorAll('.qrow-ob[data-due]').forEach((tr) => {
    const urg = urgencyOf(tr.dataset.due);
    if (tr.dataset.urgency === urg) return;
    tr.dataset.urgency = urg;              // crossed a band between polls
    const badge = tr.querySelector('.urg');
    if (badge) {
      badge.className = `urg urg-${urg}`;
      badge.textContent = URGENCY_LABEL[urg] || urg;
    }
  });
}

// ----------------------------------------------------------------- actions

function wire(body) {
  body.querySelectorAll('[data-toggle]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.dataset.toggle;
      if (expanded.has(id)) expanded.delete(id);
      else {
        expanded.add(id);
        // Opening the group counts as opening everything under it.
        api.acknowledgeGroup(id).then(() => refresh()).catch(() => {});
      }
      renderTable(rows);
    });
  });

  body.querySelectorAll('[data-priority-for]').forEach((sel) => {
    sel.addEventListener('click', (e) => e.stopPropagation());
    sel.addEventListener('change', async () => {
      const id = sel.dataset.priorityFor;
      const g = rows.find((x) => x.cluster_id === id);
      const priority = sel.value;
      const reason = prompt(
        `Why are you setting this to "${PRIORITIES[priority].label}"?\n\n`
        + (g && g.sources > 1
            ? `This applies to all ${g.sources} reportings in the group.\n`
            : '')
        + 'Recorded against your name and shown in the handover.');
      if (reason === null) { sel.value = g ? g.priority : sel.value; return; }
      await api.setGroupPriority(id, priority, reason || null);
      toast('Priority updated and recorded.', 'ok');
      refresh();
    });
  });

  body.querySelectorAll('[data-done-for]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.dataset.doneFor;
      const wasDone = btn.dataset.done === 'true';
      const g = rows.find((x) => x.cluster_id === id);
      const note = prompt(
        wasDone ? 'Why are you reopening this?'
                : `Mark this event done?\n\n`
                  + (g && g.sources > 1 ? `Closes all ${g.sources} reportings in the group.\n` : '')
                  + 'Add a note (optional):');
      if (note === null) return;
      await api.setGroupDone(id, !wasDone, note || null);
      toast(wasDone ? 'Reopened.' : 'Marked done.', 'ok');
      refresh();
    });
  });

  body.querySelectorAll('[data-ob-done]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.dataset.obDone;
      const wasDone = btn.dataset.done === 'true';
      const note = prompt(wasDone
        ? 'Why are you reopening this obligation?'
        : 'Mark this obligation discharged. Add a note (optional):');
      if (note === null) return;
      await api.setObligationDone(id, !wasDone, note || null);
      toast(wasDone ? 'Obligation reopened.' : 'Obligation discharged.', 'ok');
      refresh();
    });
  });

  body.querySelectorAll('[data-open-reporting]').forEach((node) => {
    node.addEventListener('click', () => select(node.dataset.openReporting));
  });

  // Clicking anywhere else on a row opens the primary reporting's full record.
  body.querySelectorAll('.qrow').forEach((tr) => {
    tr.addEventListener('click', () => {
      const r = rows.find((x) => x.cluster_id === tr.dataset.cluster);
      if (!r) return;
      if (r.kind === 'obligation') {
        // Nothing to open in the detail pane — expand it in place instead.
        const btn = tr.querySelector('[data-toggle]');
        if (btn) btn.click();
        return;
      }
      select(r.primary_id);
    });
  });
}

export async function select(id) {
  api.state.selectedId = id;
  document.querySelectorAll('.qrow').forEach((n) => {
    const g = rows.find((x) => x.cluster_id === n.dataset.cluster);
    n.classList.toggle('is-selected',
      !!g && g.kind === 'event' && g.members.some((m) => m.id === id));
  });
  await openDetail(id);
}

/** Open the group containing a reporting, used by the map / audit / handover. */
export async function focusReporting(id) {
  const g = rows.find((x) => x.kind === 'event' && x.members.some((m) => m.id === id));
  if (g && g.consolidated) {
    expanded.add(g.cluster_id);
    renderTable(rows);
  }
  await select(id);
}
