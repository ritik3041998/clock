"""
generate_clocks.py
===================
Reconstructs Pixel Clock, Line Clock and Frame Clock digital signals for a
16x16 point galvo/laser raster scan, from:

    Correct_16x16.csv   -> X,Y scanner drive VOLTAGES, one row per DAQ sample
    laser16x16.csv      -> Laser strobe flag, same row-for-row alignment
                            (0,0 = laser off,  5,5 = laser fires / pixel point)

Scan structure discovered in the data (16x16 = 256 pixels total):
    - 16 lines, 16 pixel dwell points per line (256 "5,5" events total)
    - Laser fires ~30 samples apart while scanning a line (pixel dwell time)
    - ~44 sample gap between the last pixel of one line and the first pixel
      of the next line (line flyback / turn-around, matches the rounded caps
      seen in scan_pattern.bmp)
    - The whole file (start delay + 16 lines + end tail) = one full frame

Clock definitions produced here:
    Pixel Clock  -> 1-sample-wide TRIGGER pulse at every laser==5 event,
                    i.e. every time a pixel is counted                (256 pulses)
    Line Clock   -> TWO 1-sample-wide TRIGGER pulses per line, not a level:
                      - "line start" pulse on the line's 1st pixel
                      - "line complete" pulse on the line's 16th (last)
                        pixel (coincides with that pixel's Pixel Clock pulse)
                    LOW at every other sample, including for the whole
                    duration in between -- it does not stay high across
                    the line                                    (32 pulses)
    Frame Clock  -> TWO 1-sample-wide TRIGGER pulses per frame, same style as
                    Line Clock:
                      - "frame start" pulse on line 1's 1st pixel
                      - "frame complete" pulse on line 16's 16th (last) pixel
                    LOW at every other sample -- not held high across the
                    frame                                           (2 pulses)

All three clocks are the same kind of signal (1-sample triggers, never held
high) -- they differ only in how often they fire: Pixel every 1 pixel, Line
every 16 pixels (start + complete), Frame every 256 pixels (start + complete).

Optional per-clock start delay:
    Real hardware rarely fires all three clocks at the exact same instant --
    each one usually has its own small propagation/processing latency. Use
    --pixel-delay-us / --line-delay-us / --frame-delay-us (microseconds,
    default 0) to shift each clock's triggers later in time independently.
    This only changes WHEN each clock asserts; the underlying scan data
    (X/Y voltage, Laser_Raw) and each clock's own period/frequency are
    unaffected -- a constant delay applied to every pulse of one clock
    cancels out of that clock's own period measurement.

Outputs:
    clock_output.csv    -> full sample-by-sample table (voltages + all clocks)
    clock_summary.csv   -> measured periods/frequencies for each clock
    viz_scan_pattern.png-> X/Y trajectory with pixel events marked (like scan_pattern.bmp)
    viz_timing_full.png -> Pixel/Line/Frame clock vs time, full frame
    viz_timing_zoom.png -> zoomed timing view of the first 2 lines

Usage:
    python generate_clocks.py --sample-rate 1e6
"""

import argparse
import csv
import glob
import os
import statistics as stats
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def load_csv_pair(pos_path, laser_path):
    with open(pos_path, newline="") as f:
        pos = [(float(r[0]), float(r[1])) for r in csv.reader(f) if r]
    with open(laser_path, newline="") as f:
        laser = [(float(r[0]), float(r[1])) for r in csv.reader(f) if r]
    if len(pos) != len(laser):
        raise ValueError(
            f"Row count mismatch: {pos_path} has {len(pos)} rows, "
            f"{laser_path} has {len(laser)} rows"
        )
    return pos, laser


