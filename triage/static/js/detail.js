// Reporting detail: what came in, what the machine thought, what people did.
//
// Opening this pane acknowledges the reporting. That is deliberate — the whole
// value of "never opened" as a handover metric depends on it meaning somebody
// actually laid eyes on the thing.

import * as api from './api.js';
import {
  CHANNELS, PRIORITIES, STATUSES, actionWords, clock, esc, isAlert,
  stamp, timeAgo, toast, $, el,
} from './util.js';

let destinations = [];
let afterChange = () => {};
let current = null;

export function init(handlers = {}) {
  afterChange = handlers.afterChange || afterChange;
  api.destinations().then((d) => { destinations = d; }).catch(() => {});
}

export async function openDetail(id) {
  // Acknowledge first so the audit trail we then render already shows it.
  await api.acknowledge(id).catch(() => {});
  const data = await api.getReporting(id);
  current = data;
  render(data);
  $('#detailEmpty').hidden = true;
  $('#detailBody').hidden = false;
  afterChange({ silent: true });
}

async function act(fn) {
  try {
    await fn();
    const data = await api.getReporting(current.card.id);
    current = data;
    render(data);
    afterChange();
  } catch { /* toast already shown by api.call */ }
}

// --------------------------------------------------------------- rendering

function banners(d) {
  const c = d.card;
  const out = [];

  if (c.cluster_flagged_false) {
    out.push(`<div class="banner banner-false">
      <strong>A similar reporting was already assessed as false.</strong><br>
      ${esc(c.cluster_flag_reason || 'No reason recorded.')}
      This one is held back rather than dropped — check it, then close it or
      reverse the assessment.</div>`);
  }
  if (c.status === 'false_reporting') {
    out.push(`<div class="banner banner-false">
      <strong>Marked as a false reporting.</strong>
      ${esc(c.override_reason || '')}</div>`);
  }
  if (c.disagreement) {
    out.push(`<div class="banner banner-warn">
      <strong>The rules and the model disagreed.</strong> ${esc(c.disagreement)}
      The higher of the two was kept. Your call.</div>`);
  }
  if (c.priority_overridden) {
    out.push(`<div class="banner banner-info">
      <strong>Priority set by an operator</strong>, overriding the automated
      assessment of ${esc(PRIORITIES[c.machine_priority]?.label || c.machine_priority)}.
      ${c.override_reason ? 'Reason: ' + esc(c.override_reason) : ''}</div>`);
  }
  if (!c.has_coords) {
    out.push(`<div class="banner banner-warn">
      <strong>No location.</strong> This cannot be plotted or tasked to a crew
      until someone calls back for one.</div>`);
  } else if (!c.location_precise) {
    out.push(`<div class="banner banner-warn">
      <strong>Location inferred</strong> from the wording
      (${esc(c.location_method)}), not supplied by the reporter. Confirm before
      tasking anyone to it.</div>`);
  }
  return out.join('');
}

function contentBlocks(r) {
  const c = r.content || {};
  const out = [];
  if (c.subject) out.push(`<div class="d-quote"><span class="label">Subject</span>${esc(c.subject)}</div>`);
  if (c.transcript) out.push(`<div class="d-quote"><span class="label">Call transcript — verbatim</span>${esc(c.transcript)}</div>`);
  if (c.text) out.push(`<div class="d-quote"><span class="label">Text as received</span>${esc(c.text)}</div>`);
  (c.media || []).forEach((m) => {
    const bits = [`<span class="label">Attached ${esc(m.kind)}</span>`];
    if (m.caption) bits.push(esc(m.caption));
    if (m.model_caption) {
      bits.push(`<div class="muted" style="margin-top:5px">AI-generated caption
        (not the author's words): ${esc(m.model_caption)}</div>`);
    }
    if (m.url) bits.push(`<div style="margin-top:5px"><a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.url)}</a></div>`);
    out.push(`<div class="d-quote">${bits.join('')}</div>`);
  });
  if (!out.length) out.push('<div class="d-quote muted">No content was supplied.</div>');
  return out.join('');
}

function whyList(t) {
  if (!t || !t.signals?.length) {
    return '<p class="muted">No rules matched. Defaulted to situational awareness.</p>';
  }
  const rows = t.signals.map((s) => {
    const cls = s.score > 0 ? 'pos' : (s.score < 0 ? 'neg' : '');
    const points = s.score ? (s.score > 0 ? '+' : '') + s.score : '·';
    return `<li>
      <span class="why-score ${cls}">${points}</span>
      <span>${esc(s.label)}${s.rationale ? `<span class="why-rat">${esc(s.rationale)}</span>` : ''}</span>
    </li>`;
  }).join('');
  return `<ul class="why-list">${rows}</ul>
    <p class="muted" style="margin-top:8px">
      Total ${t.score} · thresholds decide the bucket · engine: ${esc(t.engine)}
      ${t.model ? '· model: ' + esc(t.model) : ''}
      ${t.ruleset_version ? '· ruleset v' + t.ruleset_version : ''}
    </p>`;
}

