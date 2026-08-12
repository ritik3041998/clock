"""
build_animation.py
===================
Self-contained generator for scan_animation.html — reuses generate_clocks.py's
own detection logic directly (import, not a re-implementation) for the
PHYSICAL (undelayed) scan structure, then ships that physical data to the
browser and lets the page itself compute delayed trigger positions live in
JavaScript. This means the delay inputs in the page are truly interactive —
no server round-trip, no rebuilding the HTML — and the "start at pixel #"
control can jump anywhere in the (possibly delayed) pixel sequence instantly.

Clock semantics match generate_clocks.py:
    Pixel Clock -> trigger, 1 sample wide, once per pixel counted (256/frame)
    Line Clock  -> ONE trigger per line: fires once, on line-complete (the
                   16th/last pixel) (16/frame). NOT held high, no separate
                   line-start pulse.
    Frame Clock -> two triggers per frame: frame-start (line 1's 1st pixel)
                   and frame-complete (line 16's 16th pixel) (2/frame). NOT
                   held high.

--pixel/line/frame-delay-us on the command line only set the INITIAL values
shown in the page's delay inputs on load -- the delay itself is recomputed
live in the browser whenever you edit those inputs and click Apply.

Usage:
    python build_animation.py [--sample-rate 1e6] [--pixel/line/frame-delay-us ...] [--out scan_animation.html]
"""
import argparse
import json
import base64

import generate_clocks as gc


def build_data(pos_csv, laser_csv, sample_rate_hz, pixels_per_line=None, gap_split=None):
    pos, laser = gc.load_csv_pair(pos_csv, laser_csv)
    # physical/undelayed baseline -- delay lives in JS now
    built = gc.build_clocks(pos, laser, pixels_per_line=pixels_per_line, gap_split=gap_split)
    n = built["n"]
    lines = built["lines"]
    freqs = gc.compute_frequencies(built, sample_rate_hz, n)

    # ---- canvas trajectory geometry ----
    xs = [p[0] for p in pos]
    ys = [p[1] for p in pos]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    PAD = 32
    W, H = 460, 380

    def nx(x):
        return PAD + (x - xmin) / (xmax - xmin) * (W - 2 * PAD)

    def ny(y):
        return PAD + (1 - (y - ymin) / (ymax - ymin)) * (H - 2 * PAD)

    traj_flat = []
    for x, y in pos:
        traj_flat.append(round(nx(x), 2))
        traj_flat.append(round(ny(y), 2))

    physical_pixel_idx = [int(i) for ln in lines for i in ln]        # chronological, all pixels
    # Parallel arrays: which line / which position-in-line each entry of
    # physical_pixel_idx belongs to, read straight from build_clocks' own
    # Line_Number/Pixel_In_Line metadata -- correct for any N-line,
    # M-pixels-per-line grid (not just a hardcoded 16x16 square).
    physical_pixel_line = [int(built["line_number"][i]) for i in physical_pixel_idx]
    physical_pixel_pix = [int(built["pixel_in_line"][i]) for i in physical_pixel_idx]
    physical_lines = [[int(l[0]), int(l[-1])] for l in lines]        # num_lines x [start,end]
    physical_frame = [int(built["frame_start"]), int(built["frame_end"])]
    num_lines = len(lines)
    total_pixels = len(physical_pixel_idx)
    avg_ppl = total_pixels / num_lines
    ppl_label = str(int(avg_ppl)) if avg_ppl == int(avg_ppl) else f"{avg_ppl:.1f}"

    TW = 1000
    x0t, x1t = 10, TW - 10
    LANE_H, GAP = 54, 5
    y0 = 0
    lanes = {}
    for name in ["frame", "line", "pixel"]:
        y_hi = y0 + LANE_H * 0.18
        y_lo = y0 + LANE_H * 0.86
        lanes[name] = {"yHi": round(y_hi, 1), "yLo": round(y_lo, 1)}
        y0 += LANE_H + GAP
    total_h = y0 - GAP

    return {
        "n": n,
        "canvasW": W, "canvasH": H,
        "traj": traj_flat,
        "physicalPixelIdx": physical_pixel_idx,
        "physicalPixelLine": physical_pixel_line,
        "physicalPixelPix": physical_pixel_pix,
        "physicalLines": physical_lines,
        "physicalFrame": physical_frame,
        "numLines": num_lines,
        "totalPixels": total_pixels,
        "timing": {
            "viewW": TW, "viewH": total_h,
            "x0": x0t, "x1": x1t,
            "lanes": lanes,
        },
        "sampleRateHz": sample_rate_hz,
        "freqs": {
            "pixelHz": freqs["pixel_freq_hz"], "pixelPeriodUs": freqs["pixel_period_s"] * 1e6,
            "lineHz": freqs["line_freq_hz"], "linePeriodUs": freqs["line_period_s"] * 1e6,
            "frameHz": freqs["frame_freq_hz"], "framePeriodMs": freqs["frame_period_s"] * 1e3,
        },
        "gridLabel": f"{num_lines} × {ppl_label}",
        "numLinesLabel": str(num_lines),
        "pplLabel": ppl_label,
    }


def b64(fn):
    return base64.b64encode(open(fn, "rb").read()).decode("ascii")


