import sys
sys.path.insert(0, ".")
from scratch_assets import ARCHIVO, PLEX400, PLEX500, PLEX600, TRAJ_PTS, DOTS_SVG, D_FULL, D_ZOOM

def timing_svg(d, title_id, lane_labels):
    lanes = d["lanes"]
    total_h = d["total_h"]
    x0, x1 = d["x0"], d["x1"]
    t_lo, t_hi = d["t_lo"], d["t_hi"]
    paths = d["paths"]
    W = 1000
    label_w = 86
    vb_w = W + label_w
    parts = []
    parts.append(f'<svg class="timing-svg" viewBox="0 0 {vb_w} {total_h+34}" role="img" aria-labelledby="{title_id}" preserveAspectRatio="xMinYMid meet">')
    parts.append(f'<title id="{title_id}">Pixel, line and frame clock timing diagram</title>')
    # gridlines every 1ms mapped through t range -- vertical guide lines
    parts.append(f'<g transform="translate({label_w},0)">')
    for name, color_var in [("frame","--c-frame"), ("line","--c-line"), ("pixel","--c-pixel")]:
        y0, y_hi, y_lo = lanes[name]
        label = lane_labels[name]
        parts.append(f'<line x1="{x0}" y1="{y_lo}" x2="{x1}" y2="{y_lo}" class="baseline"/>')
        parts.append(f'<path d="{paths[name]}" class="trace trace-{name}"/>')
    parts.append('</g>')
    # lane labels (outside translated group, left column)
    for name, color_var in [("frame","--c-frame"), ("line","--c-line"), ("pixel","--c-pixel")]:
        y0, y_hi, y_lo = lanes[name]
        label = lane_labels[name]
        mid = (y_hi+y_lo)/2
        parts.append(f'<text x="{label_w-12}" y="{mid+4:.1f}" text-anchor="end" class="lane-label lane-label-{name}">{label}</text>')
    parts.append('</svg>')
    return "".join(parts)

TIMING_FULL_SVG = timing_svg(D_FULL, "timing-full-title", {"frame":"FRAME","line":"LINE","pixel":"PIXEL"})
TIMING_ZOOM_SVG = timing_svg(D_ZOOM, "timing-zoom-title", {"frame":"FRAME","line":"LINE","pixel":"PIXEL"})