def resolve_scan_files(scan_dir=None, pos_csv=None, laser_csv=None):
    """Auto-discover the position (continuous X/Y drive voltage) and laser
    strobe (mostly-repeated on/off flag) CSVs inside scan_dir, unless
    pos_csv/laser_csv are already given explicitly -- content-based, so it
    works regardless of filename convention (16x16_lines.csv,
    meas_pts_32x.csv, Square_lines.csv, ... all just work).

    Any explicitly given pos_csv/laser_csv always win outright; scan_dir
    only fills in whichever of the two wasn't given.
    """
    if pos_csv and laser_csv:
        return pos_csv, laser_csv
    if not scan_dir:
        raise ValueError(
            "Need either both --pos-csv and --laser-csv, or --scan-dir to "
            "auto-discover them from a folder."
        )

    csv_paths = sorted(glob.glob(os.path.join(scan_dir, "*.csv")))
    if not csv_paths:
        raise ValueError(f"No CSV files found in {scan_dir!r}")

    info = []
    for path in csv_paths:
        with open(path, newline="") as f:
            rows = [(r[0], r[1]) for r in csv.reader(f) if r]
        n = len(rows)
        uniq = len(set(rows))
        info.append({"path": path, "n": n, "uniq": uniq,
                      "uniq_ratio": (uniq / n) if n else 0})

    # A laser-strobe file is dominated by a couple of repeated flag-value
    # rows (mostly "off", occasionally "on") -- very low unique-row ratio.
    # A position file varies almost every row.
    laser_like = [c for c in info if c["uniq_ratio"] < 0.05 and c["uniq"] <= 20]

    if laser_csv is None:
        names = [os.path.basename(c["path"]) for c in info]
        if len(laser_like) == 0:
            raise ValueError(
                f"Couldn't find a laser-strobe file in {scan_dir!r} (looking for "
                f"a CSV whose rows are mostly-repeated on/off flag pairs, e.g. "
                f"'0,0' / '5,5'). Files present: {names}. This pattern may not "
                f"include a raw strobe trace -- pass --laser-csv explicitly if "
                f"you have one, or --pos-csv/--laser-csv for a different pair."
            )
        if len(laser_like) > 1:
            cand = [os.path.basename(c["path"]) for c in laser_like]
            raise ValueError(
                f"Found multiple candidate laser-strobe files in {scan_dir!r}: "
                f"{cand}. Pass --laser-csv explicitly to disambiguate."
            )
        laser_csv = laser_like[0]["path"]
        laser_n = laser_like[0]["n"]
    else:
        with open(laser_csv, newline="") as f:
            laser_n = sum(1 for r in csv.reader(f) if r)

    if pos_csv is None:
        pos_like = [c for c in info if c["path"] != laser_csv and c["n"] == laser_n]
        if not pos_like:
            raise ValueError(
                f"Couldn't find a position file in {scan_dir!r} with the same "
                f"row count ({laser_n}) as the laser file "
                f"{os.path.basename(laser_csv)!r}. Pass --pos-csv explicitly."
            )
        # Prefer whichever candidate varies the most row-to-row -- that's the
        # continuous X/Y drive trace, not an integer pixel-index table.
        pos_like.sort(key=lambda c: -c["uniq_ratio"])
        pos_csv = pos_like[0]["path"]

    return pos_csv, laser_csv


def auto_gap_split(pixel_idx):
    """Derive the within-line/between-line gap threshold straight from the
    data instead of hand-tuning it per dataset: the single most common gap
    between consecutive laser-on samples is the normal pixel-to-pixel dwell
    pitch: real datasets. 20% margin over that pitch reliably lands below
    the (usually 30-50%+ larger) line-to-line flyback gap without needing to
    know either value up front."""
    diffs = np.diff(pixel_idx)
    if len(diffs) == 0:
        return 36
    vals, counts = np.unique(diffs, return_counts=True)
    pixel_pitch = int(vals[np.argmax(counts)])
    return max(pixel_pitch + 1, int(round(pixel_pitch * 1.2)))


