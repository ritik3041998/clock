# Clock Reconstruction — 16×16 Raster Scan

This folder reconstructs **Pixel Clock**, **Line Clock**, and **Frame Clock**
digital signals for a 16×16 point galvo/laser raster scan, from two raw
logger files (scanner drive voltage + laser strobe flag). It also produces
CSV outputs with all the signals/voltages together, frequency numbers, and
plots/visualizations.

If you only want to *run* things, jump to [Quick start](#quick-start).
Everything below that explains *how* and *why* it works.

---

## 1. The problem, in plain terms

A galvo-mirror laser scanner sweeps a beam across a 16×16 grid of points.
Two things are logged by the DAQ while it scans, **one row per sample, at a
fixed sample rate**:

- Where the mirrors are pointing (an analog X/Y drive voltage)
- Whether the laser is firing right now (on/off)

What's *not* logged directly is the **digital timing signals** a downstream
system (camera, detector, FPGA, etc.) would need to know:

- **Pixel Clock** — "a pixel just happened, capture it" (a trigger)
- **Line Clock** — "a line just started" / "a line just completed" (two triggers)
- **Frame Clock** — "a frame just started" / "a frame just completed" (two triggers)

This pipeline reverse-engineers those three clocks purely from the logged
voltage + laser data, with no extra hardware or extra logging needed.

---

## 2. The input files

| File | Columns | What it is |
|---|---|---|
| `Correct_16x16.csv` | `X_Voltage, Y_Voltage` | Analog galvo mirror drive voltage, **one row per DAQ sample**. This is the continuous physical path the beam follows (straight sweeps + curved turnarounds), not just the 256 grid points. |
| `laser16x16.csv` | `col1, col2` (always equal) | Laser strobe flag, **same row-for-row alignment** as the position file. `0,0` = laser off. `5,5` = laser fires (5 V TTL-style strobe). |

Both files have **8,349 rows** — they are two logs of the *same* sample
clock, just recording different signals. Row `i` in one file always
corresponds to row `i` in the other.

Also present (not used by the pipeline, kept for reference):
`16x16_lines.csv`, `16x16_meas.csv`, `scan_pattern.bmp`, `spatial_points.bmp`
— these are the original reference renderings the reconstructed trajectory
plot is checked against.

### What the data actually looks like

```
Sample  X_Voltage   Y_Voltage   Laser
465     -1.090296   1.95264     0        <- beam moving, laser off
466     -1.090272   1.94412     0
467     -1.090248   1.93560     0
468     -1.090224   1.92708     5        <- PIXEL: laser fires here
469     -1.090200   1.91856     0
...     (30 samples later)
498     -1.089492   1.65432     5        <- next pixel in the same line
```

- **X barely moves** within a line (≈0.00002 V/sample) — the scan is a
  near-vertical line; **Y sweeps** steadily.
- The laser fires **every ~30 samples** while dwelling on a line (16 times).
- Between the last pixel of one line and the first pixel of the next, there's
  a bigger **~44 sample gap** — that's the mirror decelerating, turning
  around, and re-accelerating (the rounded end-caps you can see in
  `scan_pattern.bmp`).

This structure (16 pixels/line spaced ~30 samples apart, 16 lines spaced
~44-sample turnarounds apart) was **discovered empirically** by inspecting
the files, not assumed — `generate_clocks.py` re-derives it at runtime from
whatever data it's given, so it isn't hard-coded to this one file.

---

## 3. The pipeline, file by file

```
Correct_16x16.csv  ─┐
                     ├──►  generate_clocks.py  ──►  clock_output.csv   (full sample table)
laser16x16.csv     ─┘   │                     ──►  clock_summary.csv (frequencies)
                         │                     ──►  viz_*.png        (quick-look plots)
                         │
                         ├──►  build_report.py     ──►  report.html         (shareable write-up)
                         └──►  build_animation.py  ──►  scan_animation.html (live playback)

clock_output.csv  ──►  visualize_clocks.py  ──►  scan_trajectory.png
                                              ──►  timing_full_frame.png
                                              ──►  timing_zoom.png
```

`build_report.py` and `build_animation.py` both `import generate_clocks` and
call its `build_clocks()` directly — they don't re-implement pixel/line
detection or the delay logic, so the report and the live animation can never
drift out of sync with what the core pipeline actually does. Both accept
the same `--sample-rate` / `--pixel-delay-us` / `--line-delay-us` /
`--frame-delay-us` flags as `generate_clocks.py` (see §3.1's delay section)
and regenerate their HTML output in place when re-run.

### 3.1 `generate_clocks.py` — the core script

This is the only script that does real signal-processing work. Everything
else just reads its output.

**Step 1 — load & align.** Reads both CSVs into parallel lists; errors out
immediately if the row counts don't match (they must, since they're the same
sample clock).

**Step 2 — find every pixel event.**
```python
laser_on = laser value >= 2.5   # robust threshold between 0 and 5
pixel_idx = every sample index where laser_on is True
```

**Step 3 — group pixel events into lines.** Walk through the pixel sample
indices in order and look at the **gap** to the previous one:
```python
gap = pixel_idx[i] - pixel_idx[i-1]
if gap > gap_split (default 36):   # bigger than a normal within-line gap
    start a new line
else:
    same line, just the next pixel
```
`gap_split = 36` sits right between the observed ~30-sample within-line gap
and the ~44-sample line-to-line gap, so it cleanly separates the two without
being hand-fit to this exact file. The script also **sanity-checks** the
result (warns if it doesn't find `pixels_per_line` pixels per line, or a
different number of lines than expected) instead of silently assuming the
16×16 structure held.

**Step 4 — build the three clock arrays.** Same length as the input
(8,349 samples), initialized to 0:

| Clock | Rule |
|---|---|
| `Pixel_Clock` | **Trigger.** `1` for exactly the 1 sample where a laser event happened, else `0` — a 1-sample pulse per pixel counted. |
| `Line_Clock` | **Two triggers per line.** `1` for exactly the 1 sample where a line's **1st** pixel fires (line-start pulse), and `1` again at the 1 sample where its **16th** pixel fires (line-complete pulse, coincides with that pixel's `Pixel_Clock` pulse). `0` at every other sample, including all the samples in between — it does **not** stay high across the line. |
| `Frame_Clock` | **Two triggers per frame.** `1` for exactly the 1 sample where the frame's **1st** pixel fires (frame-start pulse — line 1's 1st pixel), and `1` again at the 1 sample where its **last** pixel fires (frame-complete pulse — line 16's 16th pixel). `0` everywhere else — it does **not** stay high across the frame. |

All three clocks are deliberately the *same kind* of signal: 1-sample
triggers, never held high. They differ only in how often they fire — Pixel
once per pixel (256/frame), Line twice per line at 1×16 the pixel rate
(32/frame), Frame twice per frame at 1×256 the pixel rate (2/frame). A Line
Clock "complete" pulse always lands exactly on that line's 16th Pixel Clock
pulse; the Frame Clock "complete" pulse always lands on the 16th line's
"complete" pulse (both fire on the same, very last sample of the frame).

It also records, per sample, which `Line_Number` (0–15) and `Pixel_In_Line`
(0–15) it belongs to, or `-1` if it's outside any pixel/line.

**Step 5 — compute real frequencies.** The arrays above are all in *sample*
units. To turn them into Hz, the script needs a **sample rate** — this is
the one piece of information that isn't in the CSVs (a DAQ logs voltages,
not its own clock rate), so it's passed in as `--sample-rate` (Hz). Given
that:
- **Pixel period** = average gap between consecutive pixel events within a
  line, in seconds → pixel frequency = `1 / period`.
