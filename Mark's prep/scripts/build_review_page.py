#!/usr/bin/env python3
"""Build a self-contained review page for the assessed reports.

One file, no network, no server - openable from a phone or a USB stick. The
assessed GeoJSON and a simplified suburb outline are inlined, so nothing can
fail to load in front of an audience.

    python3 scripts/build_review_page.py

Writes site/review.html.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSESSED = ROOT / "data" / "corpus" / "assessed.geojson"
SUBURBS = ROOT / "site" / "data" / "suburbs.geojson"
OUT = ROOT / "site" / "review.html"

# Wellington, roughly. Used to project lat/long onto the inline locator.
BBOX = (174.68, -41.37, 175.03, -41.10)


def simplify_suburbs(step: int = 6, precision: int = 3) -> list:
    """Outer rings only, thinned and rounded - context, not cartography."""
    fc = json.loads(SUBURBS.read_text())
    rings = []
    for feature in fc["features"]:
        geom = feature["geometry"]
        parts = geom["coordinates"] if geom["type"] == "Polygon" else [
            p[0] for p in geom["coordinates"]
        ]
        outer = parts[0] if geom["type"] == "Polygon" else None
        candidates = [outer] if outer else parts
        for ring in candidates:
            if not ring or len(ring) < 8:
                continue
            thinned = [
                [round(pt[0], precision), round(pt[1], precision)]
                for i, pt in enumerate(ring) if i % step == 0
            ]
            if len(thinned) >= 4:
                rings.append(thinned)
    return rings


PAGE = """<!doctype html>
<html lang="en-NZ">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Report review queue &mdash; Wellington, 20 April 2026</title>
<style>
  :root {
    color-scheme: light;
    /* Neutrals carry a slight cyan bias - the subject is instruments and water,
       and a pure grey would read as unconsidered. */
    --paper:      #f4f7f7;
    --card:       #ffffff;
    --ink:        #0e1417;
    --ink-2:      #47575c;
    --ink-3:      #7d8f94;
    --rule:       #dde5e6;
    --accent:     #0e7c86;
    /* Semantic, deliberately not the accent hue. */
    --ok:         #0f7a45;
    --watch:      #a2621b;
    --idle:       #6b7c81;
    --absent:     #6a5f86;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --paper: #0d1214; --card: #151d20; --ink: #eef4f5; --ink-2: #a9bcc1;
      --ink-3: #74868b; --rule: #253034; --accent: #3fb6bf;
      --ok: #37b06b; --watch: #d59033; --idle: #84969b; --absent: #9e90c4;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --paper: #0d1214; --card: #151d20; --ink: #eef4f5; --ink-2: #a9bcc1;
    --ink-3: #74868b; --rule: #253034; --accent: #3fb6bf;
    --ok: #37b06b; --watch: #d59033; --idle: #84969b; --absent: #9e90c4;
  }
  :root[data-theme="light"] {
    color-scheme: light;
    --paper: #f4f7f7; --card: #ffffff; --ink: #0e1417; --ink-2: #47575c;
    --ink-3: #7d8f94; --rule: #dde5e6; --accent: #0e7c86;
    --ok: #0f7a45; --watch: #a2621b; --idle: #6b7c81; --absent: #6a5f86;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--paper); color: var(--ink);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-text-size-adjust: 100%;
  }
  .wrap { max-width: 62rem; margin: 0 auto; padding: 28px 18px 64px; }
  header { display: flex; flex-direction: column; gap: 6px; margin-bottom: 26px; }
  .eyebrow {
    font-size: 11px; letter-spacing: 0.11em; text-transform: uppercase;
    color: var(--accent); font-weight: 600;
  }
  h1 { margin: 0; font-size: clamp(21px, 4.4vw, 29px); line-height: 1.16;
       letter-spacing: -0.021em; text-wrap: balance; font-weight: 640; }
  .standfirst { color: var(--ink-2); max-width: 60ch; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-variant-numeric: tabular-nums; }

  .summary { background: var(--card); border: 1px solid var(--rule);
             border-radius: 10px; padding: 16px 18px; margin-bottom: 22px; }
  .meter { display: flex; height: 9px; border-radius: 5px; overflow: hidden;
           gap: 2px; margin-bottom: 14px; }
  .meter span { display: block; }
  .legend { display: flex; flex-wrap: wrap; gap: 8px 20px; }
  .legend button {
    display: flex; align-items: baseline; gap: 8px; background: none;
    border: 0; padding: 4px 2px; cursor: pointer; color: inherit;
    font: inherit; border-bottom: 2px solid transparent;
  }
  .legend button[aria-pressed="true"] { border-bottom-color: var(--accent); }
  .legend button:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
  .legend .n { font-weight: 650; font-size: 17px; }
  .legend .lbl { color: var(--ink-2); font-size: 13px; }

  .locator { background: var(--card); border: 1px solid var(--rule);
             border-radius: 10px; padding: 10px; margin-bottom: 22px; }
  .locator svg { display: block; width: 100%; height: auto; }
  .locator figcaption { color: var(--ink-3); font-size: 12px; padding: 6px 4px 2px; }

  ul.queue { list-style: none; margin: 0; padding: 0;
             display: flex; flex-direction: column; gap: 10px; }
  li.report {
    background: var(--card); border: 1px solid var(--rule); border-radius: 10px;
    border-left: 3px solid var(--stripe, var(--idle));
    padding: 13px 15px; display: flex; flex-direction: column; gap: 7px;
  }
  .meta { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: baseline;
          font-size: 12px; color: var(--ink-3); }
  .chip {
    font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase;
    font-weight: 650; color: var(--stripe, var(--idle));
  }
  .text { font-size: 15.5px; }
  .synthetic { color: var(--ink-3); font-size: 11px; border: 1px solid var(--rule);
               border-radius: 999px; padding: 1px 7px; }
  .because {
    font-size: 12.5px; color: var(--ink-2); padding-top: 7px;
    border-top: 1px dashed var(--rule);
  }
  .caveat {
    margin-top: 30px; padding: 15px 17px; border-radius: 10px;
    border: 1px solid var(--rule); background: var(--card); color: var(--ink-2);
    font-size: 13.5px; max-width: 66ch;
  }
  .caveat strong { color: var(--ink); }
  footer { margin-top: 26px; color: var(--ink-3); font-size: 12px; }
  @media (prefers-reduced-motion: no-preference) {
    li.report { transition: opacity .12s ease; }
  }
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="eyebrow">Wellington Impact Lab &middot; Team 3 &middot; Problem 04</div>
  <h1>Which of these reports do the instruments back up?</h1>
  <p class="standfirst">
    Reports as they arrived during the flooding of 20 April 2026, each checked
    against the nearest rain gauge that was actually reporting. The evidence sits
    under every verdict, so none of them has to be taken on trust.
  </p>
