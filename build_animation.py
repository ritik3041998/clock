"""
build_animation.py
===================
Self-contained generator for scan_animation.html — computes everything
directly from Correct_16x16.csv / laser16x16.csv (same detection logic as
generate_clocks.py) and emits a single static HTML page with an embedded
live playback animation. No intermediate/scratch files required.

Clock semantics match generate_clocks.py:
    Pixel Clock -> trigger, 1 sample wide, once per pixel counted (256/frame)
    Line Clock  -> two triggers per line, 1 sample wide each: line-start (1st
                   pixel) and line-complete (16th pixel, coincides with that
                   line's 16th Pixel Clock pulse) (32/frame). NOT held high
                   across the line.
    Frame Clock -> level, high for the whole frame span (1/frame).

Usage:
    python build_animation.py
"""
import csv
import json
import base64

SR = 1_000_000.0
DT = 1.0 / SR


def load_and_detect():
    pos, laser = [], []
    with open("Correct_16x16.csv", newline="") as f:
        for r in csv.reader(f):
            pos.append((float(r[0]), float(r[1])))
    with open("laser16x16.csv", newline="") as f:
        for r in csv.reader(f):
            laser.append(float(r[0]))
    n = len(pos)
    pixel_idx = [i for i, v in enumerate(laser) if v >= 2.5]
    lines = []
    cur = [pixel_idx[0]]
    for i in range(1, len(pixel_idx)):
        if pixel_idx[i] - pixel_idx[i - 1] > 36:
            lines.append(cur)
            cur = []
        cur.append(pixel_idx[i])
    lines.append(cur)
    assert len(lines) == 16 and all(len(l) == 16 for l in lines), \
        f"unexpected grouping: {len(lines)} lines"
    return n, pos, pixel_idx, lines


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