- **Line period** = average gap between consecutive Line Clock "complete"
  triggers (the 16th pixel of one line to the 16th pixel of the next —
  dwell time + turnaround) → line frequency.
- **Frame period** = total number of samples in the file × sample period —
  i.e. the file is treated as exactly one full frame (start delay through
  end tail) that then repeats.

**Step 6 — write outputs & plots** (see next section).

Run it with:
```bash
python generate_clocks.py --sample-rate 1e6
```
`--sample-rate` is the only value you're likely to need to change — set it
to whatever your real DAQ/galvo controller runs at. Everything else
(`--pos-csv`, `--laser-csv`, `--pixels-per-line`, `--out-prefix`) has
sensible defaults matching this dataset.

#### Optional: per-clock start delay

By default every clock fires at the exact sample its physical event
happens — Pixel Clock the instant the laser fires, Line/Frame Clock the
instant their start/complete pixel fires. Real hardware is rarely that
clean: each signal usually has its own small propagation/processing
latency, so Pixel, Line and Frame Clock don't all assert at literally the
same instant. Three optional flags model that, independently, in
microseconds:

```bash
python generate_clocks.py --sample-rate 1e6 \
    --pixel-delay-us 2 --line-delay-us 8 --frame-delay-us 15
```

Each is converted to a whole number of samples internally
(`round(delay_us / (1e6 / sample_rate))`) and just shifts that clock's `1`s
later in `clock_output.csv` — the underlying `X_Voltage`/`Y_Voltage`/
`Laser_Raw` columns (the actual measured scan) never change, and each
clock's own period/frequency is unaffected (a constant delay applied to
every pulse of one clock cancels out of that clock's own period
measurement — only its *phase relative to the other two clocks* moves).
All three default to `0` (today's behavior, all three phase-aligned to the
physical event) — set only the ones you need. If a delay is large enough
to push a trigger past the end of the recorded file, or to collide with
the next trigger of the same clock, the script prints a `[warn]` instead of
silently corrupting the data.

