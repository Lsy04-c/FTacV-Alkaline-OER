#!/usr/bin/env python3
"""Build traceable experimental noise evidence for Gate A6 recovery."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.data_contract import normalize_trace
from oer_aem.recovery import noise_fraction_evidence


DEFAULT_INPUTS = (
    ROOT / "data" / "raw" / "ftacv2-ref-5hz.txt",
    ROOT / "data" / "raw" / "ftacv3-ref-5Hz.txt",
    ROOT / "data" / "raw" / "ftacv4-ref-1hz.txt",
    ROOT / "data" / "raw" / "ftacv8-ref-5Hz.txt",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(path: Path) -> np.ndarray:
    rows = []
    for line in path.read_text().splitlines():
        try:
            values = [float(value) for value in line.replace(",", " ").split()[:3]]
        except ValueError:
            continue
        if len(values) == 3:
            rows.append(values)
    array = np.asarray(rows, dtype=float)
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValueError(f"no valid three-column rows in {path}")
    return array


def build_noise_evidence(paths: list[Path]) -> dict:
    datasets = []
    for path in paths:
        trace = normalize_trace(load_rows(path))
        datasets.append(
            {
                "filename": path.name,
                "sha256": sha256_file(path),
                "n_rows": int(trace.current.size),
                "noise": noise_fraction_evidence(trace.current),
            }
        )
    selected = max(
        float(row["noise"]["noise_fraction"]) for row in datasets
    )
    return {
        "selection_rule": "maximum_dataset_noise_floor",
        "selected_noise_fraction": selected,
        "datasets": datasets,
        "limitation": (
            "Quantized traces provide a measurement-resolution noise floor, "
            "not full repeatability uncertainty; no repeat traces are available."
        ),
    }


def git_state() -> tuple[str, bool]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    )
    return commit, dirty


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path, action="append")
    args = parser.parse_args(argv)
    commit, dirty = git_state()
    if dirty:
        raise RuntimeError("formal noise evidence requires a clean Git worktree")
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    payload = build_noise_evidence(list(args.input or DEFAULT_INPUTS))
    payload["source_commit"] = commit
    payload["dirty"] = dirty
    payload["command"] = (
        [sys.executable, *sys.argv]
        if argv is None else [sys.executable, *argv]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(output)


if __name__ == "__main__":
    main()