def build_data():
    n, pos, pixel_idx, lines = load_and_detect()

    # ---- canvas trajectory geometry ----
    xs = [p[0] for p in pos]
    ys = [p[1] for p in pos]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    PAD = 48
    W, H = 900, 720

    def nx(x):
        return PAD + (x - xmin) / (xmax - xmin) * (W - 2 * PAD)

    def ny(y):
        return PAD + (1 - (y - ymin) / (ymax - ymin)) * (H - 2 * PAD)

    traj_flat = []
    for x, y in pos:
        traj_flat.append(round(nx(x), 2))
        traj_flat.append(round(ny(y), 2))

    pixels_js = []
    for k, i in enumerate(pixel_idx):
        x, y = pos[i]
        pixels_js.append({"i": i, "x": round(nx(x), 2), "y": round(ny(y), 2),
                           "line": k // 16, "pix": k % 16})

    line_spans_js = [[l[0], l[-1]] for l in lines]      # structural: for "which line" readout
    # Line Clock is two triggers per line: line-start (1st pixel) and
    # line-complete (16th pixel) -- 32 sample indices total, not 16.
    line_triggers_js = []
    for l in lines:
        line_triggers_js.append(l[0])
        line_triggers_js.append(l[-1])
    # Frame Clock mirrors Line Clock: two triggers (start + complete), not a
    # held-high level.
    frame_js = [lines[0][0], lines[-1][-1]]
    frame_triggers_js = [lines[0][0], lines[-1][-1]]

    # ---- timing lane step paths ----
    total_ms = n * DT * 1000
    pulse_w = 0.006  # ms, visible thin pulse
    pixel_intervals = [(idx * DT * 1000, idx * DT * 1000 + pulse_w) for idx in pixel_idx]
    line_intervals = [(t * DT * 1000, t * DT * 1000 + pulse_w) for t in line_triggers_js]
    frame_intervals = [(t * DT * 1000, t * DT * 1000 + pulse_w) for t in frame_triggers_js]

    TW = 1000
    x0t, x1t = 10, TW - 10
    LANE_H, GAP = 92, 8
    y0 = 0
    lanes = {}
    for name in ["frame", "line", "pixel"]:
        y_hi = y0 + LANE_H * 0.18
        y_lo = y0 + LANE_H * 0.86
        lanes[name] = {"yHi": round(y_hi, 1), "yLo": round(y_lo, 1)}
        y0 += LANE_H + GAP
    total_h = y0 - GAP

    def Xmap(t_lo, t_hi, t):
        return x0t + (t - t_lo) / (t_hi - t_lo) * (x1t - x0t)

    def render(t_lo, t_hi):
        paths = {
            "pixel": build_step_path(pixel_intervals, t_lo, t_hi, lanes["pixel"]["yHi"], lanes["pixel"]["yLo"], x0t, x1t),
            "line": build_step_path(line_intervals, t_lo, t_hi, lanes["line"]["yHi"], lanes["line"]["yLo"], x0t, x1t),
            "frame": build_step_path(frame_intervals, t_lo, t_hi, lanes["frame"]["yHi"], lanes["frame"]["yLo"], x0t, x1t),
        }
        # numbered bold(start)/dotted(complete) markers, same convention as report.html
        markers = {"line": {"starts": [], "ends": []}, "frame": {"starts": [], "ends": []}}
        for k, l in enumerate(lines):
            t = l[0] * DT * 1000
            if t_lo <= t <= t_hi:
                markers["line"]["starts"].append([round(Xmap(t_lo, t_hi, t), 2), f"L{k+1}"])
        for l in lines:
            t = l[-1] * DT * 1000
            if t_lo <= t <= t_hi:
                markers["line"]["ends"].append(round(Xmap(t_lo, t_hi, t), 2))
        t = lines[0][0] * DT * 1000
        if t_lo <= t <= t_hi:
            markers["frame"]["starts"].append([round(Xmap(t_lo, t_hi, t), 2), "F1"])
        t = lines[-1][-1] * DT * 1000
        if t_lo <= t <= t_hi:
            markers["frame"]["ends"].append(round(Xmap(t_lo, t_hi, t), 2))
        return paths, markers

    paths, markers = render(0, total_ms)

    data = {
        "n": n,
        "canvasW": W, "canvasH": H,
        "traj": traj_flat,
        "pixels": pixels_js,
        "lineSpans": line_spans_js,
        "lineTriggers": line_triggers_js,
        "frame": frame_js,
        "frameTriggers": frame_triggers_js,
        "timing": {
            "viewW": TW, "viewH": total_h,
            "x0": x0t, "x1": x1t,
            "lanes": lanes,
            "paths": paths,
            "markers": markers,
        },
        "sampleRateHz": SR,
    }
    return data


def b64(fn):
    return base64.b64encode(open(fn, "rb").read()).decode("ascii")


def timing_lanes_svg(data):
    lanes = data["timing"]["lanes"]
    paths = data["timing"]["paths"]
    x0, x1, view_h = data["timing"]["x0"], data["timing"]["x1"], data["timing"]["viewH"]
    parts = []
    for name in ["frame", "line", "pixel"]:
        y_lo = lanes[name]["yLo"]
        parts.append(f'<line x1="{x0}" y1="{y_lo}" x2="{x1}" y2="{y_lo}" class="baseline"/>')
    for name in ["frame", "line", "pixel"]:
        parts.append(f'<path d="{paths[name]}" class="trace-dim trace-{name}"/>')
    parts.append(f'<clipPath id="revealClip"><rect id="revealRect" x="0" y="0" width="0" height="{view_h}"/></clipPath>')
    parts.append('<g clip-path="url(#revealClip)">')
    for name in ["frame", "line", "pixel"]:
        parts.append(f'<path d="{paths[name]}" class="trace-bright trace-{name}"/>')
    parts.append('</g>')
    # numbered bold(start)/dotted(complete) trigger markers on Line/Frame lanes
    markers = data["timing"].get("markers", {})
    for name in ["line", "frame"]:
        y_hi, y_lo = lanes[name]["yHi"], lanes[name]["yLo"]
        m = markers.get(name, {"starts": [], "ends": []})
        for x, text in m["starts"]:
            parts.append(f'<line x1="{x}" y1="{y_lo}" x2="{x}" y2="{y_hi-6:.1f}" class="marker-start marker-{name}"/>')
            parts.append(f'<text x="{x}" y="{y_hi-9:.1f}" text-anchor="middle" class="marker-label marker-label-{name}">{text}</text>')
        for x in m["ends"]:
            parts.append(f'<line x1="{x}" y1="{y_lo}" x2="{x}" y2="{y_hi}" class="marker-end marker-{name}"/>')
    for name in ["frame", "line", "pixel"]:
        y_hi, y_lo = lanes[name]["yHi"], lanes[name]["yLo"]
        mid = (y_hi + y_lo) / 2
        parts.append(f'<text x="6" y="{mid-6:.1f}" class="lane-label lane-label-{name}">{name.upper()}</text>')
    return "".join(parts)


ARCHIVO = b64("fonts/Archivo.woff2")
PLEX400 = b64("fonts/PlexMono-400.woff2")
PLEX500 = b64("fonts/PlexMono-500.woff2")
PLEX600 = b64("fonts/PlexMono-600.woff2")

DATA_OBJ = build_data()
DATA_JSON = json.dumps(DATA_OBJ, separators=(",", ":"))

HTML = """<!-- Live scan + clock generation animation -->
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
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 40px 22px 80px; }}

h1 {{
  font-family: "Archivo", system-ui, sans-serif;
  font-weight: 800;
  letter-spacing: -0.01em;
  text-wrap: balance;
  margin: 0;
  font-size: clamp(24px, 3.4vw, 32px);
  line-height: 1.14;
}}
.eyebrow {{
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--accent);
  margin: 0 0 10px;
}}
.subtitle {{
  margin: 12px 0 0;
  max-width: 66ch;
  color: var(--ink-dim);
  font-size: 13.5px;
}}

/* ---- transport bar ---- */
.transport {{
  margin-top: 26px;
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 8px;
  padding: 12px 16px;
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
.seek-row {{ margin-top: 12px; display: flex; align-items: center; gap: 12px; }}
#seek {{ flex: 1; width: 100%; height: 3px; }}
.seek-time {{ font-size: 11.5px; color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }}

/* ---- main grid ---- */
.stage {{
  margin-top: 24px;
  display: grid;
  grid-template-columns: 1.35fr 0.9fr;
  gap: 18px;
}}
@media (max-width: 880px) {{ .stage {{ grid-template-columns: 1fr; }} }}

.panel {{
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: 8px;
  box-shadow: var(--shadow);
  padding: 16px;
}}
.panel-title {{
  font-weight: 600;
  font-size: 10.5px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 10px;
}}
#scanCanvas {{ width: 100%; height: auto; display: block; border-radius: 4px; }}

/* ---- status column ---- */
.status-col {{ display: flex; flex-direction: column; gap: 14px; }}
.led-row {{ display: flex; flex-direction: column; gap: 10px; }}
.led-card {{
  display: grid;
  grid-template-columns: 22px 1fr auto;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--rule);
  border-left: 3px solid var(--led-color);
  border-radius: 5px;
  padding: 10px 12px;
  background: var(--surface-2);
}}
.led-card.pixel {{ --led-color: var(--c-pixel); }}
.led-card.line  {{ --led-color: var(--c-line); }}
.led-card.frame {{ --led-color: var(--c-frame); }}
.led-dot {{
  width: 13px; height: 13px;
  border-radius: 50%;
  background: var(--led-color);
  opacity: 0.18;
  transition: opacity 0.05s linear, box-shadow 0.05s linear;
}}
.led-dot.on {{ opacity: 1; box-shadow: 0 0 10px 1px var(--led-color); }}
.led-text {{ display: flex; flex-direction: column; gap: 1px; }}
.led-name {{ font-family: "Archivo", sans-serif; font-weight: 700; font-size: 12.5px; color: var(--ink); }}
.led-hz {{ font-size: 10.5px; color: var(--muted); font-variant-numeric: tabular-nums; }}
.led-kind {{ font-size: 9.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }}
.led-state {{
  font-size: 10px; font-weight: 600; letter-spacing: 0.06em;
  color: var(--muted); text-transform: uppercase;
  font-variant-numeric: tabular-nums;
}}

.readout-grid {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}}
.readout {{
  border: 1px solid var(--rule);
  border-radius: 5px;
  padding: 10px 12px;
  background: var(--surface-2);
}}
.readout .k {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }}
.readout .v {{
  font-family: "Archivo", sans-serif;
  font-weight: 800;
  font-size: 17px;
  color: var(--ink);
  margin-top: 3px;
  font-variant-numeric: tabular-nums;
}}
.readout .v small {{ font-family: "Plex Mono", monospace; font-weight: 500; font-size: 11px; color: var(--ink-dim); }}

/* ---- timing scope ---- */
.scope-wrap {{ margin-top: 18px; }}
.legend {{ display: flex; gap: 16px; margin: 0 0 10px; flex-wrap: wrap; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ink-dim); }}
.swatch {{ width: 11px; height: 11px; border-radius: 2px; flex: none; }}
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

footer {{ margin-top: 40px; padding-top: 18px; border-top: 1px solid var(--rule); font-size: 11.5px; color: var(--muted); }}
footer p {{ max-width: 70ch; margin: 4px 0; }}

.sr-only {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }}

@media (prefers-reduced-motion: reduce) {{
  .led-dot {{ transition: none; }}
}}
</style>

<div class="wrap">
  <header>
    <p class="eyebrow">Live Simulation · 16 × 16 Raster Scan</p>
    <h1>Watch the Laser Scan, Watch the Clocks Fire</h1>
    <p class="subtitle">Playback of the reconstructed sample-by-sample scan, slowed down so each
    trigger is visible. All three clocks are the same kind of signal — 1-sample pulses, never
    held high. Pixel Clock fires once per pixel; Line Clock and Frame Clock each fire twice —
    once on start, once on complete — at 1×16 and 1×256 the pixel rate.</p>
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
            <span class="led-text"><span class="led-name">Pixel Clock</span><span class="led-hz">33,333.3 Hz · 30.00 µs period</span><span class="led-kind">Trigger — 1 per pixel</span></span>
            <span class="led-state" id="statePixel">LOW</span>
          </div>
          <div class="led-card line">
            <span class="led-dot" id="ledLine"></span>
            <span class="led-text"><span class="led-name">Line Clock</span><span class="led-hz">2,024.8 Hz · 493.87 µs period</span><span class="led-kind">Trigger ×2 — line start + complete</span></span>
            <span class="led-state" id="stateLine">LOW</span>
          </div>
          <div class="led-card frame">
            <span class="led-dot" id="ledFrame"></span>
            <span class="led-text"><span class="led-name">Frame Clock</span><span class="led-hz">119.775 Hz · 8.349 ms period</span><span class="led-kind">Trigger ×2 — frame start + complete</span></span>
            <span class="led-state" id="stateFrame">LOW</span>
          </div>
        </div>
      </div>

      <div class="panel">
        <p class="panel-title">Position</p>
        <div class="readout-grid">
          <div class="readout"><div class="k">Sample</div><div class="v" id="roSample">0 <small>/ {N_MINUS_1}</small></div></div>
          <div class="readout"><div class="k">Sim. time</div><div class="v" id="roTime">0.000 <small>ms</small></div></div>
          <div class="readout"><div class="k">Line</div><div class="v" id="roLine">— <small>/ 16</small></div></div>
          <div class="readout"><div class="k">Pixel in line</div><div class="v" id="roPixel">— <small>/ 16</small></div></div>
        </div>
      </div>
    </div>
  </div>

  <div class="panel scope-wrap">
    <p class="panel-title">Timing Scope — frame gates two trigger trains (pixel ×1/px, line ×2/line)</p>
    <div class="legend">
      <span class="legend-item"><span class="swatch" style="background:var(--c-frame)"></span>Frame Clock (trigger ×2)</span>
      <span class="legend-item"><span class="swatch" style="background:var(--c-line)"></span>Line Clock (trigger ×2)</span>
      <span class="legend-item"><span class="swatch" style="background:var(--c-pixel)"></span>Pixel Clock (trigger)</span>
    </div>
    <svg id="timingSvg" class="timing-svg" viewBox="0 -22 {TIMING_VB_W} {TIMING_VB_H_MARGIN}" role="img" aria-label="Live timing diagram of pixel, line and frame clocks">
      <title>Live timing diagram</title>
      {TIMING_LANES_SVG}
      <line id="playhead" x1="0" y1="-22" x2="0" y2="{TIMING_VIEW_H}"/>
    </svg>
  </div>

  <footer>
    <p><b style="color:var(--ink)">How this works:</b> every frame of this animation reads one
    sample index into the same 8,349-row table used throughout this project
    (<code>clock_output.csv</code>). The beam's X/Y position, the pixel/line/frame clock states,
    and the scope trace are all lookups against that index — nothing here is re-simulated or
    approximated, it's the exact reconstructed data played back slower than its native 1 MSa/s
    rate so it's watchable. Line Clock fires two triggers per line — one coincident with the 1st
    Pixel Clock pulse (line start), one with the 16th (line complete) — the "Line" progress
    readout tracks the beam's structural position for context, independent of those two triggers.</p>
  </footer>
</div>

<script>
const DATA = {DATA_JSON};
</script>
<script>
(function() {{
  "use strict";
  const N = DATA.n;
  const traj = DATA.traj; // flat [x0,y0,x1,y1,...]
  const pixels = DATA.pixels; // [{{i,x,y,line,pix}}]
  const lineSpans = DATA.lineSpans; // structural: [[s,e],...] -- for "current line" readout only
  const lineTriggers = DATA.lineTriggers; // the actual Line Clock trigger sample indices
  const frameTriggers = DATA.frameTriggers; // the actual Frame Clock trigger sample indices ([start, end])
  const timing = DATA.timing;
  const SR = DATA.sampleRateHz;
  const dtMs = 1000 / SR;

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

  // baseline: 30-sample pixel period -> ~150ms real, scaled by speed slider
  const BASE_SAMPLES_PER_SEC = 200;
  function speedFromSlider(v) {{
    const t = v / 100;
    return Math.pow(10, (t * 2) - 1); // 0 -> 0.1x, 0.5 -> 1x, 1 -> 10x
  }}
  let speedMult = speedFromSlider(parseFloat(speedEl.value));
  speedLabel.textContent = speedMult.toFixed(1) + "×";

  // ---- lookup structures ----
  const pixelByIndex = new Map();
  pixels.forEach((p, k) => pixelByIndex.set(p.i, k));
  const lineTriggerSet = new Set(lineTriggers);
  const frameTriggerSet = new Set(frameTriggers);

  function findLine(idx) {{
    for (let k = 0; k < lineSpans.length; k++) {{
      if (idx >= lineSpans[k][0] && idx <= lineSpans[k][1]) return k;
    }}
    return -1;
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
    ctx.lineWidth = 1.2;
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
    ctx.lineWidth = 1.6;
    ctx.stroke();
    ctx.globalAlpha = 1;

    for (const p of pixels) {{
      const isLit = p.i <= currentIndex;
      const isLineTrigger = lineTriggerSet.has(p.i);
      const isFlashing = p.i === lastFlashedPixel && performance.now() < pixelFlashUntil;
      const isLineFlashing = isLineTrigger && p.i === lastFlashedLine && performance.now() < lineFlashUntil;
      const glowColor = isLineFlashing ? lineColor : pixelColor;
      ctx.beginPath();
      ctx.arc(p.x, p.y, (isFlashing || isLineFlashing) ? 6.6 : (isLit ? (isLineTrigger ? 5.0 : 4.4) : 3.2), 0, Math.PI * 2);
      if (isFlashing || isLineFlashing) {{
        ctx.fillStyle = glowColor;
        ctx.shadowColor = glowColor;
        ctx.shadowBlur = 15;
      }} else if (isLit) {{
        ctx.fillStyle = isLineTrigger ? lineColor : pixelColor;
        ctx.shadowBlur = 0;
      }} else {{
        ctx.fillStyle = "transparent";
        ctx.strokeStyle = inkDim;
        ctx.globalAlpha = 0.45;
        ctx.lineWidth = 1;
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
    ctx.arc(bx, by, 7, 0, Math.PI * 2);
    ctx.fillStyle = cssColor("--accent");
    ctx.shadowColor = cssColor("--accent");
    ctx.shadowBlur = 16;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.beginPath();
    ctx.arc(bx, by, 7, 0, Math.PI * 2);
    ctx.lineWidth = 2;
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
    roLine.innerHTML = (curLine >= 0 ? (curLine + 1) : "—") + " <small>/ 16</small>";
    roPixel.innerHTML = (curPixInLine >= 0 ? (curPixInLine + 1) : "—") + " <small>/ 16</small>";

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

  playBtn.addEventListener("click", () => {{
    playing = !playing;
    playBtn.textContent = playing ? "Pause" : "Play";
    lastTs = null;
  }});
  resetBtn.addEventListener("click", () => {{
    currentIndex = 0;
    lastFlashedPixel = -1;
    lastFlashedLine = -1;
    lastFlashedFrame = -1;
    lastPixInLine = -1;
    lastLine = -1;
    pixelFlashUntil = 0;
    lineFlashUntil = 0;
    frameFlashUntil = 0;
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
    lastFlashedPixel = -1;
    lastFlashedLine = -1;
    lastFlashedFrame = -1;
    lastLine = -1;
  }});

  window.addEventListener("resize", fitCanvas);

  requestAnimationFrame(tick);
}})();
</script>
"""

HTML = HTML.format(
    ARCHIVO=ARCHIVO, PLEX400=PLEX400, PLEX500=PLEX500, PLEX600=PLEX600,
    DATA_JSON=DATA_JSON,
    N_MINUS_1=DATA_OBJ["n"] - 1,
    TOTAL_MS=f'{DATA_OBJ["n"] / DATA_OBJ["sampleRateHz"] * 1000:.3f}',
    CANVAS_W=DATA_OBJ["canvasW"], CANVAS_H=DATA_OBJ["canvasH"],
    TIMING_VB_W=DATA_OBJ["timing"]["viewW"], TIMING_VB_H=DATA_OBJ["timing"]["viewH"],
    TIMING_VB_H_MARGIN=DATA_OBJ["timing"]["viewH"] + 22,
    TIMING_VIEW_H=DATA_OBJ["timing"]["viewH"],
    TIMING_LANES_SVG=timing_lanes_svg(DATA_OBJ),
)

with open("scan_animation.html", "w", encoding="utf-8", newline="\n") as f:
    f.write(HTML)

print("wrote scan_animation.html", len(HTML), "chars")
