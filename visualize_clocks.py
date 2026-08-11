"""
visualize_clocks.py
====================
Standalone plotting script for the Pixel / Line / Frame clocks.

Unlike generate_clocks.py (which derives the clocks from the raw
Correct_16x16.csv / laser16x16.csv), this script only PLOTS — it reads the
already-built clock_output.csv and draws the same three figures shown in the
report, using the report's colour scheme so anything you plot later stays
visually consistent:

    Pixel Clock -> orange  #eb6834
    Line  Clock -> blue    #2a78d6
    Frame Clock -> green   #1baf7a

Figures produced:
    1. scan_trajectory.png   - X/Y galvo path with pixel-clock events marked
    2. timing_full_frame.png - Pixel/Line/Frame clocks stacked, whole frame
    3. timing_zoom.png       - same, zoomed to the first N lines (default 2)

Line/Frame Clock convention in the timing plots: a bold solid vertical line
marks a "start" trigger (numbered L1, L2, ... / F1), a dotted vertical line
marks the matching "complete" trigger -- both derived straight from the
Pixel_Clock/Line_Number columns already in clock_output.csv.

Usage:
    python visualize_clocks.py
    python visualize_clocks.py --csv clock_output.csv --zoom-lines 3 --show
"""

import argparse
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---- report colour palette (light theme) -----------------------------------
COLOR_PIXEL = "#eb6834"
COLOR_LINE = "#2a78d6"
COLOR_FRAME = "#1baf7a"
COLOR_INK = "#10151b"
COLOR_INK_DIM = "#4b5563"
COLOR_GRID = "#dde1e6"
COLOR_BG = "#ffffff"


def load(csv_path):
    df = pd.read_csv(csv_path)
    required = {
        "Sample_Index", "Time_s", "X_Voltage", "Y_Voltage",
        "Pixel_Clock", "Line_Clock", "Frame_Clock", "Line_Number",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{csv_path} is missing columns: {missing}")
    return df


def plot_scan_trajectory(df, out_path):
    pixel_events = df[df["Pixel_Clock"] == 1]

    fig, ax = plt.subplots(figsize=(7, 6.5), facecolor=COLOR_BG)
    ax.set_facecolor(COLOR_BG)
    ax.plot(df["X_Voltage"], df["Y_Voltage"], color=COLOR_INK_DIM,
            linewidth=1.1, alpha=0.6, zorder=1)
    ax.scatter(pixel_events["X_Voltage"], pixel_events["Y_Voltage"],
               color=COLOR_PIXEL, s=22, zorder=3, edgecolors=COLOR_BG, linewidths=0.6)

    ax.set_title("Scan Trajectory with Pixel-Clock Events", color=COLOR_INK,
                 fontsize=13, fontweight="bold")
    ax.set_xlabel("X Voltage", color=COLOR_INK_DIM)
    ax.set_ylabel("Y Voltage", color=COLOR_INK_DIM)
    ax.tick_params(colors=COLOR_INK_DIM)
    ax.grid(color=COLOR_GRID, linewidth=0.7)
    for spine in ax.spines.values():
        spine.set_color(COLOR_GRID)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=COLOR_BG)
    plt.close(fig)
    print(f"wrote {out_path}")


def _trigger_edges(df):
    """Derive each line's start/complete sample index and the frame's
    start/complete sample index directly from clock_output.csv's columns,
    so this stays correct even if the underlying data changes."""
    line_starts, line_ends = [], []
    for line_no, grp in df[df["Line_Number"] >= 0].groupby("Line_Number"):
        pix = grp[grp["Pixel_Clock"] == 1]
        if len(pix):
            line_starts.append(int(pix["Sample_Index"].min()))
            line_ends.append(int(pix["Sample_Index"].max()))
    line_starts.sort()
    line_ends.sort()

    frame_hits = df[df["Frame_Clock"] == 1]["Sample_Index"]
    frame_start = int(frame_hits.min()) if len(frame_hits) else None
    frame_end = int(frame_hits.max()) if len(frame_hits) else None
    return line_starts, line_ends, frame_start, frame_end