function timeline(events) {
  if (!events.length) return '<p class="muted">Nothing recorded yet.</p>';
  const items = events.map((e) => {
    const cls = isAlert(e.action) ? 'alert' : (e.is_human ? 'human' : '');
    const change = (e.from || e.to)
      ? `<div class="tl-chg">${esc(e.from ?? '—')} → <b>${esc(e.to ?? '—')}</b></div>` : '';
    return `<li class="${cls}">
      <div class="tl-when">${stamp(e.at)}</div>
      <div class="tl-what"><b>${esc(e.actor)}</b> ${esc(actionWords(e.action))}</div>
      ${change}
      ${e.note ? `<div class="tl-note">“${esc(e.note)}”</div>` : ''}
    </li>`;
  }).join('');
  return `<ul class="tl">${items}</ul>`;
}

function related(cluster) {
  if (!cluster || !cluster.members?.length) {
    return '<p class="muted">Nothing else matched this one.</p>';
  }
  const rows = cluster.members.map((m) => `
    <div class="related" data-goto="${esc(m.id)}">
      <div>${esc(m.excerpt)}</div>
      <div class="rep-meta" style="margin-top:4px">
        <span>${esc(CHANNELS[m.channel] || m.channel)}</span>
        <span>${timeAgo(m.received_at)}</span>
        <span>${esc(STATUSES[m.status] || m.status)}</span>
      </div>
    </div>`).join('');
  return `<p class="muted">Grouped by wording, location and time. Grouping is a
    hint, not a decision — open any of them to check.</p>${rows}`;
}

function forwards(list) {
  if (!list.length) return '';
  const rows = list.map((f) => `
    <div class="related">
      <div><strong>${esc(f.destination_name)}</strong>
        <span class="muted">${esc(f.target)}</span></div>
      <div class="rep-meta" style="margin-top:4px">
        <span>${stamp(f.sent_at)}</span>
        <span>by ${esc(f.sent_by)}</span>
        <span>${f.dry_run ? 'dry run — not transmitted' : (f.ok ? 'sent' : 'FAILED')}</span>
        <span>${f.acknowledged_at ? 'acknowledged' : 'no reply yet'}</span>
      </div>
      ${f.note ? `<div class="tl-note">“${esc(f.note)}”</div>` : ''}
    </div>`).join('');
  return `<div class="d-section"><h4>Forwarded to</h4>${rows}</div>`;
}

function render(d) {
  const c = d.card;
  const r = d.reporting;
  const body = $('#detailBody');

  body.innerHTML = `
    <div class="d-head">
      <span class="pri pri-${c.priority}">${esc(PRIORITIES[c.priority]?.label || c.priority)}</span>
      <span class="chip">${esc(STATUSES[c.status] || c.status)}</span>
      <span class="d-id">${esc(c.id)}</span>
    </div>

    ${banners(d)}

    <div class="d-section">
      <h4>What was reported</h4>
      ${contentBlocks(r)}
    </div>

    <div class="d-section">
      <h4>Provenance</h4>
      <dl class="d-grid">
        <dt>Channel</dt><dd>${esc(CHANNELS[c.channel] || c.channel)}</dd>
        <dt>Source</dt><dd>${esc(c.source_system || 'unknown')}${c.author ? ' · ' + esc(c.author) : ''}</dd>
        <dt>Received</dt><dd>${stamp(c.received_at)} (${timeAgo(c.received_at)})</dd>
        <dt>Location</dt><dd>${esc(c.location_text || 'not stated')}${c.has_coords ? ` · ${c.location_precise ? 'confirmed' : 'inferred'} (${esc(c.location_method)})` : ''}</dd>
        ${r.reporter?.name ? `<dt>Reporter</dt><dd>${esc(r.reporter.name)}${r.reporter.phone ? ' · ' + esc(r.reporter.phone) : ''}${r.reporter.organisation ? ' · ' + esc(r.reporter.organisation) : ''}</dd>` : ''}
        <dt>Original</dt><dd>${c.permalink
          ? `<a href="${esc(c.permalink)}" target="_blank" rel="noopener">${esc(c.permalink)}</a>`
          : '<span class="muted">no link supplied</span>'}</dd>
      </dl>
    </div>

    <div class="d-section">
      <h4>Why it is here</h4>
      ${whyList(d.triage)}
    </div>

    <div class="d-section">
      <h4>Change the priority</h4>
      <div class="actions-grid">
        ${Object.entries(PRIORITIES).map(([k, v]) => `
          <button class="btn btn-sm" data-pri="${k}" ${k === c.priority ? 'disabled' : ''}>
            ${esc(v.label)}</button>`).join('')}
      </div>
      <p class="muted" style="margin-top:6px">You will be asked why. The reason
        goes in the audit trail and into the handover briefing.</p>
    </div>

    <div class="d-section">
      <h4>Forward to</h4>
      <div class="actions-grid">
        ${destinations.filter((x) => x.enabled !== false).map((x) => `
          <button class="btn btn-sm" data-fwd="${esc(x.id)}" title="${esc(x.description || '')}">
            ${esc(x.name)}</button>`).join('')}
      </div>
    </div>

    ${forwards(d.forwards)}

    <div class="d-section">
      <h4>Working it</h4>
      <div class="actions-grid">
        <button class="btn btn-sm" data-status="in_review">Mark in review</button>
        <button class="btn btn-sm" data-status="verified">Mark verified</button>
        <button class="btn btn-sm" data-status="actioned">Mark actioned</button>
        <button class="btn btn-sm" data-status="closed">Close</button>
        <button class="btn btn-sm" data-act="assign">Assign…</button>
        <button class="btn btn-sm" data-act="note">Add a note…</button>
        <button class="btn btn-sm" data-act="retriage">Re-run triage</button>
        ${c.status === 'false_reporting'
          ? '<button class="btn btn-sm" data-act="unfalse">Reverse the false call</button>'
          : '<button class="btn btn-sm btn-warn" data-act="false">Mark false reporting…</button>'}
      </div>
    </div>

    <div class="d-section">
      <h4>Related reportings ${c.cluster_size > 1 ? `(${c.cluster_size} in this group)` : ''}</h4>
      ${related(d.cluster)}
    </div>

    <div class="d-section">
      <h4>Audit trail — everything that has happened to this reporting</h4>
      ${timeline(d.audit)}
    </div>`;

  wire(body, c);
}