### 3.2 `visualize_clocks.py` — plotting only

A second, independent script that **only reads `clock_output.csv`** and
draws pictures from it — it never touches the raw CSVs or re-derives
anything. This is deliberate: you can re-plot as many times as you like
(different zoom windows, different color themes) without re-running the
detection logic in step 2–4 above.

It draws:
1. **`scan_trajectory.png`** — the X/Y voltage path (grey line) with every
   pixel-clock event marked as a dot (orange), reproducing the shape in
   `scan_pattern.bmp` directly from the reconstructed data.
2. **`timing_full_frame.png`** — Pixel/Line/Frame clocks stacked as digital
   step traces across the whole 8.349 ms frame, with numbered bold/dotted
   start-vs-complete markers on the Line and Frame lanes (see §5).
3. **`timing_zoom.png`** — the same three traces, zoomed to just the first
   `--zoom-lines` lines (default 2) so individual pixel pulses are legible.

Colors are fixed and consistent across every figure this pipeline produces:
**pixel = orange `#eb6834`**, **line = blue `#2a78d6`**, **frame = green
`#1baf7a`**.

```bash
python visualize_clocks.py                        # defaults
python visualize_clocks.py --zoom-lines 4 --show   # wider zoom, pop up windows
```

### 3.3 `report.html` / `build_report.py` — the shareable write-up

`build_report.py` regenerates the polished HTML report (published as a
Claude Artifact) straight from the two source CSVs, via `generate_clocks.
build_clocks()` — the same detection/delay logic as §3.1, not a
reimplementation. It constructs inline SVG figures (not matplotlib) so the
report renders crisply at any size and matches light/dark viewing themes,
and needs the font files under `fonts/`.

```bash
python build_report.py --sample-rate 1e6
python build_report.py --line-delay-us 8 --frame-delay-us 15 --out report_delayed.html
```

### 3.4 `scan_animation.html` / `build_animation.py` — the live playback

Different from `build_report.py` in one important way: **the delay is a
live, in-browser control here, not baked in at build time.** The page ships
the *physical* (undelayed) scan structure — 256 pixel events grouped into
16 lines, plus the physical frame span — and a small JS engine
(`applyDelays()`) that recomputes every trigger position, the timing-scope
paths, and the numbered markers **in the browser**, instantly, whenever you
edit a delay input and click **Apply**. No server, no rebuild.

