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
  filters: { q: '', priority: '', channel: '', unacknowledged: false, showFalse: false },
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

export const handoverPreview = (useLLM) =>
  call(`/handover/preview?use_llm=${useLLM ? 'true' : 'false'}`);
export const handoverGenerate = (body) =>
  call('/handover', { method: 'POST', body });

export const saveConfig = (name, text) => call(`/config/${name}`, { method: 'PUT', body: { text } });
export const retriageAll = () => call('/retriage', { method: 'POST', body: {} });
export const generateRules = (body) => call('/rules/generate', { method: 'POST', body });
export const reseed = () => call('/demo/seed', { method: 'POST', body: { reset: true } });