</header>

<section class="summary">
  <div class="meter" id="meter"></div>
  <div class="legend" id="legend"></div>
</section>

<figure class="locator">
  <svg id="map" viewBox="0 0 700 380" role="img"
       aria-label="Wellington, with each located report plotted by verdict"></svg>
  <figcaption>Each dot is a report, placed where it was resolved to. Four reports could not be placed at all and are not shown.</figcaption>
</figure>

<ul class="queue" id="queue"></ul>

<div class="caveat">
  <strong>Corroboration is not confirmation, and &ldquo;unsupported&rdquo; is not &ldquo;false&rdquo;.</strong>
  A gauge two kilometres away misses a local downpour, and a burst main floods a
  street on a dry day. A report the gauges do not support is a reason to look at
  it sooner &mdash; not grounds to dismiss it.
</div>

<footer>
  Rainfall: Greater Wellington Regional Council (Hilltop telemetry).
  Suburb boundaries and fault jobs: Wellington City Council.
  Reports marked <span class="synthetic">synthetic</span> are generated from the
  real event for testing and are not real reports.
</footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const BBOX = __BBOX__;
const RINGS = DATA.rings;
const FEATURES = DATA.assessed.features;

const VERDICTS = {
  corroborated:   { label: "Backed by a gauge",    css: "var(--ok)" },
  unsupported:    { label: "Gauges say otherwise", css: "var(--watch)" },
  not_checked:    { label: "No gauge can judge",   css: "var(--idle)" },
  no_nearby_data: { label: "No gauge in range",    css: "var(--idle)" },
  no_location:    { label: "Couldn't be placed",   css: "var(--absent)" },
};
const ORDER = ["corroborated", "unsupported", "no_nearby_data", "not_checked", "no_location"];

let active = null;