The page has two interactive controls beyond play/pause/speed/seek:

- **Start at pixel #** — jump playback straight to any of the 256 pixels
  (1–256) via the number input + **Go** button, instead of always starting
  at sample 0.
- **Pixel / Line / Frame delay (µs)** — three number inputs + **Apply**.
  Editing these and clicking Apply re-derives the delayed trigger set from
  the embedded physical data, exactly like `generate_clocks.py`'s
  `--pixel/line/frame-delay-us`, including the same drop-and-warn behavior
  if a delay pushes a trigger past the end of the recorded window (shown as
  an on-page banner instead of a console `[warn]`).

`--pixel/line/frame-delay-us` on the command line still exist, but now they
only set the *initial* values the page's delay inputs load with — the CLI
flags are a convenience for opening the page pre-configured, not a
requirement; every value is editable live afterward.

```bash
python build_animation.py --line-delay-us 12   # page opens with Line Delay pre-filled to 12 µs
```

#### Why one frame takes way more than 8.349 ms to watch

The frequency summary (§4) says a frame is 8.349 ms — that's correct, and
it's what the page's **Sim. time** readout counts up. But 8.349 ms is
faster than a human eye can register a single blink, let alone 256
individual pixel pulses, so the animation deliberately plays back in slow
motion. Two different clocks are running at once:

- **Simulated time** — what a real 1 MSa/s clock experiences: 8,349
  samples × 1 µs = 8.349 ms. This is the number in the readouts and the
  report; it never changes regardless of playback speed.
- **Wall-clock playback time** — how long *you* actually watch it take in
  the browser, controlled by the **Speed** slider.

The slider scales a baseline of `BASE_SAMPLES_PER_SEC = 200` (see the
`speedFromSlider()` function in `build_animation.py`'s embedded JS),
exponentially from 0.1× to 10× as you drag it. At the default position
(~0.79×) that works out to roughly **150 ms of real time per pixel-to-pixel
step** — enough for each LED flash to actually be visible — which stretches
the whole 8.349 ms frame out to **~52 seconds** of real playback, about
6,300× slower than the real clock. Drag the Speed slider to the right for a
faster (down to ~4 seconds/frame at max) but less readable playback.

---

## 4. The outputs, explained column by column

### `clock_output.csv` — the master table (8,349 rows)

| Column | Meaning |
|---|---|
| `Sample_Index` | Row number, 0-based, same order as the source CSVs. |
| `Time_s` | `Sample_Index / sample_rate`, in seconds. |
| `X_Voltage`, `Y_Voltage` | Galvo drive voltage at this sample (from `Correct_16x16.csv`). |
| `Laser_Raw` | The raw laser strobe value at this sample (`0.0` or `5.0`). |
| `Pixel_Clock` | `1` on the exact sample a pixel fires, else `0` (trigger). |
| `Line_Clock` | `1` on the exact sample a line's 1st pixel fires **and** again on its 16th pixel (coincides with that pixel's `Pixel_Clock=1`), else `0` (two triggers per line — **not** held high across the line). |
| `Frame_Clock` | `1` on the exact sample the frame's 1st pixel fires **and** again on the frame's last pixel, else `0` (two triggers per frame — **not** held high across the frame). |
| `Line_Number` | Which line (`0`–`15`) this sample belongs to, or `-1` if between lines / outside the frame. |
| `Pixel_In_Line` | Which pixel within that line (`0`–`15`) this sample *is*, or `-1` if it isn't a pixel sample. |

### `clock_summary.csv` — one row per clock

| Column | Meaning |
|---|---|
| `Period_s` / `Period_ms` | Average time between rising edges. For Line/Frame Clock this is the per-*line*/per-*frame* period (start to next start), not the gap between the two pulses within one line/frame. |
| `Frequency_Hz` | `1 / Period_s`. |
| `Events_Per_Frame` | 256 for Pixel, **32** for Line (2 triggers × 16 lines), **2** for Frame (start + complete). |
| `Start_Delay_us` | The `--pixel-delay-us` / `--line-delay-us` / `--frame-delay-us` that clock was generated with (`0.000` by default). |