// ----------------------------------------------------------------- actions

function wire(body, c) {
  body.querySelectorAll('[data-pri]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const priority = btn.dataset.pri;
      const reason = prompt(
        `Why are you setting this to "${PRIORITIES[priority].label}"?\n\n`
        + 'This is recorded against your name and appears in the handover.');
      if (reason === null) return;
      act(() => api.setPriority(c.id, priority, reason || null));
    });
  });

  body.querySelectorAll('[data-status]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const status = btn.dataset.status;
      const note = prompt(`Note for changing the status to "${STATUSES[status]}" (optional):`);
      if (note === null) return;
      act(() => api.setStatus(c.id, status, note || null));
    });
  });

  body.querySelectorAll('[data-fwd]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const dest = destinations.find((x) => x.id === btn.dataset.fwd);
      const note = prompt(
        `Forward to ${dest.name} (${dest.address || dest.url}).\n\n`
        + 'Add a note for them (optional):');
      if (note === null) return;
      act(async () => {
        const res = await api.forwardTo(c.id, dest.id, note || null);
        toast(res.forward.dry_run
          ? `Composed for ${dest.name} — dry run, nothing was transmitted. The exact payload is in the audit trail.`
          : `Sent to ${dest.name}.`, 'ok');
      });
    });
  });

  body.querySelectorAll('[data-act]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const what = btn.dataset.act;
      if (what === 'note') {
        const note = prompt('Add a note. Handover notes like "called back, no answer" are the ones that matter most.');
        if (!note) return;
        return act(() => api.addNote(c.id, note));
      }
      if (what === 'assign') {
        const who = prompt('Assign to (team or person):', c.assigned_to || '');
        if (who === null) return;
        return act(() => api.assign(c.id, who || null, null));
      }
      if (what === 'false') {
        const reason = prompt(
          'Why is this a false reporting?\n\n'
          + 'Everything already grouped with it is marked false too, and any\n'
          + 'future reporting that matches arrives flagged with your reason.');
        if (!reason) return;
        return act(async () => {
          const res = await api.markFalse(c.id, reason);
          const n = res.result.also_marked.length;
          toast(n ? `Marked false. ${n} related reporting${n > 1 ? 's' : ''} marked too.`
                  : 'Marked false.', 'ok');
        });
      }
      if (what === 'unfalse') {
        const note = prompt('Why are you reversing the false-reporting call?');
        if (note === null) return;
        return act(() => api.unmarkFalse(c.id, note || null));
      }
      if (what === 'retriage') {
        return act(() => api.retriageOne(c.id));
      }
    });
  });

  body.querySelectorAll('[data-goto]').forEach((node) => {
    node.addEventListener('click', async () => {
      const { select } = await import('./queue.js');
      select(node.dataset.goto);
    });
  });
}