def build_clocks(pos, laser, pixels_per_line=None, gap_split=None,
                  pixel_delay_samples=0, line_delay_samples=0, frame_delay_samples=0):
    """Returns dict of per-sample arrays + line/pixel grouping info.

    pixels_per_line=None / gap_split=None auto-detect from the data itself
    (see auto_gap_split() and the pixels-per-line inference below) -- pass
    explicit values only if you want to override the detection or need a
    strict sanity check against a specific expected grid.

    pixel_delay_samples / line_delay_samples / frame_delay_samples: shift
    that clock's trigger pulses this many samples LATER than the physical
    event they mark, modeling per-signal hardware latency. 0 = fires at the
    exact sample the event happens (original behaviour). Line_Number /
    Pixel_In_Line metadata and every frequency/period measurement are based
    on the physical (undelayed) event times, since a constant delay doesn't
    change a clock's own rate -- only the digital Pixel_Clock / Line_Clock /
    Frame_Clock columns are shifted.
    """
    n = len(pos)
    # Auto threshold: midpoint between the flag's two extreme values, robust
    # to whatever "on" voltage the hardware uses (5V, 3.3V, ...) instead of
    # assuming 5.
    laser_vals = [L[0] for L in laser]
    on_threshold = (min(laser_vals) + max(laser_vals)) / 2.0
    laser_on = np.array([1 if v >= on_threshold else 0 for v in laser_vals])
    pixel_idx = np.where(laser_on == 1)[0]

    if len(pixel_idx) == 0:
        raise ValueError("No laser-on events found in laser csv.")

    if gap_split is None:
        gap_split = auto_gap_split(pixel_idx)

    # Split pixel events into lines using the gap between consecutive events.
    # Small gap = still inside the same line. Large gap = moved to the next.
    lines = []
    current = [pixel_idx[0]]
    for i in range(1, len(pixel_idx)):
        gap = pixel_idx[i] - pixel_idx[i - 1]
        if gap > gap_split:
            lines.append(current)
            current = []
        current.append(pixel_idx[i])
    lines.append(current)

    if pixels_per_line is None:
        # Infer the expected pixels/line from the data itself: the most
        # common detected line length. Keeps the sanity-check warning below
        # meaningful (flags genuine outlier lines) without requiring the
        # caller to already know the grid shape.
        pixels_per_line = Counter(len(ln) for ln in lines).most_common(1)[0][0]

    print(f"[info] detected {len(lines)} lines of {pixels_per_line} pixels each "
          f"(gap-split={gap_split})")
    # Sanity check against the (given or inferred) expected grid shape --
    # warn, don't hard-fail, since a few odd lines shouldn't abort the run.
    for li, ln in enumerate(lines):
        if len(ln) != pixels_per_line:
            print(f"[warn] line {li} has {len(ln)} pixels, expected {pixels_per_line}")

    pixel_clock = np.zeros(n, dtype=int)
    line_clock = np.zeros(n, dtype=int)
    frame_clock = np.zeros(n, dtype=int)
    line_number = np.full(n, -1, dtype=int)
    pixel_in_line = np.full(n, -1, dtype=int)

    def fire(arr, event_sample, delay, clock_name):
        """Assert arr[event_sample + delay] = 1, warning instead of crashing
        if the delay pushes the trigger outside the recorded window or onto
        a sample that already fired (delay big enough to overlap the next
        event of the same clock)."""
        target = event_sample + delay
        if not (0 <= target < n):
            print(f"[warn] {clock_name} trigger at sample {event_sample} "
                  f"+ delay {delay} = {target} falls outside the recorded "
                  f"window (0..{n-1}); dropped")
            return
        if arr[target] == 1:
            print(f"[warn] {clock_name} delay of {delay} samples made two "
                  f"triggers land on the same sample ({target}); one was "
                  f"overwritten -- reduce the delay")
        arr[target] = 1

    for i in pixel_idx:
        fire(pixel_clock, i, pixel_delay_samples, "Pixel Clock")

    for li, ln in enumerate(lines):
        start, end = ln[0], ln[-1]
        # Line Clock is two triggers, not a level: one pulse when the line
        # starts (1st pixel), one pulse when it completes (16th pixel). It
        # does NOT stay high in between. Line_Number metadata below still
        # spans the full line (start..end), based on the physical/undelayed
        # event times, since that's just "which line is this sample part
        # of" -- independent of the (possibly delayed) trigger signal.
        fire(line_clock, start, line_delay_samples, "Line Clock (start)")
        fire(line_clock, end, line_delay_samples, "Line Clock (complete)")
        line_number[start:end + 1] = li
        for pi, sample in enumerate(ln):
            pixel_in_line[sample] = pi

    # Frame Clock mirrors Line Clock: two triggers, not a level -- one when
    # the frame starts (line 1's 1st pixel), one when it completes (line
    # 16's 16th pixel). Not held high across the frame.
    frame_start, frame_end = lines[0][0], lines[-1][-1]
    fire(frame_clock, frame_start, frame_delay_samples, "Frame Clock (start)")
    fire(frame_clock, frame_end, frame_delay_samples, "Frame Clock (complete)")

    return {
        "n": n,
        "pixel_clock": pixel_clock,
        "line_clock": line_clock,
        "frame_clock": frame_clock,
        "line_number": line_number,
        "pixel_in_line": pixel_in_line,
        "lines": lines,           # list of list-of-sample-indices (physical/undelayed)
        "frame_start": frame_start,     # physical/undelayed
        "frame_end": frame_end,         # physical/undelayed
        "pixel_delay_samples": pixel_delay_samples,
        "line_delay_samples": line_delay_samples,
        "frame_delay_samples": frame_delay_samples,
        "gap_split": gap_split,                 # threshold actually used (given or auto-detected)
        "pixels_per_line": pixels_per_line,      # expected/inferred pixels-per-line actually used
    }


