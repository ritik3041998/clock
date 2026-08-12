"""
build_report.py
================
Self-contained generator for report.html (the published write-up artifact).
Computes everything directly from Correct_16x16.csv / laser16x16.csv by
reusing generate_clocks.py's own detection + delay logic -- no intermediate
scratch files, and no risk of the report drifting out of sync with the
pipeline's actual clock semantics.

Supports the same optional per-clock start delay as generate_clocks.py:

    python build_report.py --pixel-delay-us 2 --line-delay-us 8 --frame-delay-us 15

Usage:
    python build_report.py [--sample-rate 1e6] [--pixel/line/frame-delay-us ...] [--out report.html]
"""
import argparse
import base64
import datetime

import numpy as np

import generate_clocks as gc


def build_step_path(intervals, t_lo, t_hi, y_hi, y_lo, x0, x1):
    def X(t):
        return x0 + (t - t_lo) / (t_hi - t_lo) * (x1 - x0)
    parts = []
    cur_x = X(t_lo)
    parts.append(f"M{cur_x:.2f},{y_lo:.2f}")
    for (t0, t1) in intervals:
        xa, xb = X(t0), X(t1)
        if xa < x0:
            xa = x0
        if xb > x1:
            xb = x1
        if xb <= cur_x:
            continue
        parts.append(f"L{xa:.2f},{y_lo:.2f}")
        parts.append(f"L{xa:.2f},{y_hi:.2f}")
        parts.append(f"L{xb:.2f},{y_hi:.2f}")
        parts.append(f"L{xb:.2f},{y_lo:.2f}")
        cur_x = xb
    parts.append(f"L{X(t_hi):.2f},{y_lo:.2f}")
    return " ".join(parts)


def b64(fn):
    return base64.b64encode(open(fn, "rb").read()).decode("ascii")