def _annotate_triggers(ax, starts, ends, dt_ms, s0, s1, prefix, color):
    """Bold solid line + number at each 'start' trigger, dotted line at each
    'complete/off' trigger, within the plotted sample window."""
    t_lo, t_hi = s0 * dt_ms, s1 * dt_ms
    for k, s in enumerate(starts):
        t = s * dt_ms
        if t_lo <= t <= t_hi:
            ax.axvline(t, color=color, linewidth=2.0, linestyle="-", alpha=0.9, zorder=4)
            ax.text(t, 1.28, f"{prefix}{k+1}", ha="center", va="bottom",
                    fontsize=7.5, color=color, clip_on=False)
    for e in ends:
        t = e * dt_ms
        if t_lo <= t <= t_hi:
            ax.axvline(t, color=color, linewidth=1.3, linestyle=(0, (2, 2)), alpha=0.8, zorder=4)


def plot_timing(df, out_path, sample_range=None, title_suffix=""):
    n = len(df)
    if sample_range is None:
        sample_range = (0, n)
    s0, s1 = sample_range
    sub = df.iloc[s0:s1]

    dt_ms = (df["Time_s"].iloc[1] - df["Time_s"].iloc[0]) * 1e3
    t_ms = sub["Time_s"].to_numpy() * 1e3
    signals = [
        ("Pixel Clock", sub["Pixel_Clock"].to_numpy(), COLOR_PIXEL),
        ("Line Clock", sub["Line_Clock"].to_numpy(), COLOR_LINE),
        ("Frame Clock", sub["Frame_Clock"].to_numpy(), COLOR_FRAME),
    ]

    fig, axes = plt.subplots(3, 1, figsize=(11, 6.6), sharex=True, facecolor=COLOR_BG)
    for ax, (label, sig, color) in zip(axes, signals):
        ax.set_facecolor(COLOR_BG)
        ax.step(t_ms, sig, where="post", color=color, linewidth=1.8)
        ax.set_ylim(-0.2, 1.2)
        ax.set_ylabel(label, color=COLOR_INK_DIM)
        ax.tick_params(colors=COLOR_INK_DIM)
        ax.grid(color=COLOR_GRID, linewidth=0.7, alpha=0.8)
        for spine in ax.spines.values():
            spine.set_color(COLOR_GRID)

    # Numbered bold(start)/dotted(complete) markers, same convention as
    # generate_clocks.py: L1, L2, ... per line, F1 for the frame.
    line_starts, line_ends, frame_start, frame_end = _trigger_edges(df)
    _annotate_triggers(axes[1], line_starts, line_ends, dt_ms, s0, s1, "L", COLOR_LINE)
    frame_starts = [frame_start] if frame_start is not None else []
    frame_ends = [frame_end] if frame_end is not None else []
    _annotate_triggers(axes[2], frame_starts, frame_ends, dt_ms, s0, s1, "F", COLOR_FRAME)

    axes[-1].set_xlabel("Time (ms)", color=COLOR_INK_DIM)
    fig.suptitle(f"Clock Timing{title_suffix}", color=COLOR_INK, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, facecolor=COLOR_BG)
    plt.close(fig)
    print(f"wrote {out_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default="clock_output.csv",
                     help="clock_output.csv produced by generate_clocks.py")
    ap.add_argument("--out-prefix", default="")
    ap.add_argument("--zoom-lines", type=int, default=2,
                     help="how many lines to include in the zoomed timing plot")
    ap.add_argument("--show", action="store_true",
                     help="also open the figures interactively")
    args = ap.parse_args()

    if not args.show:
        matplotlib.use("Agg")

    df = load(args.csv)

    plot_scan_trajectory(df, f"{args.out_prefix}scan_trajectory.png")
    plot_timing(df, f"{args.out_prefix}timing_full_frame.png", title_suffix=" - Full Frame")

    # zoom range: from sample 0 through the end of the Nth line
    lines_present = sorted(df.loc[df["Line_Number"] >= 0, "Line_Number"].unique())
    target_lines = lines_present[: args.zoom_lines]
    if target_lines:
        last_line_rows = df[df["Line_Number"] == target_lines[-1]]
        zoom_end = int(last_line_rows["Sample_Index"].max()) + 20
    else:
        zoom_end = len(df)
    plot_timing(df, f"{args.out_prefix}timing_zoom.png",
                sample_range=(0, zoom_end),
                title_suffix=f" - First {len(target_lines)} Lines (zoom)")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