def compute_frequencies(built, sample_rate_hz, total_samples):
    lines = built["lines"]
    dt = 1.0 / sample_rate_hz

    # Pixel period: gap between consecutive pixel events *within* a line.
    pixel_gaps = []
    for ln in lines:
        pixel_gaps.extend(np.diff(ln).tolist())
    pixel_period_s = stats.mean(pixel_gaps) * dt
    pixel_freq_hz = 1.0 / pixel_period_s

    # Line period: time between consecutive Line Clock triggers, i.e. between
    # the 16th pixel of one line and the 16th pixel of the next (dwell time +
    # flyback -- same spacing as start-to-start since each line has a fixed
    # 16-pixel count).
    line_triggers = [ln[-1] for ln in lines]
    line_gaps = np.diff(line_triggers).tolist()
    line_period_s = stats.mean(line_gaps) * dt
    line_freq_hz = 1.0 / line_period_s

    # Frame period: the file is taken to represent exactly one full frame
    # (start delay + all lines + end tail) before the pattern repeats.
    frame_period_s = total_samples * dt
    frame_freq_hz = 1.0 / frame_period_s

    return {
        "pixel_period_s": pixel_period_s,
        "pixel_freq_hz": pixel_freq_hz,
        "line_period_s": line_period_s,
        "line_freq_hz": line_freq_hz,
        "frame_period_s": frame_period_s,
        "frame_freq_hz": frame_freq_hz,
    }


def write_output_csv(path, pos, laser, built, sample_rate_hz):
    n = built["n"]
    dt = 1.0 / sample_rate_hz
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "Sample_Index", "Time_s",
            "X_Voltage", "Y_Voltage",
            "Laser_Raw",
            "Pixel_Clock", "Line_Clock", "Frame_Clock",
            "Line_Number", "Pixel_In_Line",
        ])
        for i in range(n):
            w.writerow([
                i, f"{i * dt:.9f}",
                pos[i][0], pos[i][1],
                laser[i][0],
                built["pixel_clock"][i], built["line_clock"][i], built["frame_clock"][i],
                built["line_number"][i], built["pixel_in_line"][i],
            ])


def write_summary_csv(path, freqs, built, sample_rate_hz):
    dt_us = 1e6 / sample_rate_hz
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Clock", "Period_s", "Period_ms", "Frequency_Hz", "Events_Per_Frame", "Start_Delay_us"])
        w.writerow([
            "Pixel Clock",
            f"{freqs['pixel_period_s']:.9f}", f"{freqs['pixel_period_s']*1e3:.6f}",
            f"{freqs['pixel_freq_hz']:.3f}",
            sum(len(ln) for ln in built["lines"]),
            f"{built['pixel_delay_samples'] * dt_us:.3f}",
        ])
        w.writerow([
            "Line Clock",
            f"{freqs['line_period_s']:.9f}", f"{freqs['line_period_s']*1e3:.6f}",
            f"{freqs['line_freq_hz']:.3f}",
            len(built["lines"]) * 2,  # 2 trigger pulses per line: start + complete
            f"{built['line_delay_samples'] * dt_us:.3f}",
        ])
        w.writerow([
            "Frame Clock",
            f"{freqs['frame_period_s']:.9f}", f"{freqs['frame_period_s']*1e3:.6f}",
            f"{freqs['frame_freq_hz']:.3f}",
            2,  # 2 trigger pulses per frame: start + complete
            f"{built['frame_delay_samples'] * dt_us:.3f}",
        ])


def plot_scan_pattern(pos, built, out_path):
    x = [p[0] for p in pos]
    y = [p[1] for p in pos]
    px = [pos[i][0] for i in np.where(built["pixel_clock"] == 1)[0]]
    py = [pos[i][1] for i in np.where(built["pixel_clock"] == 1)[0]]

    fig, ax = plt.subplots(figsize=(6, 6), facecolor="black")
    ax.set_facecolor("black")
    ax.plot(x, y, color="white", linewidth=1)
    ax.scatter(px, py, color="red", s=10, zorder=3)
    ax.set_title("Scan Trajectory with Pixel-Clock Events", color="white")
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_color("white")
    ax.set_xlabel("X Voltage", color="white")
    ax.set_ylabel("Y Voltage", color="white")
    fig.tight_layout()
    fig.savefig(out_path, facecolor="black", dpi=150)
    plt.close(fig)