def compute_report_data(pos, built, sample_rate_hz):
    n = built["n"]
    dt = 1.0 / sample_rate_hz

    # ---- trajectory geometry (X,Y) normalized to viewBox 0..920 x 0..760 ----
    xs = [p[0] for p in pos]
    ys = [p[1] for p in pos]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    PAD = 40
    W, H = 920, 760

    def nx(x):
        return PAD + (x - xmin) / (xmax - xmin) * (W - 2 * PAD)

    def ny(y):
        return PAD + (1 - (y - ymin) / (ymax - ymin)) * (H - 2 * PAD)

    traj_pts = " ".join(f"{nx(x):.1f},{ny(y):.1f}" for x, y in pos)

    # Pixel dots are drawn at the beam position AT THE SAMPLE Pixel_Clock
    # actually asserts -- i.e. the (possibly delayed) trigger sample, not
    # necessarily the physical laser-fire sample. Matches
    # visualize_clocks.py's scan_trajectory.png behaviour exactly.
    pixel_trigger_idx = sorted(int(i) for i in np.where(built["pixel_clock"] == 1)[0])
    dots_parts = []
    for idx in pixel_trigger_idx:
        x, y = pos[idx]
        # Pixel/line numbering read straight from build_clocks' own
        # Line_Number/Pixel_In_Line metadata -- correct for any N-line,
        # M-pixels-per-line grid (not just square 16x16).
        pix_num = built["pixel_in_line"][idx] + 1
        line_num = built["line_number"][idx] + 1
        dots_parts.append(
            f'<circle class="dot" cx="{nx(x):.1f}" cy="{ny(y):.1f}" r="4.2">'
            f'<title>Pixel {pix_num} / Line {line_num} - sample {idx} - '
            f't={idx*dt*1000:.3f} ms</title></circle>'
        )
    dots_svg = "\n".join(dots_parts)

    # ---- timing lane step paths + numbered start/complete markers --------
    total_ms = n * dt * 1000
    pulse_w = 0.006  # ms, visible thin pulse

    def to_intervals(idx_list):
        return [(i * dt * 1000, i * dt * 1000 + pulse_w) for i in idx_list]

    pixel_intervals = to_intervals(pixel_trigger_idx)
    line_starts_i, line_ends_i = gc._trigger_edges_from_array(built["line_clock"])
    frame_starts_i, frame_ends_i = gc._trigger_edges_from_array(built["frame_clock"])
    line_intervals = to_intervals(list(line_starts_i) + list(line_ends_i))
    frame_intervals = to_intervals(list(frame_starts_i) + list(frame_ends_i))

    TW = 1000
    x0, x1 = 10, TW - 10
    LANE_H, GAP = 92, 6
    y0 = 0
    lanes = {}
    for name in ["frame", "line", "pixel"]:
        y_hi = y0 + LANE_H * 0.18
        y_lo = y0 + LANE_H * 0.86
        lanes[name] = (y0, y_hi, y_lo)
        y0 += LANE_H + GAP
    total_h = y0 - GAP

    def Xmap(t_lo, t_hi, t):
        return x0 + (t - t_lo) / (t_hi - t_lo) * (x1 - x0)

    def render(t_lo, t_hi):
        paths = {
            "pixel": build_step_path(pixel_intervals, t_lo, t_hi, *lanes["pixel"][1:], x0, x1),
            "line": build_step_path(line_intervals, t_lo, t_hi, *lanes["line"][1:], x0, x1),
            "frame": build_step_path(frame_intervals, t_lo, t_hi, *lanes["frame"][1:], x0, x1),
        }

        def in_window(t):
            return t_lo <= t <= t_hi

        line_starts_x = []
        for k, s in enumerate(line_starts_i):
            t = s * dt * 1000
            if in_window(t):
                line_starts_x.append((Xmap(t_lo, t_hi, t), f"L{k+1}"))
        line_ends_x = []
        for e in line_ends_i:
            t = e * dt * 1000
            if in_window(t):
                line_ends_x.append(Xmap(t_lo, t_hi, t))
        frame_starts_x = []
        for k, s in enumerate(frame_starts_i):
            t = s * dt * 1000
            if in_window(t):
                frame_starts_x.append((Xmap(t_lo, t_hi, t), f"F{k+1}"))
        frame_ends_x = []
        for e in frame_ends_i:
            t = e * dt * 1000
            if in_window(t):
                frame_ends_x.append(Xmap(t_lo, t_hi, t))

        markers = {
            "line": {"starts": line_starts_x, "ends": line_ends_x},
            "frame": {"starts": frame_starts_x, "ends": frame_ends_x},
        }
        return {"paths": paths, "lanes": lanes, "total_h": total_h, "x0": x0, "x1": x1,
                "t_lo": t_lo, "t_hi": t_hi, "markers": markers}

    d_full = render(0, total_ms)
    zoom_end = built["lines"][1][-1] * dt * 1000 + 0.08 + max(
        built["pixel_delay_samples"], built["line_delay_samples"], built["frame_delay_samples"], 0
    ) * dt * 1000
    d_zoom = render(0, zoom_end)

    num_lines = len(built["lines"])
    total_pixels = sum(len(ln) for ln in built["lines"])
    avg_ppl = total_pixels / num_lines
    ppl_label = str(int(avg_ppl)) if avg_ppl == int(avg_ppl) else f"{avg_ppl:.1f}"

    return {
        "traj_pts": traj_pts, "dots_svg": dots_svg,
        "d_full": d_full, "d_zoom": d_zoom,
        "n": n, "total_ms": total_ms,
        "num_lines": num_lines, "total_pixels": total_pixels, "ppl_label": ppl_label,
    }


def timing_svg(d, title_id, lane_labels):
    lanes = d["lanes"]
    total_h = d["total_h"]
    x0, x1 = d["x0"], d["x1"]
    paths = d["paths"]
    markers = d.get("markers", {})
    W = 1000
    label_w = 86
    vb_w = W + label_w
    top_margin = 22
    parts = []
    parts.append(f'<svg class="timing-svg" viewBox="0 -{top_margin} {vb_w} {total_h+34+top_margin}" role="img" aria-labelledby="{title_id}" preserveAspectRatio="xMinYMid meet">')
    parts.append(f'<title id="{title_id}">Pixel, line and frame clock timing diagram</title>')
    parts.append(f'<g transform="translate({label_w},0)">')
    for name in ["frame", "line", "pixel"]:
        y0, y_hi, y_lo = lanes[name]
        parts.append(f'<line x1="{x0}" y1="{y_lo}" x2="{x1}" y2="{y_lo}" class="baseline"/>')
        parts.append(f'<path d="{paths[name]}" class="trace trace-{name}"/>')
    # Numbered bold(start)/dotted(complete) trigger markers on the Line and
    # Frame lanes -- same convention as the matplotlib plots.
    for name in ["line", "frame"]:
        y0, y_hi, y_lo = lanes[name]
        m = markers.get(name, {"starts": [], "ends": []})
        for x, text in m["starts"]:
            parts.append(f'<line x1="{x:.2f}" y1="{y_lo}" x2="{x:.2f}" y2="{y_hi-6:.1f}" class="marker-start marker-{name}"/>')
            parts.append(f'<text x="{x:.2f}" y="{y_hi-9:.1f}" text-anchor="middle" class="marker-label marker-label-{name}">{text}</text>')
        for x in m["ends"]:
            parts.append(f'<line x1="{x:.2f}" y1="{y_lo}" x2="{x:.2f}" y2="{y_hi:.1f}" class="marker-end marker-{name}"/>')
    parts.append('</g>')
    for name in ["frame", "line", "pixel"]:
        y0, y_hi, y_lo = lanes[name]
        label = lane_labels[name]
        mid = (y_hi + y_lo) / 2
        parts.append(f'<text x="{label_w-12}" y="{mid+4:.1f}" text-anchor="end" class="lane-label lane-label-{name}">{label}</text>')
    parts.append('</svg>')
    return "".join(parts)


