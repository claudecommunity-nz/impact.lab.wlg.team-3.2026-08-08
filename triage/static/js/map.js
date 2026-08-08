// Map tab.
//
// By default it shows only what an operator can do something about: action
// required and verification required. Situational awareness is noise on a
// tasking map, so it is opt-in.
//
// A pin's opacity carries its confidence. A solid pin is a location somebody
// gave us; a faded one was inferred from the wording and might be a suburb
// centroid. That distinction is the difference between sending a crew to an
// address and sending them to a guess.

import * as api from './api.js';
import { CHANNELS, PRIORITIES, esc, timeAgo, $ } from './util.js';

const COLOURS = {
  action_required: '#ff5c5c',
  verification_required: '#ffb020',
  situational_awareness: '#4a9eff',
};

let map = null;
let ready = false;
let onOpen = () => {};

const STYLE = {
  version: 8,
  sources: {
    base: {
      type: 'raster',
      tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png'],
      tileSize: 256,
      attribution: '© OpenStreetMap contributors © CARTO',
    },
  },
  layers: [
    { id: 'bg', type: 'background', paint: { 'background-color': '#0a0d12' } },
    { id: 'base', type: 'raster', source: 'base', paint: { 'raster-opacity': 0.85 } },
  ],
};

export function init(handlers = {}) {
  onOpen = handlers.onOpen || onOpen;
  $('#mapShowAwareness').addEventListener('change', refresh);
  $('#mapShowFalse').addEventListener('change', refresh);
}

function priorities() {
  const list = ['action_required', 'verification_required'];
  if ($('#mapShowAwareness').checked) list.push('situational_awareness');
  return list;
}

function ensureMap() {
  if (map) return map;
  map = new maplibregl.Map({
    container: 'map',
    style: STYLE,
    center: [174.7762, -41.2865],
    zoom: 11.4,
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');

  map.on('load', () => {
    map.addSource('reportings', {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: [] },
    });

    // Halo, sized by priority — reads as urgency at a glance when zoomed out.
    map.addLayer({
      id: 'halo', type: 'circle', source: 'reportings',
      paint: {
        'circle-radius': ['match', ['get', 'priority'],
          'action_required', 20, 'verification_required', 15, 11],
        'circle-color': ['match', ['get', 'priority'],
          'action_required', COLOURS.action_required,
          'verification_required', COLOURS.verification_required,
          COLOURS.situational_awareness],
        'circle-opacity': 0.14,
      },
    });

    map.addLayer({
      id: 'pins', type: 'circle', source: 'reportings',
      paint: {
        'circle-radius': ['match', ['get', 'priority'],
          'action_required', 9, 'verification_required', 7, 5.5],
        'circle-color': ['match', ['get', 'priority'],
          'action_required', COLOURS.action_required,
          'verification_required', COLOURS.verification_required,
          COLOURS.situational_awareness],
        // Faded = we inferred the location rather than being told it.
        'circle-opacity': ['case', ['get', 'location_precise'], 0.95, 0.4],
        'circle-stroke-width': ['case', ['get', 'location_precise'], 2, 1.2],
        'circle-stroke-color': ['case', ['get', 'location_precise'],
          '#ffffff', 'rgba(255,255,255,0.45)'],
      },
    });

    map.on('click', 'pins', (e) => popup(e.features[0]));
    map.on('mouseenter', 'pins', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'pins', () => { map.getCanvas().style.cursor = ''; });

    ready = true;
    refresh();
  });
  return map;
}

function popup(feature) {
  const p = feature.properties;
  const where = p.location_precise
    ? `${p.location_text || 'confirmed location'}`
    : `${p.location_text || 'inferred'} — location inferred from the wording`;

  const html = `
    <span class="pri pri-${p.priority}">${esc(PRIORITIES[p.priority]?.short || p.priority)}</span>
    <div class="pop-t">${esc(p.summary || '')}</div>
    <div class="pop-m">
      ${esc(CHANNELS[p.channel] || p.channel)} · ${timeAgo(p.received_at)}<br>
      ${esc(where)}<br>
      ${esc(p.verification.replace(/_/g, ' '))}
      ${p.acknowledged_by ? '· opened by ' + esc(p.acknowledged_by) : '· never opened'}
    </div>
    ${p.permalink ? `<div class="pop-m" style="margin-top:5px"><a href="${esc(p.permalink)}" target="_blank" rel="noopener">original source →</a></div>` : ''}
    <button class="btn btn-sm pop-btn" data-open="${esc(p.id)}">Open in the queue</button>`;

  const node = new maplibregl.Popup({ closeButton: true, maxWidth: '320px' })
    .setLngLat(feature.geometry.coordinates)
    .setHTML(html)
    .addTo(map);

  node.getElement().querySelector('[data-open]')
    ?.addEventListener('click', () => { node.remove(); onOpen(p.id); });
}

export async function refresh() {
  ensureMap();
  if (!ready) return;
  const data = await api.geojson({
    priorities: priorities(),
    includeFalse: $('#mapShowFalse').checked,
  });
  map.getSource('reportings').setData(data);
  $('#mapEmpty').hidden = data.features.length > 0;
  $('#mapFeedLink').href = '/api/v1/geojson?priorities=' + priorities().join(',');
}

export function show() {
  ensureMap();
  // The container had no size while the panel was hidden.
  setTimeout(() => { map && map.resize(); refresh(); }, 30);
}