def _trigger_edges_from_array(arr):
    """Pair up a trigger array's asserted samples in chronological order:
    1st = start, 2nd = complete, 3rd = start, 4th = complete, ... Reads the
    ACTUAL (possibly delayed) positions straight from the array, so markers
    stay correct regardless of any configured pixel/line/frame delay."""
    hits = list(np.where(arr == 1)[0])
    return hits[0::2], hits[1::2]


def _annotate_triggers(ax, starts, ends, dt, s0, s1, prefix, color):
    """Draw a bold solid line + number at each 'start' trigger and a dotted
    line at each 'complete/off' trigger, within the plotted sample window."""
    t_lo, t_hi = s0 * dt * 1e3, s1 * dt * 1e3
    for k, s in enumerate(starts):
        t = s * dt * 1e3
        if t_lo <= t <= t_hi:
            ax.axvline(t, color=color, linewidth=2.0, linestyle="-", alpha=0.9, zorder=4)
            ax.text(t, 1.28, f"{prefix}{k+1}", ha="center", va="bottom",
                    fontsize=7.5, color=color, clip_on=False)
    for e in ends:
        t = e * dt * 1e3
        if t_lo <= t <= t_hi:
            ax.axvline(t, color=color, linewidth=1.3, linestyle=(0, (2, 2)), alpha=0.8, zorder=4)