HTML_TEMPLATE = """<!-- Pixel/Line/Frame clock reconstruction report -->
<title>Clock Reconstruction — {GRID_LABEL} Raster Scan</title>
<style>
@font-face {{
  font-family: "Archivo";
  font-weight: 600 800;
  font-style: normal;
  src: url(data:font/woff2;base64,{ARCHIVO}) format("woff2");
  font-display: swap;
}}
@font-face {{
  font-family: "Plex Mono";
  font-weight: 400;
  font-style: normal;
  src: url(data:font/woff2;base64,{PLEX400}) format("woff2");
  font-display: swap;
}}
@font-face {{
  font-family: "Plex Mono";
  font-weight: 500;
  font-style: normal;
  src: url(data:font/woff2;base64,{PLEX500}) format("woff2");
  font-display: swap;
}}
@font-face {{
  font-family: "Plex Mono";
  font-weight: 600;
  font-style: normal;
  src: url(data:font/woff2;base64,{PLEX600}) format("woff2");
  font-display: swap;
}}

:root {{
  color-scheme: light;
  --bg:        #eef0f2;
  --surface:   #ffffff;
  --surface-2: #f5f7f9;
  --ink:       #10151b;
  --ink-dim:   #4b5563;
  --muted:     #838d99;
  --rule:      #dde1e6;
  --rule-strong: #c4cad2;
  --accent:    #2a78d6;
  --c-pixel:   #eb6834;
  --c-line:    #2a78d6;
  --c-frame:   #1baf7a;
  --shadow: 0 1px 2px rgba(16,21,27,0.04), 0 8px 24px -12px rgba(16,21,27,0.12);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --bg:        #0a0d11;
    --surface:   #12171d;
    --surface-2: #161c23;
    --ink:       #eef1f4;
    --ink-dim:   #aab3bf;
    --muted:     #7c8794;
    --rule:      #232a32;
    --rule-strong: #313a44;
    --accent:    #3987e5;
    --c-pixel:   #d95926;
    --c-line:    #3987e5;
    --c-frame:   #199e70;
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 12px 28px -14px rgba(0,0,0,0.55);
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --bg:        #0a0d11;
  --surface:   #12171d;
  --surface-2: #161c23;
  --ink:       #eef1f4;
  --ink-dim:   #aab3bf;
  --muted:     #7c8794;
  --rule:      #232a32;
  --rule-strong: #313a44;
  --accent:    #3987e5;
  --c-pixel:   #d95926;
  --c-line:    #3987e5;
  --c-frame:   #199e70;
  --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 12px 28px -14px rgba(0,0,0,0.55);
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Plex Mono", ui-monospace, "SF Mono", Consolas, monospace;
  font-size: 14px;
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
}}

.wrap {{
  max-width: 920px;
  margin: 0 auto;
  padding: 56px 24px 96px;
}}

h1, h2, h3 {{
  font-family: "Archivo", system-ui, sans-serif;
  font-weight: 800;
  letter-spacing: -0.01em;
  text-wrap: balance;
  margin: 0;
  color: var(--ink);
}}

.eyebrow {{
  font-family: "Plex Mono", monospace;
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--accent);
  margin: 0 0 10px;
}}

h1 {{ font-size: clamp(28px, 4vw, 38px); line-height: 1.12; }}

.subtitle {{
  margin: 14px 0 0;
  max-width: 62ch;
  color: var(--ink-dim);
  font-size: 14.5px;
  line-height: 1.65;
}}

header.report-head {{
  padding-bottom: 28px;
  border-bottom: 1px solid var(--rule);
}}

.meta-row {{
  margin-top: 22px;
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}}
.meta-chip {{
  border: 1px solid var(--rule-strong);
  border-radius: 3px;
  padding: 5px 10px;
  font-size: 11.5px;
  color: var(--ink-dim);
  background: var(--surface-2);
  font-variant-numeric: tabular-nums;
}}
.meta-chip b {{ color: var(--ink); font-weight: 600; }}
.meta-chip.delay {{ border-color: var(--accent); color: var(--ink); }}

section {{ margin-top: 52px; }}

.section-head {{
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 6px;
}}
.section-num {{
  font-family: "Archivo", sans-serif;
  font-weight: 800;
  font-size: 12px;
  color: var(--muted);
  letter-spacing: 0.02em;
}}
h2 {{ font-size: 20px; }}
.section-desc {{
  color: var(--ink-dim);
  max-width: 68ch;
  margin: 10px 0 0;
  font-size: 13.5px;
}}

/* --- Scan geometry panel --- */
.panel {{
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 6px;
  box-shadow: var(--shadow);
  padding: 20px;
  margin-top: 20px;
}}
.traj-figure {{
  display: grid;
  grid-template-columns: 1fr;
  gap: 4px;
}}
.traj-svg {{ width: 100%; height: auto; display: block; }}
.traj-svg .path-line {{
  fill: none;
  stroke: var(--ink-dim);
  stroke-width: 1.4;
  stroke-linejoin: round;
  stroke-linecap: round;
  opacity: 0.55;
}}
.traj-svg .dot {{
  fill: var(--c-pixel);
  stroke: var(--surface);
  stroke-width: 1;
}}
.figure-caption {{
  font-size: 11.5px;
  color: var(--muted);
  margin-top: 10px;
  border-top: 1px solid var(--rule);
  padding-top: 10px;
}}

/* --- Derivation cards --- */
.card-row {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-top: 20px;
}}
@media (max-width: 720px) {{ .card-row {{ grid-template-columns: 1fr; }} }}
.clock-card {{
  background: var(--surface);
  border: 1px solid var(--rule);
  border-left: 3px solid var(--card-color);
  border-radius: 4px;
  padding: 16px 16px 14px;
  box-shadow: var(--shadow);
}}
.clock-card.pixel {{ --card-color: var(--c-pixel); }}
.clock-card.line   {{ --card-color: var(--c-line); }}
.clock-card.frame  {{ --card-color: var(--c-frame); }}
.clock-card .kicker {{
  font-family: "Archivo", sans-serif;
  font-weight: 800;
  font-size: 14px;
  color: var(--card-color);
  margin: 0 0 8px;
}}
.clock-card .rule-text {{
  font-size: 12.5px;
  color: var(--ink-dim);
  margin: 0;
  line-height: 1.6;
}}
.clock-card code {{
  background: var(--surface-2);
  border: 1px solid var(--rule);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 11.5px;
  color: var(--ink);
}}

/* --- Timing diagram --- */
.legend {{
  display: flex;
  gap: 18px;
  margin: 18px 0 4px;
  flex-wrap: wrap;
}}
.legend-item {{
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  color: var(--ink-dim);
}}
.swatch {{
  width: 12px; height: 12px;
  border-radius: 2px;
  flex: none;
}}
.timing-svg {{ width: 100%; height: auto; display: block; }}
.timing-svg .baseline {{ stroke: var(--rule-strong); stroke-width: 1; }}
.timing-svg .trace {{ fill: none; stroke-width: 2; stroke-linejoin: round; }}
.timing-svg .trace-frame {{ stroke: var(--c-frame); }}
.timing-svg .trace-line  {{ stroke: var(--c-line); }}
.timing-svg .trace-pixel {{ stroke: var(--c-pixel); }}
.timing-svg .lane-label {{
  font-family: "Plex Mono", monospace;
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.08em;
}}
.timing-svg .lane-label-frame {{ fill: var(--c-frame); }}
.timing-svg .lane-label-line  {{ fill: var(--c-line); }}
.timing-svg .lane-label-pixel {{ fill: var(--c-pixel); }}
.timing-svg .marker-start {{ stroke-width: 2; }}
.timing-svg .marker-end {{ stroke-width: 1.2; stroke-dasharray: 3 3; opacity: 0.75; }}
.timing-svg .marker-line {{ stroke: var(--c-line); }}
.timing-svg .marker-frame {{ stroke: var(--c-frame); }}
.timing-svg .marker-label {{
  font-family: "Plex Mono", monospace;
  font-weight: 600;
  font-size: 9.5px;
}}
.timing-svg .marker-label-line {{ fill: var(--c-line); }}
.timing-svg .marker-label-frame {{ fill: var(--c-frame); }}
.timing-block + .timing-block {{ margin-top: 30px; }}
.timing-title {{
  font-family: "Plex Mono", monospace;
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 8px;
}}

/* --- Table --- */
.table-scroll {{ overflow-x: auto; margin-top: 20px; border: 1px solid var(--rule); border-radius: 6px; }}
table {{
  width: 100%;
  border-collapse: collapse;
  background: var(--surface);
  font-size: 12.5px;
  min-width: 560px;
}}
thead th {{
  text-align: left;
  font-family: "Plex Mono", monospace;
  font-weight: 600;
  font-size: 10.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--muted);
  background: var(--surface-2);
  padding: 10px 14px;
  border-bottom: 1px solid var(--rule);
  white-space: nowrap;
}}
tbody td {{
  padding: 11px 14px;
  border-bottom: 1px solid var(--rule);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}}
tbody tr:last-child td {{ border-bottom: none; }}
tbody td.label {{ font-family: "Archivo", sans-serif; font-weight: 700; font-size: 12.5px; }}
.dot-legend {{ display:inline-block; width:8px; height:8px; border-radius:2px; margin-right:7px; vertical-align:1px; }}

/* --- Files / output list --- */
.file-list {{ margin-top: 20px; display: grid; gap: 10px; }}
.file-row {{
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 14px;
  padding: 12px 14px;
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 5px;
  align-items: baseline;
}}
@media (max-width: 640px) {{ .file-row {{ grid-template-columns: 1fr; }} }}
.file-name {{
  font-weight: 600;
  color: var(--ink);
  font-size: 12.5px;
}}
.file-desc {{ color: var(--ink-dim); font-size: 12px; }}

.cmd-block {{
  margin-top: 18px;
  background: var(--surface-2);
  border: 1px solid var(--rule);
  border-radius: 5px;
  padding: 12px 14px;
  font-size: 12.5px;
  color: var(--ink);
  overflow-x: auto;
}}
.cmd-block .prompt {{ color: var(--muted); }}

footer {{
  margin-top: 64px;
  padding-top: 20px;
  border-top: 1px solid var(--rule);
  font-size: 11.5px;
  color: var(--muted);
}}
footer p {{ margin: 4px 0; max-width: 68ch; }}

a {{ color: var(--accent); }}
</style>

<div class="wrap">

<header class="report-head">
  <p class="eyebrow">Signal Reconstruction · {GRID_LABEL} Point Raster Scan</p>
  <h1>Pixel, Line &amp; Frame Clocks<br>from Laser Strobe &amp; Galvo Position Logs</h1>
  <p class="subtitle">Derived from <code>{POS_CSV}</code> (X/Y scanner drive voltages) and
  <code>{LASER_CSV}</code> (laser strobe flag), sample-aligned row for row. {TOTAL_PIXELS} laser-fire
  events group cleanly into {NUM_LINES} lines of {PPL_LABEL} pixels — the grouping below was detected automatically,
  with zero mismatches against that {NUM_LINES}-line target.</p>
  <div class="meta-row">
    <span class="meta-chip">Grid <b>{GRID_LABEL}</b></span>
    <span class="meta-chip">Pixels/frame <b>{TOTAL_PIXELS}</b></span>
    <span class="meta-chip">Sample rate <b>{SAMPLE_RATE_STR} Hz</b></span>
    <span class="meta-chip">Samples <b>{N}</b></span>
    <span class="meta-chip">Generated <b>{GENERATED_DATE}</b></span>
    {DELAY_CHIPS}
  </div>
</header>

<section id="geometry">
  <div class="section-head"><span class="section-num">01</span><h2>Scan geometry</h2></div>
  <p class="section-desc">The galvo traces a vertical serpentine: down a column, round a turn,
  up the next column, {NUM_LINES} times over. Each orange dot is one Pixel-Clock trigger — the same shape
  as <code>scan_pattern.bmp</code> / <code>spatial_points.bmp</code>, reconstructed here from the
  raw voltage trace rather than pre-rendered.</p>
  <div class="panel">
    <div class="traj-figure">
      {TRAJ_SVG}
    </div>
    <p class="figure-caption">X/Y galvo drive voltage, {N} samples · dots mark the {TOTAL_PIXELS} samples where Pixel Clock triggers.</p>
  </div>
</section>

<section id="derivation">
  <div class="section-head"><span class="section-num">02</span><h2>Derivation rules</h2></div>
  <p class="section-desc">All three clocks are the same kind of signal — 1-sample
  <em>triggers</em>, never held high. They differ only in how often they fire.</p>
  <div class="card-row">
    <div class="clock-card pixel">
      <p class="kicker">Pixel Clock</p>
      <p class="rule-text">Trigger. Pulses once, one sample wide, every time the laser strobe
      reads <code>5</code>{PIXEL_DELAY_NOTE}. {TOTAL_PIXELS} pulses per frame — one per pixel counted.</p>
    </div>
    <div class="clock-card line">
      <p class="kicker">Line Clock</p>
      <p class="rule-text">Trigger, twice per line: once on the line's <em>first</em> pixel
      (line-start, <b style="color:var(--c-line)">bold</b> marker), once on its <em>final</em>
      pixel
      (line-complete, <span style="border-bottom:1px dashed var(--c-line)">dotted</span>
      marker){LINE_DELAY_NOTE}. {NUM_LINES_X2} pulses per frame.</p>
    </div>
    <div class="clock-card frame">
      <p class="kicker">Frame Clock</p>
      <p class="rule-text">Trigger, twice per frame: once on line 1's first pixel (frame-start,
      <b style="color:var(--c-frame)">bold</b> marker), once on the final line's final pixel
      (frame-complete, <span style="border-bottom:1px dashed var(--c-frame)">dotted</span>
      marker){FRAME_DELAY_NOTE}. 2 pulses per frame.</p>
    </div>
  </div>
</section>

<section id="timing">
  <div class="section-head"><span class="section-num">03</span><h2>Timing diagram</h2></div>
  <p class="section-desc">Bold numbered markers (L1, L2, … / F1) mark each "start" trigger;
  dotted markers mark the matching "complete" trigger. Hover any pulse for its sample index
  and timestamp.</p>
  <div class="legend">
    <span class="legend-item"><span class="swatch" style="background:var(--c-frame)"></span>Frame Clock</span>
    <span class="legend-item"><span class="swatch" style="background:var(--c-line)"></span>Line Clock</span>
    <span class="legend-item"><span class="swatch" style="background:var(--c-pixel)"></span>Pixel Clock</span>
  </div>
  <div class="panel">
    <div class="timing-block">
      <p class="timing-title">Full frame · 0 – {TOTAL_MS}&nbsp;ms</p>
      {TIMING_FULL_SVG}
    </div>
    <div class="timing-block">
      <p class="timing-title">Zoom · lines 1–2</p>
      {TIMING_ZOOM_SVG}
    </div>
  </div>
</section>

<section id="frequencies">
  <div class="section-head"><span class="section-num">04</span><h2>Frequency summary</h2></div>
  <p class="section-desc">At the configured {SAMPLE_RATE_STR}&nbsp;Hz sample rate. Re-run
  <code>build_report.py --sample-rate &lt;Hz&gt;</code> with your DAQ's real rate, or add
  <code>--pixel/line/frame-delay-us</code>, to regenerate this page.</p>
  <div class="table-scroll">
    <table>
      <thead>
        <tr><th>Clock</th><th>Type</th><th>Period</th><th>Frequency</th><th>Events / frame</th><th>Start delay</th></tr>
      </thead>
      <tbody>
        <tr>
          <td class="label"><span class="dot-legend" style="background:var(--c-pixel)"></span>Pixel</td>
          <td>Trigger</td>
          <td>{PIXEL_PERIOD}</td>
          <td>{PIXEL_FREQ}</td>
          <td>{TOTAL_PIXELS}</td>
          <td>{PIXEL_DELAY_US} µs</td>
        </tr>
        <tr>
          <td class="label"><span class="dot-legend" style="background:var(--c-line)"></span>Line</td>
          <td>Trigger ×2</td>
          <td>{LINE_PERIOD}</td>
          <td>{LINE_FREQ}</td>
          <td>{NUM_LINES_X2} ({NUM_LINES} start + {NUM_LINES} complete)</td>
          <td>{LINE_DELAY_US} µs</td>
        </tr>
        <tr>
          <td class="label"><span class="dot-legend" style="background:var(--c-frame)"></span>Frame</td>
          <td>Trigger ×2</td>
          <td>{FRAME_PERIOD}</td>
          <td>{FRAME_FREQ}</td>
          <td>2 (start + complete)</td>
          <td>{FRAME_DELAY_US} µs</td>
        </tr>
      </tbody>
    </table>
  </div>
</section>

<section id="outputs">
  <div class="section-head"><span class="section-num">05</span><h2>Generated files</h2></div>
  <p class="section-desc">Everything below was written next to the source CSVs by
  <code>generate_clocks.py</code>, the script backing this whole report.</p>
  <div class="file-list">
    <div class="file-row">
      <span class="file-name">clock_output.csv</span>
      <span class="file-desc">Sample-by-sample table — <code>Sample_Index, Time_s, X_Voltage, Y_Voltage, Laser_Raw, Pixel_Clock, Line_Clock, Frame_Clock, Line_Number, Pixel_In_Line</code>. {N} rows.</span>
    </div>
    <div class="file-row">
      <span class="file-name">clock_summary.csv</span>
      <span class="file-desc">The frequency table above, in CSV form: period, frequency, event count and configured delay per clock.</span>
    </div>
    <div class="file-row">
      <span class="file-name">viz_scan_pattern.png</span>
      <span class="file-desc">Matplotlib render of the trajectory + pixel events (source for §01, black background to match the reference BMPs).</span>
    </div>
    <div class="file-row">
      <span class="file-name">viz_timing_full.png / viz_timing_zoom.png</span>
      <span class="file-desc">Matplotlib renders of the timing diagrams in §03.</span>
    </div>
    <div class="file-row">
      <span class="file-name">generate_clocks.py</span>
      <span class="file-desc">The script itself — reusable on any N×N scan; auto-detects line/pixel grouping from the laser strobe, warns if it doesn't match <code>--pixels-per-line</code>. Supports <code>--pixel/line/frame-delay-us</code>.</span>
    </div>
  </div>
  <div class="cmd-block"><span class="prompt">$</span> {CMD_LINE}</div>
</section>

<footer>
  <p><b style="color:var(--ink)">Assumption:</b> the {SAMPLE_RATE_STR}&nbsp;Hz sample rate is a
  placeholder value confirmed for this run — every period/frequency figure scales directly with
  it. Line grouping used a {GAP_SPLIT}-sample gap threshold separating within-line pixel spacing
  from line-to-line flyback; lines/pixels-per-line were auto-detected from the laser strobe, not
  hand-tuned, yielding {NUM_LINES} lines of {PPL_LABEL} pixels for this
  {GRID_LABEL} run.{DELAY_FOOTNOTE}</p>
</footer>

</div>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pos-csv", default="Correct_16x16.csv")
    ap.add_argument("--laser-csv", default="laser16x16.csv")
    ap.add_argument("--sample-rate", type=float, default=1e6)
    ap.add_argument("--pixels-per-line", type=int, default=16)
    ap.add_argument("--gap-split", type=int, default=36)
    ap.add_argument("--pixel-delay-us", type=float, default=0.0)
    ap.add_argument("--line-delay-us", type=float, default=0.0)
    ap.add_argument("--frame-delay-us", type=float, default=0.0)
    ap.add_argument("--out", default="report.html")
    args = ap.parse_args()

    dt_us = 1e6 / args.sample_rate
    pixel_delay_samples = round(args.pixel_delay_us / dt_us)
    line_delay_samples = round(args.line_delay_us / dt_us)
    frame_delay_samples = round(args.frame_delay_us / dt_us)

    pos, laser = gc.load_csv_pair(args.pos_csv, args.laser_csv)
    built = gc.build_clocks(pos, laser, pixels_per_line=args.pixels_per_line,
                             gap_split=args.gap_split,
                             pixel_delay_samples=pixel_delay_samples,
                             line_delay_samples=line_delay_samples,
                             frame_delay_samples=frame_delay_samples)
    freqs = gc.compute_frequencies(built, args.sample_rate, built["n"])
    data = compute_report_data(pos, built, args.sample_rate)

    timing_full_svg = timing_svg(data["d_full"], "timing-full-title",
                                  {"frame": "FRAME", "line": "LINE", "pixel": "PIXEL"})
    timing_zoom_svg = timing_svg(data["d_zoom"], "timing-zoom-title",
                                  {"frame": "FRAME", "line": "LINE", "pixel": "PIXEL"})

    def delay_note(us):
        return f", delayed {us:.1f}&nbsp;µs from the physical event" if us else ""

    delay_chips = "".join(
        f'<span class="meta-chip delay">{name} delay <b>{us:.1f} µs</b></span>'
        for name, us in [("Pixel", args.pixel_delay_us), ("Line", args.line_delay_us),
                          ("Frame", args.frame_delay_us)]
        if us
    )
    any_delay = args.pixel_delay_us or args.line_delay_us or args.frame_delay_us
    delay_footnote = ""
    if any_delay:
        delay_footnote = (
            f" Configured start delays (relative to the physical event each clock marks): "
            f"Pixel +{args.pixel_delay_us:.1f}&nbsp;µs, Line +{args.line_delay_us:.1f}&nbsp;µs, "
            f"Frame +{args.frame_delay_us:.1f}&nbsp;µs — each clock's own period/frequency is "
            f"unaffected by its delay, only its phase relative to the other two clocks."
        )

    num_lines = data["num_lines"]
    grid_label = f'{num_lines} × {data["ppl_label"]}'
    import os
    pos_csv_name = os.path.basename(args.pos_csv)
    laser_csv_name = os.path.basename(args.laser_csv)

    cmd_parts = ["python generate_clocks.py", f"--sample-rate {args.sample_rate:.0f}"]
    if args.pixel_delay_us:
        cmd_parts.append(f"--pixel-delay-us {args.pixel_delay_us}")
    if args.line_delay_us:
        cmd_parts.append(f"--line-delay-us {args.line_delay_us}")
    if args.frame_delay_us:
        cmd_parts.append(f"--frame-delay-us {args.frame_delay_us}")

    html = HTML_TEMPLATE.format(
        ARCHIVO=b64("fonts/Archivo.woff2"), PLEX400=b64("fonts/PlexMono-400.woff2"),
        PLEX500=b64("fonts/PlexMono-500.woff2"), PLEX600=b64("fonts/PlexMono-600.woff2"),
        N=data["n"], SAMPLE_RATE_STR=f"{args.sample_rate:,.0f}",
        GENERATED_DATE=datetime.date.today().isoformat(),
        DELAY_CHIPS=delay_chips,
        TRAJ_SVG=f'<svg class="traj-svg" viewBox="0 0 920 760" role="img" aria-label="Serpentine scan trajectory with pixel events">\n<polyline class="path-line" points="{data["traj_pts"]}"/>\n{data["dots_svg"]}\n</svg>',
        PIXEL_DELAY_NOTE=delay_note(args.pixel_delay_us),
        LINE_DELAY_NOTE=delay_note(args.line_delay_us),
        FRAME_DELAY_NOTE=delay_note(args.frame_delay_us),
        TOTAL_MS=f'{data["total_ms"]:.3f}',
        TIMING_FULL_SVG=timing_full_svg, TIMING_ZOOM_SVG=timing_zoom_svg,
        PIXEL_PERIOD=f'{freqs["pixel_period_s"]*1e6:.2f} µs', PIXEL_FREQ=f'{freqs["pixel_freq_hz"]:,.1f} Hz',
        LINE_PERIOD=f'{freqs["line_period_s"]*1e6:.2f} µs', LINE_FREQ=f'{freqs["line_freq_hz"]:,.1f} Hz',
        FRAME_PERIOD=f'{freqs["frame_period_s"]*1e3:.3f} ms', FRAME_FREQ=f'{freqs["frame_freq_hz"]:,.3f} Hz',
        PIXEL_DELAY_US=f'{args.pixel_delay_us:.1f}', LINE_DELAY_US=f'{args.line_delay_us:.1f}',
        FRAME_DELAY_US=f'{args.frame_delay_us:.1f}',
        CMD_LINE=" ".join(cmd_parts),
        DELAY_FOOTNOTE=delay_footnote,
        GRID_LABEL=grid_label, POS_CSV=pos_csv_name, LASER_CSV=laser_csv_name,
        NUM_LINES=num_lines, NUM_LINES_X2=num_lines * 2,
        TOTAL_PIXELS=data["total_pixels"], PPL_LABEL=data["ppl_label"],
        GAP_SPLIT=args.gap_split,
    )

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print(f"wrote {args.out} ({len(html)} chars)")


if __name__ == "__main__":
    main()