const counts = {};
for (const f of FEATURES) {
  const v = f.properties.verdict;
  counts[v] = (counts[v] || 0) + 1;
}
const present = ORDER.filter(v => counts[v]);

const meter = document.getElementById("meter");
for (const v of present) {
  const seg = document.createElement("span");
  seg.style.background = VERDICTS[v].css;
  seg.style.flex = String(counts[v]);
  seg.title = `${VERDICTS[v].label}: ${counts[v]}`;
  meter.append(seg);
}

const legend = document.getElementById("legend");
for (const v of present) {
  const b = document.createElement("button");
  b.type = "button";
  b.setAttribute("aria-pressed", "false");
  b.innerHTML = `<span class="dot" style="background:${VERDICTS[v].css}"></span>` +
                `<span class="n">${counts[v]}</span>` +
                `<span class="lbl">${VERDICTS[v].label}</span>`;
  b.addEventListener("click", () => {
    active = active === v ? null : v;
    for (const other of legend.children) {
      other.setAttribute("aria-pressed", String(other === b && active === v));
    }
    draw();
  });
  legend.append(b);
}

const W = 700, H = 380, PAD = 10;
const [w, s, e, n] = BBOX;
const sx = x => PAD + (x - w) / (e - w) * (W - PAD * 2);
const sy = y => PAD + (n - y) / (n - s) * (H - PAD * 2);

const svg = document.getElementById("map");
const NS = "http://www.w3.org/2000/svg";
function draw() {
  svg.textContent = "";
  for (const ring of RINGS) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", "M" + ring.map(c => `${sx(c[0]).toFixed(1)},${sy(c[1]).toFixed(1)}`).join("L") + "Z");
    p.setAttribute("fill", "var(--rule)");
    p.setAttribute("fill-opacity", "0.55");
    p.setAttribute("stroke", "var(--rule)");
    svg.append(p);
  }
  for (const f of FEATURES) {
    if (!f.geometry) continue;
    const v = f.properties.verdict;
    if (active && v !== active) continue;
    const [lon, lat] = f.geometry.coordinates;
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", sx(lon).toFixed(1));
    c.setAttribute("cy", sy(lat).toFixed(1));
    c.setAttribute("r", v === "corroborated" ? 5.5 : 4.5);
    c.setAttribute("fill", VERDICTS[v].css);
    c.setAttribute("fill-opacity", "0.85");
    c.setAttribute("stroke", "var(--card)");
    c.setAttribute("stroke-width", "1.5");
    const t = document.createElementNS(NS, "title");
    t.textContent = `${f.properties.text} — ${VERDICTS[v].label}`;
    c.append(t);
    svg.append(c);
  }
  renderQueue();
}

const queue = document.getElementById("queue");
function renderQueue() {
  queue.textContent = "";
  const shown = FEATURES
    .filter(f => !active || f.properties.verdict === active)
    .sort((a, b) => ORDER.indexOf(a.properties.verdict) - ORDER.indexOf(b.properties.verdict)
                 || a.properties.received_at.localeCompare(b.properties.received_at));
  for (const f of shown) {
    const p = f.properties;
    const li = document.createElement("li");
    li.className = "report";
    li.style.setProperty("--stripe", VERDICTS[p.verdict].css);
    const when = p.received_at.replace("T", " ").slice(0, 16);
    li.innerHTML =
      `<div class="meta">
         <span class="chip">${VERDICTS[p.verdict].label}</span>
         <span class="mono">${when}</span>
         <span>via ${p.channel}</span>
         ${p.synthetic ? '<span class="synthetic">synthetic</span>' : ""}
       </div>
       <div class="text"></div>
       <div class="because mono"></div>`;
    li.querySelector(".text").textContent = p.text;
    li.querySelector(".because").textContent = p.because;
    queue.append(li);
  }
}

draw();
</script>
</body>
</html>
"""


def main() -> int:
    assessed = json.loads(ASSESSED.read_text())
    rings = simplify_suburbs()
    payload = json.dumps({"assessed": assessed, "rings": rings}, separators=(",", ":"))
    html = PAGE.replace("__DATA__", payload).replace("__BBOX__", json.dumps(list(BBOX)))
    OUT.write_text(html)
    print(f"Wrote {OUT.relative_to(ROOT)}  ({OUT.stat().st_size / 1024:.0f} KB, "
          f"{len(assessed['features'])} reports, {len(rings)} outlines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