def plot_timing(built, sample_rate_hz, out_path, sample_range=None, title_suffix=""):
    n = built["n"]
    dt = 1.0 / sample_rate_hz
    if sample_range is None:
        sample_range = (0, n)
    s0, s1 = sample_range
    t = np.arange(s0, s1) * dt * 1e3  # ms

    fig, axes = plt.subplots(3, 1, figsize=(11, 6.6), sharex=True)
    signals = [
        ("Pixel Clock", built["pixel_clock"][s0:s1], "tab:orange"),
        ("Line Clock", built["line_clock"][s0:s1], "tab:blue"),
        ("Frame Clock", built["frame_clock"][s0:s1], "tab:green"),
    ]
    for ax, (label, sig, color) in zip(axes, signals):
        ax.step(t, sig, where="post", color=color, linewidth=1.5)
        ax.set_ylim(-0.2, 1.2)
        ax.set_ylabel(label)
        ax.grid(alpha=0.3)

    # Numbered bold(start)/dotted(complete) markers: L1, L2, ... on the Line
    # Clock lane, F1 on the Frame Clock lane. Pixel Clock is left plain since
    # every pulse there is already unambiguous (one event = one pixel).
    # Read straight from the (possibly delayed) arrays so markers always
    # match what the signal actually does.
    line_starts, line_ends = _trigger_edges_from_array(built["line_clock"])
    frame_starts, frame_ends = _trigger_edges_from_array(built["frame_clock"])
    _annotate_triggers(axes[1], line_starts, line_ends, dt, s0, s1, "L", "tab:blue")
    _annotate_triggers(axes[2], frame_starts, frame_ends, dt, s0, s1, "F", "tab:green")

    axes[-1].set_xlabel("Time (ms)")
    fig.suptitle(f"Clock Timing{title_suffix}")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scan-dir", default=None,
                     help="Folder to auto-discover the position/laser CSVs from "
                          "(content-based -- works with any filename convention, "
                          "e.g. --scan-dir SCAN-PATTERNS/32x32_Pattern). Ignored "
                          "for whichever of --pos-csv/--laser-csv you give explicitly.")
    ap.add_argument("--pos-csv", default=None,
                     help="X/Y scanner drive voltage CSV (default: Correct_16x16.csv "
                          "if neither this, --laser-csv nor --scan-dir is given)")
    ap.add_argument("--laser-csv", default=None,
                     help="Laser strobe flag CSV (default: laser16x16.csv "
                          "if neither this, --pos-csv nor --scan-dir is given)")
    ap.add_argument("--sample-rate", type=float, default=1e6,
                     help="DAQ sample rate in Hz (default 1e6 = 1 MSa/s)")
    ap.add_argument("--pixels-per-line", type=int, default=None,
                     help="Expected pixels/line for the sanity-check warning. "
                          "Default: auto-inferred from the data (the most common "
                          "detected line length) -- line detection itself is "
                          "gap-based and works for any N-line, M-pixel grid.")
    ap.add_argument("--gap-split", type=int, default=None,
                     help="Sample-gap threshold that separates 'still inside "
                          "the same line' pixel spacing from 'moved to the next "
                          "line' flyback gaps. Default: auto-detected from the "
                          "data (1.2x the most common consecutive-pixel gap) -- "
                          "pass this explicitly only if auto-detection misdetects "
                          "your line count.")
    ap.add_argument("--out-prefix", default="")
    ap.add_argument("--pixel-delay-us", type=float, default=0.0,
                     help="Delay Pixel Clock's triggers this many microseconds "
                          "after each physical pixel event (default 0)")
    ap.add_argument("--line-delay-us", type=float, default=0.0,
                     help="Delay Line Clock's triggers this many microseconds "
                          "after each physical line start/complete (default 0)")
    ap.add_argument("--frame-delay-us", type=float, default=0.0,
                     help="Delay Frame Clock's triggers this many microseconds "
                          "after each physical frame start/complete (default 0)")
    args = ap.parse_args()

    dt_us = 1e6 / args.sample_rate
    pixel_delay_samples = round(args.pixel_delay_us / dt_us)
    line_delay_samples = round(args.line_delay_us / dt_us)
    frame_delay_samples = round(args.frame_delay_us / dt_us)

    if args.pos_csv or args.laser_csv or args.scan_dir:
        pos_csv, laser_csv = resolve_scan_files(args.scan_dir, args.pos_csv, args.laser_csv)
    else:
        pos_csv, laser_csv = "Correct_16x16.csv", "laser16x16.csv"
    print(f"[info] pos-csv={pos_csv}  laser-csv={laser_csv}")

    pos, laser = load_csv_pair(pos_csv, laser_csv)
    built = build_clocks(pos, laser, pixels_per_line=args.pixels_per_line,
                          gap_split=args.gap_split,
                          pixel_delay_samples=pixel_delay_samples,
                          line_delay_samples=line_delay_samples,
                          frame_delay_samples=frame_delay_samples)
    freqs = compute_frequencies(built, args.sample_rate, built["n"])

    out_csv = f"{args.out_prefix}clock_output.csv"
    summary_csv = f"{args.out_prefix}clock_summary.csv"
    write_output_csv(out_csv, pos, laser, built, args.sample_rate)
    write_summary_csv(summary_csv, freqs, built, args.sample_rate)

    plot_scan_pattern(pos, built, f"{args.out_prefix}viz_scan_pattern.png")
    plot_timing(built, args.sample_rate, f"{args.out_prefix}viz_timing_full.png",
                title_suffix=" - Full Frame")

    # Zoom into the first 2 lines for a readable pixel/line relationship --
    # widen the window if a delay might push a trigger past the physical
    # line-2 boundary, so the zoom plot doesn't cut it off.
    max_delay = max(pixel_delay_samples, line_delay_samples, frame_delay_samples, 0)
    zoom_end = built["lines"][1][-1] + 20 + max_delay
    plot_timing(built, args.sample_rate, f"{args.out_prefix}viz_timing_zoom.png",
                sample_range=(0, zoom_end), title_suffix=" - First 2 Lines (zoom)")

    if pixel_delay_samples or line_delay_samples or frame_delay_samples:
        print("=== Configured start delays ===")
        print(f"Pixel Clock : +{args.pixel_delay_us:.3f} us ({pixel_delay_samples} samples)")
        print(f"Line Clock  : +{args.line_delay_us:.3f} us ({line_delay_samples} samples)")
        print(f"Frame Clock : +{args.frame_delay_us:.3f} us ({frame_delay_samples} samples)")
        print()

    print("=== Clock frequency summary (sample rate = "
          f"{args.sample_rate:,.0f} Hz) ===")
    print(f"Pixel Clock : {freqs['pixel_freq_hz']:,.1f} Hz "
          f"(period {freqs['pixel_period_s']*1e6:.2f} us), "
          f"{sum(len(ln) for ln in built['lines'])} pixels/frame")
    print(f"Line Clock  : {freqs['line_freq_hz']:,.1f} Hz "
          f"(period {freqs['line_period_s']*1e6:.2f} us), "
          f"{len(built['lines'])} lines/frame "
          f"({len(built['lines']) * 2} trigger pulses: start + complete per line)")
    print(f"Frame Clock : {freqs['frame_freq_hz']:,.3f} Hz "
          f"(period {freqs['frame_period_s']*1e3:.3f} ms)")
    print()
    print(f"Wrote: {out_csv}, {summary_csv}")
    print(f"Wrote: {args.out_prefix}viz_scan_pattern.png, "
          f"{args.out_prefix}viz_timing_full.png, {args.out_prefix}viz_timing_zoom.png")


if __name__ == "__main__":
    main()
