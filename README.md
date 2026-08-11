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
- **Line Clock** — "16 pixels were just counted, a line just completed" (a trigger)
- **Frame Clock** — "we are currently scanning a full 16×16 frame" (a level)

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
laser16x16.csv     ─┘                          ──►  clock_summary.csv (frequencies)
                                                 ──►  viz_*.png        (quick-look plots)

clock_output.csv  ──►  visualize_clocks.py  ──►  scan_trajectory.png
                                              ──►  timing_full_frame.png
                                              ──►  timing_zoom.png

(report.html / build_report.py — one-off script that built the shareable
 write-up artifact; not part of the day-to-day pipeline)
```

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
| `Line_Clock` | **Trigger.** `1` for exactly the 1 sample where a line's **16th** pixel is counted (the same instant as that pixel's `Pixel_Clock` pulse), else `0`. It does **not** stay high across the line — it's a "16-pixels-counted" trigger, not a gate. |
| `Frame_Clock` | **Level.** `1` from line 1's first pixel through line 16's last pixel; `0` outside that (start-up delay and end-of-frame tail) — one on/off span = one frame counted. |

Pixel and Line Clock are deliberately the *same kind* of signal: both are
1-sample count-complete triggers, Pixel firing every 1 pixel and Line firing
every 16 pixels (so a Line Clock pulse always lands exactly on top of every
16th Pixel Clock pulse). Frame Clock is the odd one out on purpose — it's a
level signal that stays high for the scan's full duration, matching "the
frame is in progress" rather than "an event just happened."

It also records, per sample, which `Line_Number` (0–15) and `Pixel_In_Line`
(0–15) it belongs to, or `-1` if it's outside any pixel/line.

**Step 5 — compute real frequencies.** The arrays above are all in *sample*
units. To turn them into Hz, the script needs a **sample rate** — this is
the one piece of information that isn't in the CSVs (a DAQ logs voltages,
not its own clock rate), so it's passed in as `--sample-rate` (Hz). Given
that:
- **Pixel period** = average gap between consecutive pixel events within a
  line, in seconds → pixel frequency = `1 / period`.
- **Line period** = average gap between consecutive Line Clock triggers
  (the 16th pixel of one line to the 16th pixel of the next — dwell time +
  turnaround) → line frequency.
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
   step traces across the whole 8.349 ms frame.
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

`build_report.py` is a one-off generator for the polished HTML report
(published as a Claude Artifact). It reads the same underlying data and
constructs inline SVG figures (not matplotlib) so the report renders
crisply at any size and matches light/dark viewing themes. You don't need to
run this for day-to-day use — it's here for provenance/reproducibility of
the shared report, and depends on the font files under `fonts/`.

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
| `Line_Clock` | `1` on the exact sample a line's 16th pixel fires (coincides with that pixel's `Pixel_Clock=1`), else `0` (trigger — **not** held high across the line). |
| `Frame_Clock` | `1` for the entire span from line 1's first pixel to line 16's last pixel, else `0` (level). |
| `Line_Number` | Which line (`0`–`15`) this sample belongs to, or `-1` if between lines / outside the frame. |
| `Pixel_In_Line` | Which pixel within that line (`0`–`15`) this sample *is*, or `-1` if it isn't a pixel sample. |

### `clock_summary.csv` — one row per clock

| Column | Meaning |
|---|---|
| `Period_s` / `Period_ms` | Average time between rising edges. |
| `Frequency_Hz` | `1 / Period_s`. |
| `Events_Per_Frame` | 256 for Pixel, 16 for Line, 1 for Frame. |

At the assumed 1 MSa/s sample rate:

| Clock | Period | Frequency | Events/frame |
|---|---|---|---|
| Pixel | 30.00 µs | 33,333.3 Hz | 256 |
| Line | 493.87 µs | 2,024.8 Hz | 16 |
| Frame | 8.349 ms | 119.775 Hz | 1 |

**These numbers move directly with `--sample-rate`.** If your DAQ actually
runs at, say, 500 kSa/s instead of 1 MSa/s, every period doubles and every
frequency halves — the *sample-domain* structure (30-sample pixel spacing,
16×16 grid) stays exactly the same, only the Hz conversion changes. Rerun
`generate_clocks.py --sample-rate <your value>` to get correct numbers.

---

## 5. How the three clocks relate (nested, not independent)

```
Frame Clock   ▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▁▁
Line Clock    ▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▏▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▏▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▏ ...           ▁
Pixel Clock   ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏    ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏    ▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏
              └─────line 1─────┘ gap └─────line 2─────┘ gap  ...  (×16 lines)
              └──────────────────── 1 frame ────────────────────┘
