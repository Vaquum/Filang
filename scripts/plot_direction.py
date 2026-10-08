#!/usr/bin/env python3
"""Render exact report figures from a completed direction-analysis artifact.

Plotting is optional and outside the native measurement and inference paths.
No model fitting, selection or statistical calculation is performed here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.analysis.read_text())
    if not data["complete_design"]:
        raise ValueError("report figures require the full declared design")
    args.out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.hashsalt": "filang-direction-v1", "figure.facecolor": "white",
                         "savefig.facecolor": "white"})
    generated = []

    def save(fig, stem):
        for suffix in ("png", "svg"):
            path = args.out / (stem + "." + suffix)
            metadata = {"Date": None} if suffix == "svg" else {"Software": "Filang plot_direction.py"}
            fig.savefig(path, dpi=160, bbox_inches="tight", metadata=metadata)
            generated.append(path)
        plt.close(fig)

    selected = sorted((s for s in data["selected"] if s["target"] == "cc"),
                      key=lambda s: s["timeframe_minutes"])
    estimate, lower, upper = [], [], []
    for row in selected:
        point = row["inference"][row["primary_baseline"]]["7"]["log_loss_improvement"]
        estimate.append(1000 * point["estimate"])
        lower.append(1000 * point["percentile_95_ci"][0])
        upper.append(1000 * point["percentile_95_ci"][1])
    estimate, lower, upper = map(np.asarray, (estimate, lower, upper))
    fig, ax = plt.subplots(figsize=(9.0, 4.7))
    ypos = np.arange(len(selected))
    ax.errorbar(estimate, ypos, xerr=[estimate - lower, upper - estimate], fmt="o",
                color="#1f5675", ecolor="#81949e", markersize=7, capsize=4, linewidth=1.8)
    ax.axvline(0, color="#333333", linestyle="--", linewidth=1.1)
    ax.set_yticks(ypos, [f"{s['timeframe_minutes']} min" for s in selected])
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.17)
    ax.set_xlabel("Log-loss improvement over learned lag-one direction\n"
                  "nats per prediction × 1,000; positive favors geometry")
    ax.set_title("Does full candle geometry add predictive information?", loc="left", pad=29,
                 fontsize=15, fontweight="semibold")
    ax.text(0, 1.035, "Frozen test · validation-selected models · seven-day paired bootstrap, 95% intervals",
            transform=ax.transAxes, fontsize=9.5, color="#52626c")
    fig.tight_layout()
    save(fig, "primary-log-loss")

    frames = sorted(data["timeframes_minutes"])
    fig, axes = plt.subplots(1, 2, figsize=(13.8, 5.1), sharey=True)
    for ax, mode in zip(axes, ("unoriented", "oriented")):
        values = np.zeros((len(frames), 9))
        for i, minute in enumerate(frames):
            for j, bars in enumerate(range(2, 11)):
                rows = [c for c in data["candidates"] if c["timeframe_minutes"] == minute
                        and c["bars"] == bars and c["mode"] == mode and c["target"] == "cc"]
                coverage = [100 * (1 - c["test_support"]["binary_unseen_fraction"]) for c in rows]
                if not coverage or max(coverage) - min(coverage) > 1e-10:
                    raise ValueError("support must agree across smoothing choices")
                values[i, j] = coverage[0]
        heat = ax.imshow(values, cmap="Blues", vmin=0, vmax=100, aspect="auto")
        for i in range(len(frames)):
            for j in range(9):
                value = values[i, j]
                label = "0" if value == 0 else "<.01" if value < .01 else f"{value:.2f}" if value < 1 else f"{value:.1f}"
                ax.text(j, i, label, ha="center", va="center", fontsize=9,
                        color="white" if value > 60 else "#173346")
        ax.set_xticks(range(9), range(2, 11))
        ax.set_yticks(range(len(frames)), [f"{m} min" for m in frames])
        ax.set_xlabel("Candles in complete pattern")
        ax.set_title(mode.capitalize(), fontsize=12)
        ax.set_xticks(np.arange(-.5, 9, 1), minor=True)
        ax.set_yticks(np.arange(-.5, len(frames), 1), minor=True)
        ax.grid(which="minor", color="white", linewidth=1)
        ax.tick_params(which="minor", bottom=False, left=False)
    fig.suptitle("Long complete patterns rarely recur in the fitting data", x=.04, ha="left",
                 fontsize=16, fontweight="semibold", y=.98)
    fig.text(.04, .905, "Percentage of nonflat test decisions whose exact pattern appeared in training plus validation",
             fontsize=10.5, color="#52626c")
    fig.subplots_adjust(left=.06, right=.89, bottom=.20, top=.82, wspace=.12)
    color_axis = fig.add_axes([.91, .20, .013, .62])
    fig.colorbar(heat, cax=color_axis, label="Test coverage (%)")
    fig.text(.04, .045, "Common valid ten-bar test timeline; fitting support includes flat outcomes. "
             "An unseen pattern uses the fitted unconditional probability.", fontsize=9.5, color="#52626c")
    save(fig, "pattern-support")

    manifest = {"version": 1, "analysis_sha256": digest(args.analysis),
                "plot_script_sha256": digest(__file__), "matplotlib_version": matplotlib.__version__,
                "numpy_version": np.__version__, "python_version": sys.version,
                "files": {p.name: {"bytes": p.stat().st_size, "sha256": digest(p)} for p in generated}}
    (args.out / "figures.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"status": "PASS", "figures": [p.name for p in generated]}))


if __name__ == "__main__":
    main()