At the assumed 1 MSa/s sample rate:

| Clock | Period | Frequency | Events/frame |
|---|---|---|---|
| Pixel | 30.00 µs | 33,333.3 Hz | 256 |
| Line | 493.87 µs | 2,024.8 Hz | 32 (16 start + 16 complete) |
| Frame | 8.349 ms | 119.775 Hz | 2 (start + complete) |

**These numbers move directly with `--sample-rate`.** If your DAQ actually
runs at, say, 500 kSa/s instead of 1 MSa/s, every period doubles and every
frequency halves — the *sample-domain* structure (30-sample pixel spacing,
16×16 grid) stays exactly the same, only the Hz conversion changes. Rerun
`generate_clocks.py --sample-rate <your value>` to get correct numbers.

---

## 5. How the three clocks relate (three trigger trains, same kind of signal)

```
Frame Clock   ▏                                                              ▏
Line Clock    ▏             ▏  ▏             ▏  ▏             ▏  ...         ▏
Pixel Clock   ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏    ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏    ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏
              └─────line 1─────┘ gap └─────line 2─────┘ gap  ...  (×16 lines)
              └──────────────────── 1 frame ────────────────────┘
```

- **Pixel Clock** fires once per pixel — 16 pulses per line, 256 per frame.
- **Line Clock** fires *twice* per line: once at the line's 1st pixel
  (line-start pulse) and once at its 16th (line-complete pulse, landing
  exactly on that pixel's Pixel Clock pulse — the second `▏` in each line's
  group above). 32 pulses per frame.
- **Frame Clock** fires *twice* per frame: once at line 1's 1st pixel
  (frame-start — the very first `▏` above, coincident with Line Clock's
  L1-start pulse) and once at line 16's 16th pixel (frame-complete — the
  very last `▏`, coincident with Line Clock's L16-complete pulse). 2 pulses
  per frame.

All three are trigger trains at three different rates (1×, 1×16, 1×256 the
pixel rate) rather than one being a continuous span gating the others —
there is no level/held-high signal anywhere in this pipeline anymore.

**Visualizing start vs. complete:** every plot and diagram in this project
(matplotlib PNGs, the report, the live animation) uses one convention: a
**bold solid** vertical marker, numbered (`L1`, `L2`, … / `F1`), on a
"start" trigger, and a **dotted** vertical marker on the matching
"complete" trigger.

---

## 6. Design choices & things to double-check

- **`gap_split = 36` samples by default, now a `--gap-split` CLI flag.** This
  threshold decides "same line" vs "next line." It's derived from the
  16×16 data (within-line gaps cluster at 30, line-to-line gaps at 42–44) —
  if you point this at a different scan pattern with different dwell/
  flyback timing, check the `[warn]` messages `generate_clocks.py` prints;
  they tell you if the detected line/pixel counts don't match
  `--pixels-per-line`, and let you re-tune `--gap-split` if the default
  misdetects your line boundaries.
- **Sample rate is an assumption, not measured.** Nothing in the CSVs states
  the DAQ's actual sample rate — 1 MSa/s was confirmed for this run, but
  it's a single `--sample-rate` argument if that's wrong.
- **Frame period = whole file length.** The script assumes the file
  represents exactly one frame (delay + 16 lines + tail) that then loops.
  If your logger captures multiple frames per file, this would need
  updating to detect frame boundaries instead of using the file length.
- **All three clocks are made of 1-sample trigger pulses**, not
  50%-duty-cycle square waves or held-high gates. That matches "strobe"
  semantics (fire once when something happens) rather than a free-running
  oscillator. Line Clock and Frame Clock both used to be levels held high
  across their duration — they're now `line_clock[start]=1` /
  `line_clock[end]=1` and `frame_clock[frame_start]=1` /
  `frame_clock[frame_end]=1` in `build_clocks()`, marking "started" and
  "complete" instead of gating the duration. If you need either as a
  held-high signal instead, that's a one-line change back to
  `line_clock[start:end+1] = 1` (or the frame equivalent).
