// Shared formatting and DOM helpers.

export const PRIORITIES = {
  action_required:       { label: 'Action required',       short: 'Action' },
  verification_required: { label: 'Verification required', short: 'Verify' },
  situational_awareness: { label: 'Situational awareness', short: 'Awareness' },
};

export const CHANNELS = {
  phone_call:     'Call centre',
  email:          'Email',
  web_form:       'Web form',
  social_media:   'Social media',
  news:           'News',
  partner_agency: 'Partner agency',
  sensor:         'Sensor',
  other:          'Other',
};

export const STATUSES = {
  new: 'New', acknowledged: 'Acknowledged', in_review: 'In review',
  verified: 'Verified', false_reporting: 'False reporting',
  forwarded: 'Forwarded', actioned: 'Actioned', closed: 'Closed',
  duplicate: 'Duplicate',
};

const ACTION_WORDS = {
  ingested: 'received', triaged: 'triaged automatically',
  retriaged: 're-triaged', viewed: 'viewed', acknowledged: 'opened',
  priority_overridden: 'changed the priority', status_changed: 'changed the status',
  marked_false: 'marked it a FALSE reporting',
  cluster_flagged_false: 'flagged the whole group as false',
  note_added: 'added a note', assigned: 'assigned it',
  forwarded: 'forwarded it', forward_failed: 'FAILED to forward it',
  linked_duplicate: 'linked it as a duplicate',
  shift_started: 'started a shift', shift_ended: 'ended the shift',
  handover_generated: 'generated a handover briefing',
  config_changed: 'edited configuration', ruleset_generated: 'generated a ruleset',
};

export const actionWords = (a) => ACTION_WORDS[a] || (a || '').replace(/_/g, ' ');

// Actions worth a red dot on the timeline.
const ALERT_ACTIONS = new Set(['marked_false', 'cluster_flagged_false',
                               'forward_failed', 'priority_overridden']);
export const isAlert = (a) => ALERT_ACTIONS.has(a);

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function timeAgo(iso) {
  if (!iso) return '';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h}h ${mins % 60}m ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function clock(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString('en-NZ',
    { hour: '2-digit', minute: '2-digit' });
}

export function stamp(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('en-NZ', { day: '2-digit', month: 'short' })
       + ' ' + d.toLocaleTimeString('en-NZ', { hour: '2-digit', minute: '2-digit' });
}

export const $  = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

let toastTimer;
export function toast(message, kind = '') {
  const node = $('#toast');
  node.textContent = message;
  node.className = 'toast ' + kind;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, kind === 'err' ? 6500 : 3800);
}