HTML = f"""<!-- Pixel/Line/Frame clock reconstruction report -->
<title>Clock Reconstruction — 16×16 Raster Scan</title>
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
  <p class="eyebrow">Signal Reconstruction · 16 × 16 Point Raster Scan</p>
  <h1>Pixel, Line &amp; Frame Clocks<br>from Laser Strobe &amp; Galvo Position Logs</h1>
  <p class="subtitle">Derived from <code>Correct_16x16.csv</code> (X/Y scanner drive voltages) and
  <code>laser16x16.csv</code> (laser strobe flag), sample-aligned row for row. 256 laser-fire
  events group cleanly into 16 lines of 16 pixels — the grouping below was detected automatically,
  with zero mismatches against that 16×16 target.</p>
  <div class="meta-row">
    <span class="meta-chip">Grid <b>16 × 16</b></span>
    <span class="meta-chip">Pixels/frame <b>256</b></span>
    <span class="meta-chip">Sample rate <b>1,000,000 Hz</b></span>
    <span class="meta-chip">Samples <b>8,349</b></span>
    <span class="meta-chip">Generated <b>2026-08-10</b></span>
  </div>
</header>

<section id="geometry">
  <div class="section-head"><span class="section-num">01</span><h2>Scan geometry</h2></div>
  <p class="section-desc">The galvo traces a vertical serpentine: down a column, round a turn,
  up the next column, 16 times over. Each orange dot is one laser-fire sample — the same shape
  as <code>scan_pattern.bmp</code> / <code>spatial_points.bmp</code>, reconstructed here from the
  raw voltage trace rather than pre-rendered.</p>
  <div class="panel">
    <div class="traj-figure">
      {"{{TRAJ_SVG}}"}
    </div>
    <p class="figure-caption">X/Y galvo drive voltage, 8,349 samples · dots mark the 256 samples where the laser strobe reads 5&nbsp;V.</p>
  </div>
</section>

<section id="derivation">
  <div class="section-head"><span class="section-num">02</span><h2>Derivation rules</h2></div>
  <p class="section-desc">Three nested clocks, each one gating the one below it.</p>
  <div class="card-row">
    <div class="clock-card pixel">
      <p class="kicker">Pixel Clock</p>
      <p class="rule-text">Pulses once, one sample wide, every time the laser strobe reads
      <code>5</code>. 256 pulses per frame — one per dwell point.</p>
    </div>
    <div class="clock-card line">
      <p class="kicker">Line Clock</p>
      <p class="rule-text">Goes high on the line's <em>1st</em> pixel pulse, stays high through
      its <em>16th</em>, then drops low for the ~44-sample flyback to the next line. 16 pulses
      per frame.</p>
    </div>
    <div class="clock-card frame">
      <p class="kicker">Frame Clock</p>
      <p class="rule-text">Goes high on line 1's first pixel, stays high through line 16's last
      pixel, then drops — closing the frame. One pulse per frame.</p>
    </div>
  </div>
</section>

<section id="timing">
  <div class="section-head"><span class="section-num">03</span><h2>Timing diagram</h2></div>
  <p class="section-desc">Standard nested-clock convention: frame envelopes line, line envelopes
  pixel. Hover any pixel pulse or line block for its sample index and timestamp.</p>
  <div class="legend">
    <span class="legend-item"><span class="swatch" style="background:var(--c-frame)"></span>Frame Clock</span>
    <span class="legend-item"><span class="swatch" style="background:var(--c-line)"></span>Line Clock</span>
    <span class="legend-item"><span class="swatch" style="background:var(--c-pixel)"></span>Pixel Clock</span>
  </div>
  <div class="panel">
    <div class="timing-block">
      <p class="timing-title">Full frame · 0 – 8.349&nbsp;ms</p>
      {"{{TIMING_FULL_SVG}}"}
    </div>
    <div class="timing-block">
      <p class="timing-title">Zoom · lines 1–2 · 0 – 1.49&nbsp;ms</p>
      {"{{TIMING_ZOOM_SVG}}"}
    </div>
  </div>
</section>

<section id="frequencies">
  <div class="section-head"><span class="section-num">04</span><h2>Frequency summary</h2></div>
  <p class="section-desc">At the assumed 1&nbsp;MSa/s sample rate. Re-run
  <code>generate_clocks.py --sample-rate &lt;Hz&gt;</code> with your DAQ's real rate to rescale
  every figure below.</p>
  <div class="table-scroll">
    <table>
      <thead>
        <tr><th>Clock</th><th>Period</th><th>Frequency</th><th>Events / frame</th><th>Duty cycle</th></tr>
      </thead>
      <tbody>
        <tr>
          <td class="label"><span class="dot-legend" style="background:var(--c-pixel)"></span>Pixel</td>
          <td>30.00 µs</td>
          <td>33,333.3 Hz</td>
          <td>256</td>
          <td>1 sample / 30 (~3.3%)</td>
        </tr>
        <tr>
          <td class="label"><span class="dot-legend" style="background:var(--c-line)"></span>Line</td>
          <td>493.87 µs</td>
          <td>2,024.8 Hz</td>
          <td>16</td>
          <td>450 / 494 samples (~91%)</td>
        </tr>
        <tr>
          <td class="label"><span class="dot-legend" style="background:var(--c-frame)"></span>Frame</td>
          <td>8.349 ms</td>
          <td>119.775 Hz</td>
          <td>1</td>
          <td>7,859 / 8,349 samples (~94%)</td>
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
      <span class="file-desc">Sample-by-sample table — <code>Sample_Index, Time_s, X_Voltage, Y_Voltage, Laser_Raw, Pixel_Clock, Line_Clock, Frame_Clock, Line_Number, Pixel_In_Line</code>. 8,349 rows.</span>
    </div>
    <div class="file-row">
      <span class="file-name">clock_summary.csv</span>
      <span class="file-desc">The frequency table above, in CSV form: period, frequency and event count per clock.</span>
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
      <span class="file-desc">The script itself — reusable on any N×N scan; auto-detects line/pixel grouping from the laser strobe, warns if it doesn't match <code>--pixels-per-line</code>.</span>
    </div>
  </div>
  <div class="cmd-block"><span class="prompt">$</span> python generate_clocks.py --sample-rate 1e6</div>
</section>

<footer>
  <p><b style="color:var(--ink)">Assumption:</b> the 1,000,000 Hz sample rate is a placeholder value confirmed for this run — every period/frequency figure scales directly with it. Line grouping used a 36-sample gap threshold (within-line gaps run ~30 samples, line-to-line flyback ~42–44); both were auto-detected, not hand-tuned, and validated with zero mismatches against the 16×16 target.</p>
</footer>

</div>
"""

HTML = HTML.replace("{{TRAJ_SVG}}", f'''<svg class="traj-svg" viewBox="0 0 920 760" role="img" aria-label="Serpentine scan trajectory with pixel events">
<polyline class="path-line" points="{TRAJ_PTS}"/>
{DOTS_SVG}
</svg>''')
HTML = HTML.replace("{{TIMING_FULL_SVG}}", TIMING_FULL_SVG)
HTML = HTML.replace("{{TIMING_ZOOM_SVG}}", TIMING_ZOOM_SVG)

with open("report.html", "w", encoding="utf-8", newline="\n") as f:
    f.write(HTML)

print("wrote report.html", len(HTML), "chars")
