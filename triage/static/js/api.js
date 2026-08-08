// Thin API client plus the small amount of shared client state.
// Every mutating call carries the operator name so the server can attribute
// the audit event to a person rather than to "the UI".

import { toast } from './util.js';

const BASE = '/api/v1';

export const state = {
  operator: localStorage.getItem('eoc.operator') || 'day.controller',
  shift: null,
  selectedId: null,
  reportings: [],
  groups: [],
  // Done rows are shown by default: ticking one moves it to the bottom of the
  // queue rather than making it disappear, which is how an operator sees that
  // the tick registered and how the next shift sees what this one closed.
  filters: { q: '', priority: '', unacknowledged: false, includeDone: true },
};

export function setOperator(name) {
  state.operator = name;
  localStorage.setItem('eoc.operator', name);
}

async function request(path, { method = 'GET', body } = {}) {
  const opts = { method, headers: { 'X-Operator': state.operator } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify({ actor: state.operator, ...body });
  }
  const res = await fetch(BASE + path, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = (data && data.detail) || res.statusText || 'request failed';
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

export async function call(path, opts) {
  try {
    return await request(path, opts);
  } catch (err) {
    toast(err.message, 'err');
    throw err;
  }
}

// --- reads -----------------------------------------------------------------

export const health   = ()      => call('/health');
export const stats    = ()      => call('/stats');
export const rulesets = ()      => call('/rules');
export const llmStatus= ()      => call('/llm/status');
export const adapters = ()      => call('/adapters');
export const destinations = ()  => call('/destinations');
export const shifts   = ()      => call('/shifts');
export const getReporting = (id)=> call(`/reportings/${id}`);
export const getConfig = (name) => call(`/config/${name}`);

export function consolidated() {
  const f = state.filters;
  const p = new URLSearchParams();
  if (f.q) p.set('q', f.q);
  if (f.priority) p.set('priority', f.priority);
  if (f.unacknowledged) p.set('unacknowledged', 'true');
  if (f.includeDone) p.set('include_done', 'true');
  return call('/consolidated?' + p.toString());
}

export const setGroupPriority = (id, priority, reason) =>
  call(`/consolidated/${id}/priority`, { method: 'POST', body: { priority, reason } });
export const setGroupDone = (id, done, note) =>
  call(`/consolidated/${id}/done`, { method: 'POST', body: { done, note } });
export const acknowledgeGroup = (id) =>
  call(`/consolidated/${id}/acknowledge`, { method: 'POST', body: {} });

export const getObligations = () => call('/obligations');
export const putObligations = (text) =>
  call('/obligations', { method: 'PUT', body: { text } });
export const deleteObligations = () => call('/obligations', { method: 'DELETE' });
export const setObligationDone = (id, done, note) =>
  call(`/obligations/${id}/done`, { method: 'POST', body: { done, note } });

export async function uploadObligations(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/v1/obligations/upload', {
    method: 'POST', headers: { 'X-Operator': state.operator }, body: form,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const msg = (data && data.detail) || res.statusText;
    toast(typeof msg === 'string' ? msg : 'upload failed', 'err');
    throw new Error(msg);
  }
  return data;
}

// --- controller instructions ------------------------------------------------

export const getInstructions = () => call('/instructions');
export const putInstructions = (text) =>
  call('/instructions', { method: 'PUT', body: { text } });
export const deleteInstructions = () => call('/instructions', { method: 'DELETE' });

export async function uploadInstructions(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/v1/instructions/upload', {
    method: 'POST', headers: { 'X-Operator': state.operator }, body: form,
  });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const msg = (data && data.detail) || res.statusText;
    toast(typeof msg === 'string' ? msg : 'upload failed', 'err');
    throw new Error(msg);
  }
  return data;
}

export function listReportings() {
  const f = state.filters;
  const p = new URLSearchParams();
  if (f.q) p.set('q', f.q);
  if (f.priority) p.set('priority', f.priority);
  if (f.channel) p.set('channel', f.channel);
  if (f.unacknowledged) p.set('unacknowledged', 'true');
  p.set('hide_false', f.showFalse ? 'false' : 'true');
  return call('/reportings?' + p.toString());
}

export function geojson({ priorities, includeFalse } = {}) {
  const p = new URLSearchParams();
  if (priorities) p.set('priorities', priorities.join(','));
  if (includeFalse) p.set('include_false', 'true');
  return call('/geojson?' + p.toString());
}

export function auditFeed({ shiftId, action, humansOnly } = {}) {
  const p = new URLSearchParams({ limit: '400' });
  if (shiftId) p.set('shift_id', shiftId);
  if (action) p.set('action', action);
  if (humansOnly) p.set('humans_only', 'true');
  return call('/audit?' + p.toString());
}

// --- operator actions ------------------------------------------------------

export const acknowledge = (id)              => call(`/reportings/${id}/acknowledge`, { method: 'POST', body: {} });
export const setPriority = (id, priority, reason) => call(`/reportings/${id}/priority`, { method: 'POST', body: { priority, reason } });
export const setStatus   = (id, status, note)=> call(`/reportings/${id}/status`, { method: 'POST', body: { status, note } });
export const addNote     = (id, note)        => call(`/reportings/${id}/note`, { method: 'POST', body: { note } });
export const assign      = (id, assignee, note) => call(`/reportings/${id}/assign`, { method: 'POST', body: { assignee, note } });
export const markFalse   = (id, reason)      => call(`/reportings/${id}/false`, { method: 'POST', body: { reason, propagate: true } });
export const unmarkFalse = (id, note)        => call(`/reportings/${id}/unfalse`, { method: 'POST', body: { note } });
export const forwardTo   = (id, destination_id, note) => call(`/reportings/${id}/forward`, { method: 'POST', body: { destination_id, note } });
export const retriageOne = (id)              => call(`/reportings/${id}/retriage`, { method: 'POST', body: {} });

// --- shifts, handover, config ----------------------------------------------

export const startShift = (operator, role, note) => call('/shifts/start', { method: 'POST', body: { operator, role, note } });
export const endShift   = (id, note)             => call(`/shifts/${id}/end`, { method: 'POST', body: { note } });

const handoverQuery = (useLLM, shiftId) => {
  const p = new URLSearchParams({ use_llm: useLLM ? 'true' : 'false' });
  if (shiftId) p.set('shift_id', shiftId);
  return p.toString();
};

export const handoverPreview = (useLLM, shiftId) =>
  call(`/handover/preview?${handoverQuery(useLLM, shiftId)}`);
export const handoverGenerate = (body) =>
  call('/handover', { method: 'POST', body });
/** The PDF is a download, not JSON — the browser fetches it itself. */
export const handoverPdfUrl = (useLLM, shiftId) =>
  `${BASE}/handover/pdf?${handoverQuery(useLLM, shiftId)}`;

export const saveConfig = (name, text) => call(`/config/${name}`, { method: 'PUT', body: { text } });
export const retriageAll = () => call('/retriage', { method: 'POST', body: {} });
export const reseed = () => call('/demo/seed', { method: 'POST', body: { reset: true } });