```

- **Pixel Clock** fires once per pixel — 16 pulses per line, 256 per frame.
- **Line Clock** fires once per line, exactly on top of that line's *16th*
  Pixel Clock pulse (`▏` in the diagram above lands on the last pixel tick of
  each line's group of 16). It is not "nested inside" Line Clock in the
  sense of being held high while Pixel Clock ticks underneath it — the two
  are the same kind of trigger, Line Clock is just Pixel Clock's counter
  rolling over every 16.
- **Frame Clock** is the one level (gated) signal: it stays high for the
  entire scan and only the Pixel/Line triggers happen "inside" it. It drops
  low for the tail after the last pixel (22 samples in this file) and would
  rise again at the start of the next frame if the scan repeated.

So the hierarchy is: Frame Clock is a *gate* spanning the whole frame; Pixel
Clock and Line Clock are both *counters* inside that gate, ticking at two
different rates (every 1 pixel, and every 16 pixels) rather than one being a
sub-span of the other.

---

## 6. Design choices & things to double-check

- **`gap_split = 36` samples.** This threshold decides "same line" vs "next
  line." It's derived from the data (within-line gaps cluster at 30,
  line-to-line gaps at 42–44), not tuned by hand — but if you point this at
  a different scan pattern with different dwell/flyback timing, check the
  `[warn]` messages `generate_clocks.py` prints; it tells you if the
  detected line/pixel counts don't match what you expected.
- **Sample rate is an assumption, not measured.** Nothing in the CSVs states
  the DAQ's actual sample rate — 1 MSa/s was confirmed for this run, but
  it's a single `--sample-rate` argument if that's wrong.
- **Frame period = whole file length.** The script assumes the file
  represents exactly one frame (delay + 16 lines + tail) that then loops.
  If your logger captures multiple frames per file, this would need
  updating to detect frame boundaries instead of using the file length.
- **Pixel Clock and Line Clock are both 1-sample trigger pulses**, not
  50%-duty-cycle square waves or held-high gates. That matches "strobe"
  semantics (fire once when the count completes) rather than a free-running
  oscillator. Line Clock in particular used to be a level held high across
  the whole line — it was changed to a single trigger, coincident with the
  line's 16th Pixel Clock pulse, to match a hardware trigger input rather
  than a gate. If you need either as a toggling/held-high signal instead,
  that's the `line_clock[end] = 1` line in `build_clocks()`.

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
| `generate_clocks.py` | **Core pipeline** — detects pixels/lines, builds all 3 clocks, computes frequencies, writes CSVs + quick-look PNGs. |
| `visualize_clocks.py` | **Standalone plotting** — reads `clock_output.csv`, redraws the trajectory + timing figures anytime, in the report's color scheme. |
| `clock_output.csv` | Full sample-by-sample table: voltages + all three clocks. |
| `clock_summary.csv` | Period/frequency/event-count per clock. |
| `viz_scan_pattern.png`, `viz_timing_full.png`, `viz_timing_zoom.png` | Quick-look plots written directly by `generate_clocks.py`. |
| `scan_trajectory.png`, `timing_full_frame.png`, `timing_zoom.png` | Plots written by `visualize_clocks.py` (report color scheme). |
| `report.html`, `build_report.py`, `fonts/` | Source for the published write-up artifact; not needed to run the pipeline. |
| `16x16_lines.csv`, `16x16_meas.csv`, `scan_pattern.bmp`, `spatial_points.bmp` | Reference files from the original dataset, used to validate the reconstruction, not consumed by any script. |