def timing_lanes_svg(data):
    """SVG skeleton only -- the trace paths and start/complete markers start
    empty and are filled in by JS's applyDelays() on page load (and again on
    every 'Apply' click), since the delay is a live client-side parameter now."""
    lanes = data["timing"]["lanes"]
    x0, x1, view_h = data["timing"]["x0"], data["timing"]["x1"], data["timing"]["viewH"]
    parts = []
    for name in ["frame", "line", "pixel"]:
        y_lo = lanes[name]["yLo"]
        parts.append(f'<line x1="{x0}" y1="{y_lo}" x2="{x1}" y2="{y_lo}" class="baseline"/>')
    for name in ["frame", "line", "pixel"]:
        parts.append(f'<path id="dim{name.capitalize()}" d="" class="trace-dim trace-{name}"/>')
    parts.append(f'<clipPath id="revealClip"><rect id="revealRect" x="0" y="0" width="0" height="{view_h}"/></clipPath>')
    parts.append('<g clip-path="url(#revealClip)">')
    for name in ["frame", "line", "pixel"]:
        parts.append(f'<path id="bright{name.capitalize()}" d="" class="trace-bright trace-{name}"/>')
    parts.append('</g>')
    parts.append('<g id="markersGroup"></g>')
    for name in ["frame", "line", "pixel"]:
        y_hi, y_lo = lanes[name]["yHi"], lanes[name]["yLo"]
        mid = (y_hi + y_lo) / 2
        parts.append(f'<text x="6" y="{mid-6:.1f}" class="lane-label lane-label-{name}">{name.upper()}</text>')
    return "".join(parts)


