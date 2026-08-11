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
import statistics as stats

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


def build_clocks(pos, laser, pixels_per_line=16, gap_split=36):
    """Returns dict of per-sample arrays + line/pixel grouping info."""
    n = len(pos)
    laser_on = np.array([1 if L[0] >= 2.5 else 0 for L in laser])  # robust to 5 vs 5.0 etc.
    pixel_idx = np.where(laser_on == 1)[0]

    if len(pixel_idx) == 0:
        raise ValueError("No laser-on (5,5) events found in laser csv.")

    # Split pixel events into lines using the gap between consecutive events.
    # Small gap (~30 samples)  = still inside the same line.
    # Large gap (~44 samples)  = moved on to the next line.
    lines = []
    current = [pixel_idx[0]]
    for i in range(1, len(pixel_idx)):
        gap = pixel_idx[i] - pixel_idx[i - 1]
        if gap > gap_split:
            lines.append(current)
            current = []
        current.append(pixel_idx[i])
    lines.append(current)

    # Sanity check against the expected 16x16 grid (warn, don't hard-fail,
    # in case this script is reused on a different NxN scan).
    if len(lines) != pixels_per_line:
        print(f"[warn] detected {len(lines)} lines, expected {pixels_per_line}")
    for li, ln in enumerate(lines):
        if len(ln) != pixels_per_line:
            print(f"[warn] line {li} has {len(ln)} pixels, expected {pixels_per_line}")

    pixel_clock = np.zeros(n, dtype=int)
    line_clock = np.zeros(n, dtype=int)
    frame_clock = np.zeros(n, dtype=int)
    line_number = np.full(n, -1, dtype=int)
    pixel_in_line = np.full(n, -1, dtype=int)

    pixel_clock[pixel_idx] = 1

    for li, ln in enumerate(lines):
        start, end = ln[0], ln[-1]
        # Line Clock is two triggers, not a level: one pulse when the line
        # starts (1st pixel), one pulse when it completes (16th pixel). It
        # does NOT stay high in between. Line_Number metadata below still
        # spans the full line (start..end) since that's just "which line is
        # this sample part of", independent of the trigger signal itself.
        line_clock[start] = 1
        line_clock[end] = 1
        line_number[start:end + 1] = li
        for pi, sample in enumerate(ln):
            pixel_in_line[sample] = pi

    # Frame Clock mirrors Line Clock: two triggers, not a level -- one when
    # the frame starts (line 1's 1st pixel), one when it completes (line
    # 16's 16th pixel). Not held high across the frame.
    frame_start, frame_end = lines[0][0], lines[-1][-1]
    frame_clock[frame_start] = 1
    frame_clock[frame_end] = 1

    return {
        "n": n,
        "pixel_clock": pixel_clock,
        "line_clock": line_clock,
        "frame_clock": frame_clock,
        "line_number": line_number,
        "pixel_in_line": pixel_in_line,
        "lines": lines,           # list of list-of-sample-indices
        "frame_start": frame_start,
        "frame_end": frame_end,
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


def write_summary_csv(path, freqs, built):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Clock", "Period_s", "Period_ms", "Frequency_Hz", "Events_Per_Frame"])
        w.writerow([
            "Pixel Clock",
            f"{freqs['pixel_period_s']:.9f}", f"{freqs['pixel_period_s']*1e3:.6f}",
            f"{freqs['pixel_freq_hz']:.3f}",
            sum(len(ln) for ln in built["lines"]),
        ])
        w.writerow([
            "Line Clock",
            f"{freqs['line_period_s']:.9f}", f"{freqs['line_period_s']*1e3:.6f}",
            f"{freqs['line_freq_hz']:.3f}",
            len(built["lines"]) * 2,  # 2 trigger pulses per line: start + complete
        ])
        w.writerow([
            "Frame Clock",
            f"{freqs['frame_period_s']:.9f}", f"{freqs['frame_period_s']*1e3:.6f}",
            f"{freqs['frame_freq_hz']:.3f}",
            2,  # 2 trigger pulses per frame: start + complete
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
    line_starts = [ln[0] for ln in built["lines"]]
    line_ends = [ln[-1] for ln in built["lines"]]
    _annotate_triggers(axes[1], line_starts, line_ends, dt, s0, s1, "L", "tab:blue")
    _annotate_triggers(axes[2], [built["frame_start"]], [built["frame_end"]], dt, s0, s1, "F", "tab:green")

    axes[-1].set_xlabel("Time (ms)")
    fig.suptitle(f"Clock Timing{title_suffix}")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pos-csv", default="Correct_16x16.csv")
    ap.add_argument("--laser-csv", default="laser16x16.csv")
    ap.add_argument("--sample-rate", type=float, default=1e6,
                     help="DAQ sample rate in Hz (default 1e6 = 1 MSa/s)")
    ap.add_argument("--pixels-per-line", type=int, default=16)
    ap.add_argument("--out-prefix", default="")
    args = ap.parse_args()

    pos, laser = load_csv_pair(args.pos_csv, args.laser_csv)
    built = build_clocks(pos, laser, pixels_per_line=args.pixels_per_line)
    freqs = compute_frequencies(built, args.sample_rate, built["n"])

    out_csv = f"{args.out_prefix}clock_output.csv"
    summary_csv = f"{args.out_prefix}clock_summary.csv"
    write_output_csv(out_csv, pos, laser, built, args.sample_rate)
    write_summary_csv(summary_csv, freqs, built)

    plot_scan_pattern(pos, built, f"{args.out_prefix}viz_scan_pattern.png")
    plot_timing(built, args.sample_rate, f"{args.out_prefix}viz_timing_full.png",
                title_suffix=" - Full Frame")

    # Zoom into the first 2 lines for a readable pixel/line relationship
    zoom_end = built["lines"][1][-1] + 20
    plot_timing(built, args.sample_rate, f"{args.out_prefix}viz_timing_zoom.png",
                sample_range=(0, zoom_end), title_suffix=" - First 2 Lines (zoom)")

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
