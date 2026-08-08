// Shift handover briefing.
//
// Sections are ordered by how badly the incoming controller needs them, and
// the first one is the reason the whole thing exists: reportings nobody ever
// opened. Every item is clickable through to the reporting and its audit
// trail, so the briefing is a route into the record rather than a copy of it.

import * as api from './api.js';
import { CHANNELS, PRIORITIES, esc, stamp, toast, $ } from './util.js';

let onOpen = () => {};
let latest = null;

export function init(handlers = {}) {
  onOpen = handlers.onOpen || onOpen;

  $('#btnHandoverPreview').addEventListener('click', () => build(false));
  $('#btnHandoverSave').addEventListener('click', () => build(true));
  $('#btnHandoverPdf').addEventListener('click', exportPdf);
  $('#btnEndShift').addEventListener('click', endShiftFlow);
  $('#handoverShift').addEventListener('change', () => build(false));
  loadShifts();
}

/** Which shift the briefing is about — the open one unless a past one is picked. */
const chosenShift = () => $('#handoverShift').value || null;

/**
 * The shift picker. A handover is usually written about the shift that has
 * just ended, so the list has to reach back past the open one.
 */
export async function loadShifts() {
  const { shifts } = await api.shifts();
  const sel = $('#handoverShift');
  const keep = sel.value;
  sel.replaceChildren(new Option('Current shift', ''));
  shifts.forEach((s) => {
    sel.appendChild(new Option(
      `${s.operator} · ${stamp(s.started_at)}`
      + (s.ended_at ? ` → ${stamp(s.ended_at)}` : ' (open)'), s.id));
  });
  sel.value = keep;
}

async function build(save) {
  const useLLM = $('#handoverLLM').checked;
  const body = $('#handoverBody');
  body.innerHTML = `<p class="muted pad">Building the briefing${useLLM ? ' and asking the local model for a summary — this takes a moment' : ''}…</p>`;
  try {
    const res = save
      ? await api.handoverGenerate({ use_llm: useLLM, shift_id: chosenShift() })
      : await api.handoverPreview(useLLM, chosenShift());
    latest = res;
    render(res.briefing, res.id);
    if (save) toast('Briefing saved and recorded in the audit trail.', 'ok');
  } catch {
    body.innerHTML = '<p class="muted pad">Could not build the briefing.</p>';
  }
}

/**
 * The shift report as an A4 PDF: what the incoming controller picks up first,
 * then every decision the outgoing shift made, read straight off the audit
 * trail. Saved briefings export the document that was filed; anything else is
 * built fresh for the selected shift.
 */
function exportPdf() {
  const useLLM = $('#handoverLLM').checked;
  const url = latest && latest.id
    ? `/api/v1/handover/${encodeURIComponent(latest.id)}/pdf`
    : api.handoverPdfUrl(useLLM, chosenShift());
  window.open(url, '_blank');
  toast('Building the shift report…');
}

async function endShiftFlow() {
  const note = prompt(
    'Anything to tell the person coming on that is not already in the queue?\n\n'
    + 'This goes at the end of the briefing.');
  if (note === null) return;
  const useLLM = $('#handoverLLM').checked;
  const res = await api.handoverGenerate({ use_llm: useLLM, end_shift: true, note });
  latest = res;
  render(res.briefing, res.id);
  toast('Shift closed and the briefing saved. Set the incoming operator in the top right.', 'ok');
  await loadShifts();
  // Leave the picker on the shift that just ended: that is the one the
  // incoming controller wants the report for.
  if (res.briefing?.shift?.id) $('#handoverShift').value = res.briefing.shift.id;
  const { refreshShift } = await import('./app.js');
  refreshShift();
}

// --------------------------------------------------------------- rendering

function item(card, extra = '') {
  return `<div class="hv-item" data-priority="${esc(card.priority)}" data-open="${esc(card.id)}">
    <div class="t">${esc(card.excerpt || '(no text)')}</div>
    <div class="m">
      ${esc(PRIORITIES[card.priority]?.short || card.priority)} ·
      ${esc(CHANNELS[card.channel] || card.channel)} ·
      ${esc(card.location)} · ${esc(card.age)} · ${esc(card.status)}
      ${card.assigned_to ? '· assigned ' + esc(card.assigned_to) : ''}
    </div>
    ${extra ? `<div class="x">${extra}</div>` : ''}
  </div>`;
}

function section(title, sub, cards, empty, extraFn, critical = false) {
  const rows = cards.length
    ? cards.map((c) => item(c, extraFn ? extraFn(c) : '')).join('')
    : `<div class="hv-none">${esc(empty)}</div>`;
  return `<div class="hv-sec${critical ? ' crit' : ''}">
    <h3>${esc(title)} <span class="count">${cards.length}</span></h3>
    ${sub ? `<p class="sub">${esc(sub)}</p>` : ''}
    ${rows}
  </div>`;
}