HTML_TEMPLATE = """<!-- Live scan + clock generation animation -->
<title>Live Scan — Pixel/Line/Frame Clocks</title>
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
  --trail:     #10151b;
  --warn:      #b5570f;
  --warn-bg:   #fdf0e6;
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
    --trail:     #eef1f4;
    --warn:      #e8934f;
    --warn-bg:   #2a1d10;
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
  --trail:     #eef1f4;
  --warn:      #e8934f;
  --warn-bg:   #2a1d10;
  --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 12px 28px -14px rgba(0,0,0,0.55);
}}

* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: "Plex Mono", ui-monospace, "SF Mono", Consolas, monospace;
  font-size: 14px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}}
.wrap {{ max-width: 860px; margin: 0 auto; padding: 20px 18px 24px; }}

h1 {{
  font-family: "Archivo", system-ui, sans-serif;
  font-weight: 800;
  letter-spacing: -0.01em;
  text-wrap: balance;
  margin: 0;
  font-size: clamp(18px, 2.4vw, 22px);
  line-height: 1.14;
}}
.eyebrow {{
  font-weight: 600;
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--accent);
  margin: 0 0 4px;
}}

/* ---- transport bar ---- */
.transport {{
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 8px;
  padding: 8px 12px;
  box-shadow: var(--shadow);
}}
.btn {{
  font-family: "Plex Mono", monospace;
  font-weight: 600;
  font-size: 12.5px;
  letter-spacing: 0.02em;
  border: 1px solid var(--rule-strong);
  background: var(--surface-2);
  color: var(--ink);
  border-radius: 5px;
  padding: 8px 14px;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease;
}}
.btn:hover {{ border-color: var(--accent); }}
.btn:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
.btn.primary {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
.btn.primary:hover {{ opacity: 0.92; }}
.transport .divider {{ width: 1px; align-self: stretch; background: var(--rule); }}
.speed-group {{ display: flex; align-items: center; gap: 8px; }}
.speed-group label {{ font-size: 11px; color: var(--muted); letter-spacing: 0.06em; text-transform: uppercase; }}
input[type="range"] {{
  -webkit-appearance: none;
  width: 130px;
  height: 3px;
  background: var(--rule-strong);
  border-radius: 2px;
  outline: none;
}}
input[type="range"]::-webkit-slider-thumb {{
  -webkit-appearance: none;
  width: 13px; height: 13px;
  border-radius: 50%;
  background: var(--accent);
  cursor: pointer;
  border: 2px solid var(--surface);
  box-shadow: 0 0 0 1px var(--accent);
}}
input[type="range"]::-moz-range-thumb {{
  width: 13px; height: 13px;
  border-radius: 50%;
  background: var(--accent);
  cursor: pointer;
  border: 2px solid var(--surface);
}}
#speedLabel {{ font-size: 12px; color: var(--ink-dim); min-width: 34px; font-variant-numeric: tabular-nums; }}
.check-group {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--ink-dim); }}
.check-group input {{ accent-color: var(--accent); width: 14px; height: 14px; }}

/* ---- seek bar ---- */
.seek-row {{ margin-top: 8px; display: flex; align-items: center; gap: 12px; }}
#seek {{ flex: 1; width: 100%; height: 3px; }}
.seek-time {{ font-size: 11px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }}

/* ---- controls panel (start pixel + delay) ---- */
.controls-panel {{ margin-top: 10px; }}
.control-row {{
  display: flex;
  align-items: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}}
.control-field {{
  display: flex;
  flex-direction: column;
  gap: 5px;
  font-size: 11px;
  color: var(--muted);
  letter-spacing: 0.04em;
}}
input[type="number"] {{
  font-family: "Plex Mono", monospace;
  font-size: 13px;
  color: var(--ink);
  background: var(--surface-2);
  border: 1px solid var(--rule-strong);
  border-radius: 5px;
  padding: 7px 9px;
  width: 84px;
  font-variant-numeric: tabular-nums;
}}
input[type="number"]:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
.controls-panel .divider {{ width: 1px; align-self: stretch; background: var(--rule); }}
.warn-text {{
  margin: 12px 0 0;
  padding: 8px 12px;
  border-radius: 5px;
  background: var(--warn-bg);
  color: var(--warn);
  font-size: 11.5px;
  border: 1px solid var(--warn);
}}

/* ---- main grid ---- */
.stage {{
  margin-top: 10px;
  display: grid;
  grid-template-columns: 1.2fr 1fr;
  gap: 10px;
}}
@media (max-width: 640px) {{ .stage {{ grid-template-columns: 1fr; }} }}

.panel {{
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 8px;
  box-shadow: var(--shadow);
  padding: 10px;
}}
.panel-title {{
  font-weight: 600;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 6px;
}}
#scanCanvas {{ width: 100%; height: auto; display: block; border-radius: 4px; }}

/* ---- status column ---- */
.status-col {{ display: flex; flex-direction: column; gap: 8px; }}
.led-row {{ display: flex; flex-direction: column; gap: 6px; }}
.led-card {{
  display: grid;
  grid-template-columns: 18px 1fr auto;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--rule);
  border-left: 3px solid var(--led-color);
  border-radius: 5px;
  padding: 6px 9px;
  background: var(--surface-2);
}}
.led-card.pixel {{ --led-color: var(--c-pixel); }}
.led-card.line  {{ --led-color: var(--c-line); }}
.led-card.frame {{ --led-color: var(--c-frame); }}
.led-dot {{
  width: 11px; height: 11px;
  border-radius: 50%;
  background: var(--led-color);
  opacity: 0.18;
  transition: opacity 0.05s linear, box-shadow 0.05s linear;
}}
.led-dot.on {{ opacity: 1; box-shadow: 0 0 10px 1px var(--led-color); }}
.led-text {{ display: flex; flex-direction: column; gap: 1px; }}
.led-name {{ font-family: "Archivo", sans-serif; font-weight: 700; font-size: 11.5px; color: var(--ink); }}
.led-hz {{ font-size: 9.5px; color: var(--muted); font-variant-numeric: tabular-nums; }}
.led-kind {{ font-size: 8.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}
.led-state {{
  font-size: 9px; font-weight: 600; letter-spacing: 0.06em;
  color: var(--muted); text-transform: uppercase;
  font-variant-numeric: tabular-nums;
}}

.readout-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px;
}}
.readout {{
  border: 1px solid var(--rule);
  border-radius: 5px;
  padding: 7px 9px;
  background: var(--surface-2);
}}
.readout .k {{ font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }}
.readout .v {{
  font-family: "Archivo", sans-serif;
  font-weight: 800;
  font-size: 14px;
  color: var(--ink);
  margin-top: 2px;
  font-variant-numeric: tabular-nums;
}}
.readout .v small {{ font-family: "Plex Mono", monospace; font-weight: 500; font-size: 10px; color: var(--ink-dim); }}

/* ---- timing scope ---- */
.scope-wrap {{ margin-top: 10px; }}
.legend {{ display: flex; gap: 12px; margin: 0 0 6px; flex-wrap: wrap; }}
.legend-item {{ display: flex; align-items: center; gap: 5px; font-size: 10.5px; color: var(--ink-dim); }}
.swatch {{ width: 10px; height: 10px; border-radius: 2px; flex: none; }}
#timingSvg {{ width: 100%; height: auto; display: block; }}
.timing-svg .baseline {{ stroke: var(--rule-strong); stroke-width: 1; }}
.timing-svg .trace-dim {{ fill: none; stroke-width: 1.6; opacity: 0.28; }}
.timing-svg .trace-bright {{ fill: none; stroke-width: 2.2; }}
.timing-svg .trace-frame {{ stroke: var(--c-frame); }}
.timing-svg .trace-line  {{ stroke: var(--c-line); }}
.timing-svg .trace-pixel {{ stroke: var(--c-pixel); }}
.timing-svg .lane-label {{ font-family: "Plex Mono", monospace; font-weight: 600; font-size: 10.5px; letter-spacing: 0.08em; }}
.timing-svg .lane-label-frame {{ fill: var(--c-frame); }}
.timing-svg .lane-label-line  {{ fill: var(--c-line); }}
.timing-svg .lane-label-pixel {{ fill: var(--c-pixel); }}
.timing-svg .marker-start {{ stroke-width: 2; }}
.timing-svg .marker-end {{ stroke-width: 1.2; stroke-dasharray: 3 3; opacity: 0.75; }}
.timing-svg .marker-line {{ stroke: var(--c-line); }}
.timing-svg .marker-frame {{ stroke: var(--c-frame); }}
.timing-svg .marker-label {{ font-family: "Plex Mono", monospace; font-weight: 600; font-size: 9.5px; }}
.timing-svg .marker-label-line {{ fill: var(--c-line); }}
.timing-svg .marker-label-frame {{ fill: var(--c-frame); }}
#playhead {{ stroke: var(--ink); stroke-width: 1.2; opacity: 0.8; }}

.sr-only {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }}

@media (prefers-reduced-motion: reduce) {{
  .led-dot {{ transition: none; }}
}}
</style>

<div class="wrap">
  <header>
    <p class="eyebrow">Live Simulation · {GRID_LABEL} Raster Scan</p>
    <h1>Watch the Laser Scan, Watch the Clocks Fire</h1>
  </header>

  <div class="transport">
    <button class="btn primary" id="playBtn">Pause</button>
    <button class="btn" id="resetBtn">Reset</button>
    <button class="btn" id="stepBtn">Step ▸ next pixel</button>
    <div class="divider"></div>
    <div class="speed-group">
      <label for="speed">Speed</label>
      <input type="range" id="speed" min="0" max="100" value="45" />
      <span id="speedLabel">1.0×</span>
    </div>
    <div class="divider"></div>
    <label class="check-group"><input type="checkbox" id="loopChk" checked/> Loop</label>
  </div>
  <div class="seek-row">
    <input type="range" id="seek" min="0" max="{N_MINUS_1}" value="0" />
    <span class="seek-time" id="seekTime">t = 0.000 ms / {TOTAL_MS} ms</span>
  </div>

  <div class="panel controls-panel">
    <p class="panel-title">Scan Origin &amp; Clock Delay</p>
    <div class="control-row">
      <label class="control-field">Start at pixel #
        <input type="number" id="startPixel" min="1" max="{TOTAL_PIXELS}" value="1" />
      </label>
      <button class="btn" id="goStartBtn">Go</button>
      <div class="divider"></div>
      <label class="control-field">Pixel delay (µs)
        <input type="number" id="pixelDelayUs" step="0.5" value="{INIT_PIXEL_DELAY}" />
      </label>
      <label class="control-field">Line delay (µs)
        <input type="number" id="lineDelayUs" step="0.5" value="{INIT_LINE_DELAY}" />
      </label>
      <label class="control-field">Frame delay (µs)
        <input type="number" id="frameDelayUs" step="0.5" value="{INIT_FRAME_DELAY}" />
      </label>
      <button class="btn primary" id="applyDelayBtn">Apply</button>
    </div>
    <p id="delayWarn" class="warn-text" style="display:none;"></p>
  </div>

  <div class="stage">
    <div class="panel">
      <p class="panel-title">Scan Trajectory — live beam position</p>
      <canvas id="scanCanvas" width="{CANVAS_W}" height="{CANVAS_H}"></canvas>
    </div>

    <div class="status-col">
      <div class="panel">
        <p class="panel-title">Clock State</p>
        <div class="led-row">
          <div class="led-card pixel">
            <span class="led-dot" id="ledPixel"></span>
            <span class="led-text"><span class="led-name">Pixel Clock</span><span class="led-hz">{PIXEL_HZ_LABEL}</span><span class="led-kind">Trigger — 1 per pixel</span></span>
            <span class="led-state" id="statePixel">LOW</span>
          </div>
          <div class="led-card line">
            <span class="led-dot" id="ledLine"></span>
            <span class="led-text"><span class="led-name">Line Clock</span><span class="led-hz">{LINE_HZ_LABEL}</span><span class="led-kind">Trigger — once per line, on completion</span></span>
            <span class="led-state" id="stateLine">LOW</span>
          </div>
          <div class="led-card frame">
            <span class="led-dot" id="ledFrame"></span>
            <span class="led-text"><span class="led-name">Frame Clock</span><span class="led-hz">{FRAME_HZ_LABEL}</span><span class="led-kind">Trigger ×2 — frame start + complete</span></span>
            <span class="led-state" id="stateFrame">LOW</span>
          </div>
        </div>
      </div>

      <div class="panel">
        <p class="panel-title">Position</p>
        <div class="readout-grid">
          <div class="readout"><div class="k">Sample</div><div class="v" id="roSample">0 <small>/ {N_MINUS_1}</small></div></div>
          <div class="readout"><div class="k">Sim. time</div><div class="v" id="roTime">0.000 <small>ms</small></div></div>
          <div class="readout"><div class="k">Line</div><div class="v" id="roLine">— <small>/ {NUM_LINES_LABEL}</small></div></div>
          <div class="readout"><div class="k">Pixel in line</div><div class="v" id="roPixel">— <small>/ {PPL_LABEL}</small></div></div>
        </div>
      </div>
    </div>
  </div>

  <div class="panel scope-wrap">
    <p class="panel-title">Timing Scope — pixel ×1/px, line ×1/line (on completion), frame ×2 (start + complete)</p>
    <div class="legend">
      <span class="legend-item"><span class="swatch" style="background:var(--c-frame)"></span>Frame Clock (trigger ×2)</span>
      <span class="legend-item"><span class="swatch" style="background:var(--c-line)"></span>Line Clock (trigger, ×1/line)</span>
      <span class="legend-item"><span class="swatch" style="background:var(--c-pixel)"></span>Pixel Clock (trigger)</span>
    </div>
    <svg id="timingSvg" class="timing-svg" viewBox="0 -22 {TIMING_VB_W} {TIMING_VB_H_MARGIN}" role="img" aria-label="Live timing diagram of pixel, line and frame clocks">
      <title>Live timing diagram</title>
      {TIMING_LANES_SVG}
      <line id="playhead" x1="0" y1="-22" x2="0" y2="{TIMING_VIEW_H}"/>
    </svg>
  </div>

</div>

<script>
const DATA = {DATA_JSON};
</script>
<script>
(function() {{
  "use strict";
  const N = DATA.n;
  const traj = DATA.traj; // flat [x0,y0,x1,y1,...]
  const physicalPixelIdx = DATA.physicalPixelIdx; // physical sample indices, chronological
  const physicalPixelLine = DATA.physicalPixelLine; // parallel: which line each physicalPixelIdx entry belongs to
  const physicalPixelPix = DATA.physicalPixelPix;   // parallel: position-in-line for each physicalPixelIdx entry
  const physicalLines = DATA.physicalLines;        // [[s,e],...] x numLines, physical -- structural "which line" + delay base
  const physicalFrame = DATA.physicalFrame;        // [s,e], physical
  const lineSpans = physicalLines;                 // structural "current line" readout never shifts with delay
  const timing = DATA.timing;
  const SR = DATA.sampleRateHz;
  const dtMs = 1000 / SR;
  const dtUs = dtMs * 1000;
  const totalMs = N * dtMs;
  const PULSE_W = 0.006; // ms, visible thin pulse width in the timing scope

  // ---- DOM ----
  const canvas = document.getElementById("scanCanvas");
  const ctx = canvas.getContext("2d");
  const playBtn = document.getElementById("playBtn");
  const resetBtn = document.getElementById("resetBtn");
  const stepBtn = document.getElementById("stepBtn");
  const speedEl = document.getElementById("speed");
  const speedLabel = document.getElementById("speedLabel");
  const loopChk = document.getElementById("loopChk");
  const seekEl = document.getElementById("seek");
  const seekTime = document.getElementById("seekTime");
  const startPixelEl = document.getElementById("startPixel");
  const goStartBtn = document.getElementById("goStartBtn");
  const pixelDelayEl = document.getElementById("pixelDelayUs");
  const lineDelayEl = document.getElementById("lineDelayUs");
  const frameDelayEl = document.getElementById("frameDelayUs");
  const applyDelayBtn = document.getElementById("applyDelayBtn");
  const delayWarn = document.getElementById("delayWarn");
  const ledPixel = document.getElementById("ledPixel");
  const ledLine = document.getElementById("ledLine");
  const ledFrame = document.getElementById("ledFrame");
  const statePixel = document.getElementById("statePixel");
  const stateLine = document.getElementById("stateLine");
  const stateFrame = document.getElementById("stateFrame");
  const roSample = document.getElementById("roSample");
  const roTime = document.getElementById("roTime");
  const roLine = document.getElementById("roLine");
  const roPixel = document.getElementById("roPixel");
  const playhead = document.getElementById("playhead");

  const cssColor = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // ---- state ----
  let currentIndex = 0;
  let playing = true;
  let loop = true;
  let pixelFlashUntil = 0;
  let lastFlashedPixel = -1;
  let lineFlashUntil = 0;
  let lastFlashedLine = -1;
  let frameFlashUntil = 0;
  let lastFlashedFrame = -1;
  let lastPixInLine = -1;
  let lastLine = -1;

  // ---- live-delay-derived state (rebuilt by applyDelays()) ----
  let pixels = [];              // [{{i,x,y,line,pix}}], delayed
  let pixelByIndex = new Map();
  let lineTriggerSet = new Set();
  let frameTriggerSet = new Set();

  // baseline: 30-sample pixel period -> ~150ms real, scaled by speed slider
  const BASE_SAMPLES_PER_SEC = 200;
  function speedFromSlider(v) {{
    const t = v / 100;
    return Math.pow(10, (t * 2) - 1); // 0 -> 0.1x, 0.5 -> 1x, 1 -> 10x
  }}
  let speedMult = speedFromSlider(parseFloat(speedEl.value));
  speedLabel.textContent = speedMult.toFixed(1) + "×";

  function findLine(idx) {{
    for (let k = 0; k < lineSpans.length; k++) {{
      if (idx >= lineSpans[k][0] && idx <= lineSpans[k][1]) return k;
    }}
    return -1;
  }}

  // ---- live delay engine ----
  function buildStepPath(intervals, yHi, yLo, x0, x1) {{
    const X = (t) => x0 + (t / totalMs) * (x1 - x0);
    let curX = X(0);
    let d = "M" + curX.toFixed(2) + "," + yLo.toFixed(2);
    for (const iv of intervals) {{
      let xa = X(iv[0]), xb = X(iv[1]);
      if (xa < x0) xa = x0;
      if (xb > x1) xb = x1;
      if (xb <= curX) continue;
      d += " L" + xa.toFixed(2) + "," + yLo.toFixed(2);
      d += " L" + xa.toFixed(2) + "," + yHi.toFixed(2);
      d += " L" + xb.toFixed(2) + "," + yHi.toFixed(2);
      d += " L" + xb.toFixed(2) + "," + yLo.toFixed(2);
      curX = xb;
    }}
    d += " L" + X(totalMs).toFixed(2) + "," + yLo.toFixed(2);
    return d;
  }}

  function toSamples(us) {{ return Math.round(us / dtUs); }}

  function applyDelays(pixelUs, lineUs, frameUs) {{
    const pxD = toSamples(pixelUs), lnD = toSamples(lineUs), frD = toSamples(frameUs);
    let dropped = 0;

    const pxIdxAll = physicalPixelIdx.map((i) => i + pxD);
    const pxPairs = pxIdxAll.map((t, k) => ({{ t, k }})).filter((p) => p.t >= 0 && p.t < N);
    const pxIdx = pxPairs.map((p) => p.t);
    dropped += pxIdxAll.length - pxIdx.length;

    // Line Clock is a single discrete pulse per line -- fired once, on line
    // completion (the line's last pixel). No separate line-start pulse.
    const lineHits = [];
    for (const span of physicalLines) {{
      const de = span[1] + lnD;
      if (de >= 0 && de < N) lineHits.push(de); else dropped++;
    }}
    const frameStarts = [], frameEnds = [];
    {{
      const ds = physicalFrame[0] + frD, de = physicalFrame[1] + frD;
      if (ds >= 0 && ds < N) frameStarts.push(ds); else dropped++;
      if (de >= 0 && de < N) frameEnds.push(de); else dropped++;
    }}

    pixels = pxPairs.map((p) => ({{
      i: p.t, x: traj[p.t * 2], y: traj[p.t * 2 + 1],
      line: physicalPixelLine[p.k], pix: physicalPixelPix[p.k],
    }}));
    pixelByIndex = new Map();
    pixels.forEach((p, k) => pixelByIndex.set(p.i, k));
    lineTriggerSet = new Set(lineHits);
    frameTriggerSet = new Set(frameStarts.concat(frameEnds));

    const lanes = timing.lanes;
    const pxIntervals = pxIdx.map((i) => [i * dtMs, i * dtMs + PULSE_W]);
    const lnIntervals = lineHits.slice().sort((a, b) => a - b).map((i) => [i * dtMs, i * dtMs + PULSE_W]);
    const frIntervals = frameStarts.concat(frameEnds).sort((a, b) => a - b).map((i) => [i * dtMs, i * dtMs + PULSE_W]);

    const pathPixel = buildStepPath(pxIntervals, lanes.pixel.yHi, lanes.pixel.yLo, timing.x0, timing.x1);
    const pathLine = buildStepPath(lnIntervals, lanes.line.yHi, lanes.line.yLo, timing.x0, timing.x1);
    const pathFrame = buildStepPath(frIntervals, lanes.frame.yHi, lanes.frame.yLo, timing.x0, timing.x1);
    document.getElementById("dimPixel").setAttribute("d", pathPixel);
    document.getElementById("dimLine").setAttribute("d", pathLine);
    document.getElementById("dimFrame").setAttribute("d", pathFrame);
    document.getElementById("brightPixel").setAttribute("d", pathPixel);
    document.getElementById("brightLine").setAttribute("d", pathLine);
    document.getElementById("brightFrame").setAttribute("d", pathFrame);

    function Xmap(t) {{ return timing.x0 + (t / totalMs) * (timing.x1 - timing.x0); }}
    let markerSvg = "";
    // Line Clock: one bold, numbered marker per line (no dotted "complete"
    // counterpart anymore -- the single pulse itself IS the completion).
    lineHits.slice().sort((a, b) => a - b).forEach((s, k) => {{
      const x = Xmap(s * dtMs);
      markerSvg += '<line x1="' + x.toFixed(2) + '" y1="' + lanes.line.yLo + '" x2="' + x.toFixed(2) + '" y2="' + (lanes.line.yHi - 6).toFixed(1) + '" class="marker-start marker-line"/>';
      markerSvg += '<text x="' + x.toFixed(2) + '" y="' + (lanes.line.yHi - 9).toFixed(1) + '" text-anchor="middle" class="marker-label marker-label-line">L' + (k + 1) + '</text>';
    }});
    frameStarts.forEach((s, k) => {{
      const x = Xmap(s * dtMs);
      markerSvg += '<line x1="' + x.toFixed(2) + '" y1="' + lanes.frame.yLo + '" x2="' + x.toFixed(2) + '" y2="' + (lanes.frame.yHi - 6).toFixed(1) + '" class="marker-start marker-frame"/>';
      markerSvg += '<text x="' + x.toFixed(2) + '" y="' + (lanes.frame.yHi - 9).toFixed(1) + '" text-anchor="middle" class="marker-label marker-label-frame">F' + (k + 1) + '</text>';
    }});
    frameEnds.forEach((e) => {{
      const x = Xmap(e * dtMs);
      markerSvg += '<line x1="' + x.toFixed(2) + '" y1="' + lanes.frame.yLo + '" x2="' + x.toFixed(2) + '" y2="' + lanes.frame.yHi + '" class="marker-end marker-frame"/>';
    }});
    document.getElementById("markersGroup").innerHTML = markerSvg;

    if (dropped > 0) {{
      delayWarn.textContent = "⚠ " + dropped + " trigger pulse(s) fell outside the recorded window (0.." + (N - 1) + " samples) and were dropped -- reduce the delay to recover them.";
      delayWarn.style.display = "block";
    }} else {{
      delayWarn.style.display = "none";
    }}

    startPixelEl.max = String(Math.max(1, pixels.length));
    if (parseInt(startPixelEl.value, 10) > pixels.length) startPixelEl.value = String(Math.max(1, pixels.length));
  }}

  // ---- canvas setup ----
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  function fitCanvas() {{
    canvas.width = Math.round(DATA.canvasW * dpr);
    canvas.height = Math.round(DATA.canvasH * dpr);
    canvas.style.width = "100%";
    canvas.style.height = "auto";
  }}
  fitCanvas();

  function drawScan() {{
    const W = DATA.canvasW, H = DATA.canvasH;
    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    const inkDim = cssColor("--ink-dim");
    const trailColor = cssColor("--trail");
    const pixelColor = cssColor("--c-pixel");
    const lineColor = cssColor("--c-line");
    const surface = cssColor("--surface");

    ctx.beginPath();
    ctx.moveTo(traj[0], traj[1]);
    for (let i = 2; i < traj.length; i += 2) ctx.lineTo(traj[i], traj[i+1]);
    ctx.strokeStyle = inkDim;
    ctx.globalAlpha = 0.22;
    ctx.lineWidth = 0.9;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();
    ctx.globalAlpha = 1;

    const upTo = Math.max(1, Math.floor(currentIndex));
    ctx.beginPath();
    ctx.moveTo(traj[0], traj[1]);
    for (let i = 1; i <= upTo; i++) ctx.lineTo(traj[i*2], traj[i*2+1]);
    ctx.strokeStyle = trailColor;
    ctx.globalAlpha = 0.85;
    ctx.lineWidth = 1.1;
    ctx.stroke();
    ctx.globalAlpha = 1;

    for (const p of pixels) {{
      const isLit = p.i <= currentIndex;
      const isLineTrigger = lineTriggerSet.has(p.i);
      const isFlashing = p.i === lastFlashedPixel && performance.now() < pixelFlashUntil;
      const isLineFlashing = isLineTrigger && p.i === lastFlashedLine && performance.now() < lineFlashUntil;
      const glowColor = isLineFlashing ? lineColor : pixelColor;
      ctx.beginPath();
      ctx.arc(p.x, p.y, (isFlashing || isLineFlashing) ? 3.6 : (isLit ? (isLineTrigger ? 2.8 : 2.4) : 1.8), 0, Math.PI * 2);
      if (isFlashing || isLineFlashing) {{
        ctx.fillStyle = glowColor;
        ctx.shadowColor = glowColor;
        ctx.shadowBlur = 9;
      }} else if (isLit) {{
        ctx.fillStyle = isLineTrigger ? lineColor : pixelColor;
        ctx.shadowBlur = 0;
      }} else {{
        ctx.fillStyle = "transparent";
        ctx.strokeStyle = inkDim;
        ctx.globalAlpha = 0.45;
        ctx.lineWidth = 0.8;
        ctx.shadowBlur = 0;
      }}
      ctx.fill();
      if (!isLit) ctx.stroke();
      ctx.globalAlpha = 1;
      ctx.shadowBlur = 0;
    }}

    const i0 = Math.min(N - 1, Math.floor(currentIndex));
    const i1 = Math.min(N - 1, i0 + 1);
    const frac = currentIndex - i0;
    const bx = traj[i0*2] + (traj[i1*2] - traj[i0*2]) * frac;
    const by = traj[i0*2+1] + (traj[i1*2+1] - traj[i0*2+1]) * frac;
    ctx.beginPath();
    ctx.arc(bx, by, 4, 0, Math.PI * 2);
    ctx.fillStyle = cssColor("--accent");
    ctx.shadowColor = cssColor("--accent");
    ctx.shadowBlur = 10;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.beginPath();
    ctx.arc(bx, by, 4, 0, Math.PI * 2);
    ctx.lineWidth = 1.3;
    ctx.strokeStyle = surface;
    ctx.stroke();

    ctx.restore();
  }}

  function playheadX(idx) {{
    return timing.x0 + (idx / (N - 1)) * (timing.x1 - timing.x0);
  }}

  function updateTiming() {{
    const px = playheadX(currentIndex);
    playhead.setAttribute("x1", px.toFixed(2));
    playhead.setAttribute("x2", px.toFixed(2));
    document.getElementById("revealRect").setAttribute("width", Math.max(0, px - timing.x0).toFixed(2));
  }}

  function updateReadouts(curLine, curPixInLine, pixelOn, lineOn, frameOn) {{
    roSample.innerHTML = Math.floor(currentIndex) + " <small>/ " + (N - 1) + "</small>";
    roTime.innerHTML = (currentIndex * dtMs).toFixed(3) + " <small>ms</small>";
    roLine.innerHTML = (curLine >= 0 ? (curLine + 1) : "—") + " <small>/ " + DATA.numLinesLabel + "</small>";
    roPixel.innerHTML = (curPixInLine >= 0 ? (curPixInLine + 1) : "—") + " <small>/ " + DATA.pplLabel + "</small>";

    ledPixel.classList.toggle("on", pixelOn);
    ledLine.classList.toggle("on", lineOn);
    ledFrame.classList.toggle("on", frameOn);
    statePixel.textContent = pixelOn ? "HIGH" : "LOW";
    stateLine.textContent = lineOn ? "HIGH" : "LOW";
    stateFrame.textContent = frameOn ? "HIGH" : "LOW";

    seekEl.value = Math.floor(currentIndex);
    seekTime.textContent = "t = " + (currentIndex * dtMs).toFixed(3) + " ms / {TOTAL_MS} ms";
  }}

  let lastTs = null;
  function tick(ts) {{
    if (lastTs === null) lastTs = ts;
    const dt = Math.min(0.1, (ts - lastTs) / 1000);
    lastTs = ts;

    if (playing) {{
      const prevIndex = currentIndex;
      currentIndex += BASE_SAMPLES_PER_SEC * speedMult * dt;

      const from = Math.floor(prevIndex), to = Math.floor(currentIndex);
      for (let i = from; i <= to; i++) {{
        if (pixelByIndex.has(i)) {{
          lastFlashedPixel = i;
          pixelFlashUntil = performance.now() + 140;
          lastPixInLine = pixels[pixelByIndex.get(i)].pix;
        }}
        if (lineTriggerSet.has(i)) {{
          lastFlashedLine = i;
          lineFlashUntil = performance.now() + 220; // slightly longer: line trigger is the rarer event
        }}
        if (frameTriggerSet.has(i)) {{
          lastFlashedFrame = i;
          frameFlashUntil = performance.now() + 320; // longest flash: rarest event of the three
        }}
      }}

      if (currentIndex >= N - 1) {{
        if (loop) {{
          currentIndex = 0;
        }} else {{
          currentIndex = N - 1;
          playing = false;
          playBtn.textContent = "Play";
        }}
      }}
    }}

    const idx = currentIndex;
    const curLine = findLine(idx);
    if (curLine !== lastLine) {{ lastPixInLine = -1; lastLine = curLine; }}
    const curPixInLine = curLine >= 0 ? lastPixInLine : -1;
    const pixelOn = performance.now() < pixelFlashUntil;
    const lineOn = performance.now() < lineFlashUntil;
    const frameOn = performance.now() < frameFlashUntil;

    drawScan();
    updateTiming();
    updateReadouts(curLine, curPixInLine, pixelOn, lineOn, frameOn);

    requestAnimationFrame(tick);
  }}

  function resetPlaybackState() {{
    lastFlashedPixel = -1;
    lastFlashedLine = -1;
    lastFlashedFrame = -1;
    lastPixInLine = -1;
    lastLine = -1;
    pixelFlashUntil = 0;
    lineFlashUntil = 0;
    frameFlashUntil = 0;
  }}

  playBtn.addEventListener("click", () => {{
    playing = !playing;
    playBtn.textContent = playing ? "Pause" : "Play";
    lastTs = null;
  }});
  resetBtn.addEventListener("click", () => {{
    currentIndex = 0;
    resetPlaybackState();
    playing = true;
    playBtn.textContent = "Pause";
  }});
  stepBtn.addEventListener("click", () => {{
    playing = false;
    playBtn.textContent = "Play";
    const cur = Math.floor(currentIndex);
    let next = null;
    for (const p of pixels) {{ if (p.i > cur) {{ next = p.i; break; }} }}
    if (next === null) next = N - 1;
    currentIndex = next;
    lastFlashedPixel = next;
    pixelFlashUntil = performance.now() + 400;
    if (lineTriggerSet.has(next)) {{
      lastFlashedLine = next;
      lineFlashUntil = performance.now() + 400;
    }}
    if (frameTriggerSet.has(next)) {{
      lastFlashedFrame = next;
      frameFlashUntil = performance.now() + 400;
    }}
  }});
  speedEl.addEventListener("input", () => {{
    speedMult = speedFromSlider(parseFloat(speedEl.value));
    speedLabel.textContent = speedMult.toFixed(1) + "×";
  }});
  loopChk.addEventListener("change", () => {{ loop = loopChk.checked; }});
  seekEl.addEventListener("input", () => {{
    playing = false;
    playBtn.textContent = "Play";
    currentIndex = parseFloat(seekEl.value);
    resetPlaybackState();
  }});

  goStartBtn.addEventListener("click", () => {{
    const wanted = Math.max(1, Math.min(pixels.length, parseInt(startPixelEl.value, 10) || 1));
    startPixelEl.value = String(wanted);
    const target = pixels[wanted - 1];
    if (!target) return;
    playing = false;
    playBtn.textContent = "Play";
    currentIndex = target.i;
    lastFlashedPixel = target.i;
    pixelFlashUntil = performance.now() + 450;
    lastLine = -1; // force recompute of "current line" readout at the new position
    if (lineTriggerSet.has(target.i)) {{
      lastFlashedLine = target.i;
      lineFlashUntil = performance.now() + 450;
    }}
    if (frameTriggerSet.has(target.i)) {{
      lastFlashedFrame = target.i;
      frameFlashUntil = performance.now() + 450;
    }}
  }});

  applyDelayBtn.addEventListener("click", () => {{
    applyDelays(
      parseFloat(pixelDelayEl.value) || 0,
      parseFloat(lineDelayEl.value) || 0,
      parseFloat(frameDelayEl.value) || 0
    );
    currentIndex = 0;
    resetPlaybackState();
    playing = true;
    playBtn.textContent = "Pause";
  }});

  window.addEventListener("resize", fitCanvas);

  // ---- initial setup: apply whatever delay values the page loaded with ----
  applyDelays(
    parseFloat(pixelDelayEl.value) || 0,
    parseFloat(lineDelayEl.value) || 0,
    parseFloat(frameDelayEl.value) || 0
  );

  requestAnimationFrame(tick);
}})();
</script>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scan-dir", default=None,
                     help="Folder to auto-discover the position/laser CSVs from "
                          "(content-based, any filename convention)")
    ap.add_argument("--pos-csv", default=None)
    ap.add_argument("--laser-csv", default=None)
    ap.add_argument("--sample-rate", type=float, default=1e6)
    ap.add_argument("--pixels-per-line", type=int, default=None,
                     help="Default: auto-inferred from the data")
    ap.add_argument("--gap-split", type=int, default=None,
                     help="Default: auto-detected from the data")
    ap.add_argument("--pixel-delay-us", type=float, default=0.0,
                     help="Initial value pre-filled into the page's Pixel Delay input (editable live)")
    ap.add_argument("--line-delay-us", type=float, default=0.0,
                     help="Initial value pre-filled into the page's Line Delay input (editable live)")
    ap.add_argument("--frame-delay-us", type=float, default=0.0,
                     help="Initial value pre-filled into the page's Frame Delay input (editable live)")
    ap.add_argument("--out", default="scan_animation.html")
    args = ap.parse_args()

    if args.pos_csv or args.laser_csv or args.scan_dir:
        args.pos_csv, args.laser_csv = gc.resolve_scan_files(
            args.scan_dir, args.pos_csv, args.laser_csv)
    else:
        args.pos_csv, args.laser_csv = "Correct_16x16.csv", "laser16x16.csv"

    data_obj = build_data(args.pos_csv, args.laser_csv, args.sample_rate,
                           pixels_per_line=args.pixels_per_line, gap_split=args.gap_split)
    data_json = json.dumps(data_obj, separators=(",", ":"))
    freqs = data_obj["freqs"]

    html = HTML_TEMPLATE.format(
        ARCHIVO=b64("fonts/Archivo.woff2"), PLEX400=b64("fonts/PlexMono-400.woff2"),
        PLEX500=b64("fonts/PlexMono-500.woff2"), PLEX600=b64("fonts/PlexMono-600.woff2"),
        DATA_JSON=data_json,
        N_MINUS_1=data_obj["n"] - 1,
        TOTAL_MS=f'{data_obj["n"] / args.sample_rate * 1000:.3f}',
        CANVAS_W=data_obj["canvasW"], CANVAS_H=data_obj["canvasH"],
        TIMING_VB_W=data_obj["timing"]["viewW"], TIMING_VB_H=data_obj["timing"]["viewH"],
        TIMING_VB_H_MARGIN=data_obj["timing"]["viewH"] + 22,
        TIMING_VIEW_H=data_obj["timing"]["viewH"],
        TIMING_LANES_SVG=timing_lanes_svg(data_obj),
        INIT_PIXEL_DELAY=args.pixel_delay_us, INIT_LINE_DELAY=args.line_delay_us,
        INIT_FRAME_DELAY=args.frame_delay_us,
        GRID_LABEL=data_obj["gridLabel"], TOTAL_PIXELS=data_obj["totalPixels"],
        NUM_LINES_LABEL=data_obj["numLinesLabel"], PPL_LABEL=data_obj["pplLabel"],
        PIXEL_HZ_LABEL=f'{freqs["pixelHz"]:,.1f} Hz · {freqs["pixelPeriodUs"]:.2f} µs period',
        LINE_HZ_LABEL=f'{freqs["lineHz"]:,.1f} Hz · {freqs["linePeriodUs"]:.2f} µs period',
        FRAME_HZ_LABEL=f'{freqs["frameHz"]:,.3f} Hz · {freqs["framePeriodMs"]:.3f} ms period',
    )

    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print(f"wrote {args.out} ({len(html)} chars)")


if __name__ == "__main__":
    main()
