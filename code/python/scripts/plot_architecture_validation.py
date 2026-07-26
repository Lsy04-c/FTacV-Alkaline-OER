#!/usr/bin/env python3
"""Render presentation-clean evidence figures from validated comparison tables."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "results" / "architecture_validation"
LEGACY = "#2563A6"
COMPLEX = "#D97706"
M0_COLOR = "#397D8C"
M1_COLOR = "#B44B4B"
NEUTRAL = "#5B6573"

mpl.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 11,
        "axes.spines.right": False,
        "axes.spines.top": False,
        "axes.linewidth": 1.1,
        "legend.frameon": False,
        "svg.fonttype": "none",
    }
)


def _rows(name: str) -> list[dict[str, str]]:
    with (RESULTS / name).open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _save(fig: plt.Figure, stem: str) -> None:
    fig.savefig(RESULTS / f"{stem}.png", dpi=240, bbox_inches="tight")
    fig.savefig(RESULTS / f"{stem}.svg", bbox_inches="tight")
    plt.close(fig)


def plot_feature_comparison() -> None:
    rows = _rows("feature_objective_comparison.csv")
    modes = ("legacy", "complex_snr")
    colors = (LEGACY, COMPLEX)
    labels = ("Legacy", "Complex-SNR")
    datasets = sorted(
        {row["dataset"] for row in rows if row["target_type"] == "experimental"}
    )

    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.2))

    for index, (mode, color, label) in enumerate(zip(modes, colors, labels)):
        values = [
            float(row["recovery_error"])
            for row in rows
            if row["dataset"] == "synthetic" and row["feature_mode"] == mode
        ]
        jitter = np.linspace(-0.07, 0.07, len(values))
        axes[0].scatter(
            np.full(len(values), index) + jitter,
            values,
            color=color,
            s=42,
            zorder=3,
        )
        axes[0].hlines(
            np.mean(values),
            index - 0.22,
            index + 0.22,
            color=color,
            linewidth=2.2,
        )
    axes[0].set_xticks(range(2), labels)
    axes[0].set_ylabel("Normalized recovery error")
    axes[0].set_title("a  Synthetic recovery", loc="left", fontweight="bold")

    x = np.arange(len(datasets))
    width = 0.36
    for offset, mode, color, label in zip(
        (-width / 2, width / 2),
        modes,
        colors,
        labels,
    ):
        means = [
            np.mean(
                [
                    float(row["common_h1_h3_rmse"])
                    for row in rows
                    if row["dataset"] == dataset
                    and row["feature_mode"] == mode
                ]
            )
            for dataset in datasets
        ]
        axes[1].bar(x + offset, means, width, color=color, label=label)
    axes[1].set_xticks(x, ["FT2", "FT3", "FT4", "FT8"])
    axes[1].set_ylabel("Common H1-H3 RMSE")
    axes[1].set_title("b  Experimental harmonics", loc="left", fontweight="bold")
    axes[1].legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=2,
    )

    thermo = ("G_OH", "G_O", "scaling_OOH_OH")
    thermo_labels = ("$G_{OH}$", "$G_O$", "OOH-OH scaling")
    for offset, mode, color in zip((-width / 2, width / 2), modes, colors):
        representative_rows = []
        for dataset in datasets:
            candidates = [
                row
                for row in rows
                if row["dataset"] == dataset
                and row["feature_mode"] == mode
            ]
            representative_rows.append(candidates)
        cvs = []
        for parameter in thermo:
            values = [
                float(np.median([float(row[parameter]) for row in candidates]))
                for candidates in representative_rows
            ]
            cvs.append(float(np.std(values) / abs(np.mean(values))))
        axes[2].bar(
            np.arange(3) + offset,
            cvs,
            width,
            color=color,
        )
    axes[2].set_xticks(np.arange(3), thermo_labels)
    axes[2].set_ylabel("Cross-dataset coefficient of variation")
    axes[2].set_title("c  Parameter stability", loc="left", fontweight="bold")

    fig.suptitle(
        "Legacy and Complex-SNR objectives under matched budgets",
        fontsize=13,
        fontweight="bold",
    )
    fig.tight_layout()
    _save(fig, "feature_objective_comparison")


def plot_reconstruction_comparison() -> None:
    rows = _rows("reconstruction_model_comparison.csv")
    datasets = sorted({row["dataset"] for row in rows})
    grouped = {
        (dataset, model): sorted(
            [
                row for row in rows
                if row["dataset"] == dataset and row["model"] == model
            ],
            key=lambda row: int(row["seed"]),
        )
        for dataset in datasets
        for model in ("M0", "M1")
    }

    fig, axes = plt.subplots(1, 3, figsize=(13.2, 4.2))
    x = np.arange(len(datasets))
    width = 0.36
    for offset, model, color in (
        (-width / 2, "M0", M0_COLOR),
        (width / 2, "M1", M1_COLOR),
    ):
        axes[0].bar(
            x + offset,
            [
                np.mean([
                    float(row["high_potential_shape_rmse"])
                    for row in grouped[(dataset, model)]
                ])
                for dataset in datasets
            ],
            width,
            color=color,
            label=model,
        )
    axes[0].set_xticks(x, ["FT2", "FT3", "FT4", "FT8"])
    axes[0].set_ylabel("High-potential shape RMSE")
    axes[0].set_title("a  Structured DC residual", loc="left", fontweight="bold")
    axes[0].legend(loc="upper right")

    delta_bic = [
        np.mean([
            float(m1["bic"]) - float(m0["bic"])
            for m0, m1 in zip(
                grouped[(dataset, "M0")],
                grouped[(dataset, "M1")],
            )
        ])
        for dataset in datasets
    ]
    axes[1].bar(
        x,
        delta_bic,
        color=[M1_COLOR if value > 0 else M0_COLOR for value in delta_bic],
    )
    axes[1].axhline(0.0, color=NEUTRAL, linewidth=1.0)
    axes[1].set_xticks(x, ["FT2", "FT3", "FT4", "FT8"])
    axes[1].set_ylabel(r"$\Delta$BIC (M1 - M0)")
    axes[1].set_title("b  Complexity penalty", loc="left", fontweight="bold")

    ratios = [
        np.mean([
            float(m1["h1_h3_loss"])
            / max(float(m0["h1_h3_loss"]), 1e-12)
            for m0, m1 in zip(
                grouped[(dataset, "M0")],
                grouped[(dataset, "M1")],
            )
        ])
        for dataset in datasets
    ]
    axes[2].bar(
        x,
        ratios,
        color=[M0_COLOR if value <= 1.05 else M1_COLOR for value in ratios],
    )
    axes[2].axhline(1.0, color=NEUTRAL, linewidth=1.0)
    axes[2].axhline(1.05, color=NEUTRAL, linewidth=1.0, linestyle="--")
    axes[2].set_xticks(x, ["FT2", "FT3", "FT4", "FT8"])
    axes[2].set_ylabel("M1 / M0 H1-H3 loss")
    axes[2].set_title("c  Harmonic preservation", loc="left", fontweight="bold")

    fig.suptitle(
        "Paired-seed comparison of baseline and reconstruction models",
        fontsize=13,
        fontweight="bold",
    )
    fig.tight_layout()
    _save(fig, "reconstruction_model_comparison")


def main() -> None:
    plot_feature_comparison()
    plot_reconstruction_comparison()
    print("ARCHITECTURE_VALIDATION_FIGURES_OK")


if __name__ == "__main__":
    main()