- **Per-clock start delay is a phase shift, not a rate change.** `--pixel-
  delay-us` / `--line-delay-us` / `--frame-delay-us` (see §3.1) move each
  clock's pulses later in time independently to model real hardware
  latency, defaulting to `0` (no delay, all three phase-aligned as before).
  The markers (§5) always reflect the actual delayed positions — they're
  read straight back out of the `Pixel_Clock`/`Line_Clock`/`Frame_Clock`
  columns, not recomputed from the physical event times, so they stay
  correct under any delay.

- **The pipeline is not limited to 16×16.** `build_clocks()`'s line
  detection is purely gap-based (§ above) — it doesn't assume a fixed
  line count or a fixed pixels-per-line, so `generate_clocks.py`,
  `build_report.py` and `build_animation.py` all work unmodified on any
  N-line, M-pixels-per-line raster scan. `--pixels-per-line` only feeds a
  sanity-check warning; it never changes what gets detected. Verified
  end-to-end against real `SCAN-PATTERNS/32x32_Pattern/` data (32 lines ×
  38 laser-fire points/line, detected automatically with the default
  `--gap-split 36`) — the CSV output, matplotlib plots, HTML report and
  live animation all render correctly with dynamically computed grid
  labels, pixel counts and per-line numbering instead of a hardcoded
  "16"/"256".

---

## 7. Quick start

```bash
# 1. Install dependencies (once)
python -m pip install pandas matplotlib numpy

# 2. Derive the clocks (reads the raw CSVs, writes clock_output.csv etc.)
python generate_clocks.py --sample-rate 1e6

# 3. Plot from the derived table (reads clock_output.csv, writes PNGs)
python visualize_clocks.py --zoom-lines 2
```

## 8. File index

| File | Role |
|---|---|
| `Correct_16x16.csv` | Raw input: galvo X/Y drive voltage per sample. |
| `laser16x16.csv` | Raw input: laser strobe flag per sample. |
| `generate_clocks.py` | **Core pipeline** — detects pixels/lines, builds all 3 clocks (with optional `--pixel/line/frame-delay-us`), computes frequencies, writes CSVs + quick-look PNGs. Also importable — `build_report.py`/`build_animation.py` call its functions directly. |
| `visualize_clocks.py` | **Standalone plotting** — reads `clock_output.csv`, redraws the trajectory + timing figures anytime, in the report's color scheme. |
| `clock_output.csv` | Full sample-by-sample table: voltages + all three clocks. |
| `clock_summary.csv` | Period/frequency/event-count/start-delay per clock. |
| `viz_scan_pattern.png`, `viz_timing_full.png`, `viz_timing_zoom.png` | Quick-look plots written directly by `generate_clocks.py`. |
| `scan_trajectory.png`, `timing_full_frame.png`, `timing_zoom.png` | Plots written by `visualize_clocks.py` (report color scheme). |
| `report.html`, `build_report.py` | The published write-up artifact + its self-contained generator (imports `generate_clocks`, same delay flags). |
| `scan_animation.html`, `build_animation.py` | The published live-playback artifact + its self-contained generator (imports `generate_clocks`, same delay flags). |
| `fonts/` | Archivo + IBM Plex Mono `.woff2` files, embedded as data URIs by both build scripts. |
| `16x16_lines.csv`, `16x16_meas.csv`, `scan_pattern.bmp`, `spatial_points.bmp` | Reference files from the original dataset, used to validate the reconstruction, not consumed by any script. |




Tier	Pixel delay	Line delay	Frame delay	What you'll see
Subtle (what you tried)	2 µs	8 µs	15 µs	Technically correct, but invisible without zooming way in — only ~0.4% of the plotted window
Moderate (recommended)	5 µs	15 µs	60 µs	Clear, obvious offset between the orange/blue/green markers in viz_timing_zoom.png
Dramatic	10 µs	40 µs	150 µs	Unmistakable at a glance, markers clearly separated in both zoom and full-frame plots