function render(b, savedId) {
  const t = b.totals;
  const s = b.shift;
  const llm = b.llm_summary || {};

  const tiles = [
    ['crit', t.never_acknowledged, 'Never opened by anyone'],
    ['', t.open_action_required, 'Open — action required'],
    ['', t.open_verification_required, 'Open — verification required'],
    ['', t.received_this_shift, 'Received this shift'],
    ['', t.human_decisions_this_shift, 'Operator decisions'],
  ].map(([cls, n, l]) => `<div class="hv-tile ${cls}"><div class="n">${n}</div><div class="l">${esc(l)}</div></div>`).join('');

  const summary = llm.summary ? `
    <div class="hv-summary">
      <div>${esc(llm.summary)}</div>
      ${llm.watch_items?.length ? `<ul>${llm.watch_items.map((i) => `<li>${esc(i)}</li>`).join('')}</ul>` : ''}
      <div class="ai-note">Drafted by ${esc(llm.model || 'a local model')} from the
        lists below. The lists are the record; this paragraph is a convenience and
        has not been checked.</div>
    </div>` : (llm.error ? `<div class="banner banner-warn">Summary unavailable: ${esc(llm.error)}. The briefing below is unaffected.</div>` : '');

  const decisions = b.decisions.length ? `
    <div class="hv-sec">
      <h3>Every operator decision this shift <span class="count">${b.decisions.length}</span></h3>
      <p class="sub">The full judgement record, in order. This is what the audit
        trail contains — the briefing just arranges it.</p>
      <table class="hv-table">
        <thead><tr><th>Time</th><th>Operator</th><th>Did what</th><th>Change</th><th>Reason given</th></tr></thead>
        <tbody>${b.decisions.map((d) => `
          <tr data-open="${esc(d.reporting_id || '')}" style="cursor:${d.reporting_id ? 'pointer' : 'default'}">
            <td class="mono">${stamp(d.at)}</td>
            <td class="mono">${esc(d.actor)}</td>
            <td>${esc(d.action.replace(/_/g, ' '))}</td>
            <td class="mono">${d.from || d.to ? `${esc(d.from ?? '—')} → ${esc(d.to ?? '—')}` : ''}</td>
            <td>${esc(d.note || '')}</td>
          </tr>`).join('')}</tbody>
      </table>
    </div>` : '';

  $('#handoverBody').innerHTML = `
    <div class="hv-summary" style="border-left-color:var(--line)">
      <strong>Outgoing:</strong> ${esc(s.operator || 'unknown')} (${esc(s.role || 'operator')}) ·
      <strong>Shift:</strong> ${stamp(s.started_at)} → ${s.ended_at ? stamp(s.ended_at) : 'still open'}
      ${savedId ? `· <span class="muted">saved as ${esc(savedId)} · <a href="/api/v1/handover/${esc(savedId)}/markdown" target="_blank" rel="noopener">markdown</a></span>` : ''}
    </div>

    ${summary}
    <div class="hv-tiles">${tiles}</div>

    ${section('Never opened — nobody has looked at these',
      'The reason this briefing exists. Sorted by priority. Opening one marks it seen.',
      b.never_acknowledged, 'Everything open has been seen by someone.', null, true)}

    ${section('Open and action required', 'Live work to pick up first.',
      b.open_action_required, 'Nothing outstanding at action level.')}

    ${section('Stalled — opened, then nothing happened',
      'Someone started on these and did not come back.',
      b.stalled, 'Nothing has gone quiet.',
      (c) => `idle ${c.idle_minutes} min · last: ${esc(c.last_action)}${c.last_note ? ` — “${esc(c.last_note)}”` : ''}`)}

    ${section('Awaiting verification', 'Leads someone has to chase down.',
      b.awaiting_verification, 'No open verification tasks.')}

    ${section('Forwarded — no reply yet',
      'We asked another agency and have not heard back.',
      b.forwarded_awaiting_reply, 'No outstanding forwards.',
      (c) => `sent to ${esc(c.destination)} (${esc(c.target)}) by ${esc(c.sent_by)}, waiting ${c.waiting_minutes} min${c.dry_run ? ' · dry run' : ''}`)}

    ${section('Ruled out this shift — do not rework',
      'Already assessed as false. Listed so the next shift does not start again.',
      b.ruled_out_this_shift, 'Nothing was assessed as a false reporting this shift.',
      (c) => `marked false by ${esc(c.marked_by)}${c.reason ? ` — “${esc(c.reason)}”` : ''}`)}

    ${b.priority_overrides.length ? `
      <div class="hv-sec">
        <h3>Priorities an operator changed <span class="count">${b.priority_overrides.length}</span></h3>
        <p class="sub">Where a human disagreed with the automated assessment, and why.</p>
        ${b.priority_overrides.map((o) => `
          <div class="hv-item" data-open="${esc(o.reporting_id)}">
            <div class="t">${esc(o.excerpt || o.reporting_id)}</div>
            <div class="m">${esc(o.from)} → ${esc(o.to)} · ${esc(o.actor)} · ${stamp(o.at)}</div>
            ${o.note ? `<div class="x">“${esc(o.note)}”</div>` : ''}
          </div>`).join('')}
      </div>` : ''}

    ${decisions}

    ${s.handover_note ? `
      <div class="hv-sec">
        <h3>Note from the outgoing operator</h3>
        <div class="hv-summary">${esc(s.handover_note)}</div>
      </div>` : ''}`;

  $('#handoverBody').querySelectorAll('[data-open]').forEach((node) => {
    const id = node.dataset.open;
    if (!id) return;
    node.addEventListener('click', () => onOpen(id));
  });
}
