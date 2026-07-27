"""Minimal deterministic task for real oer-wf infrastructure acceptance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be positive")

    args.output.mkdir(parents=True, exist_ok=True)
    arithmetic = sum(value * value for value in range(1, 6))
    (args.output / "summary.csv").write_text(
        f"check,value\nworkers,{args.workers}\narithmetic,{arithmetic}\n",
        encoding="utf-8",
    )
    (args.output / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "workers": args.workers,
                "checks": {"sum_of_squares_1_to_5": arithmetic},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
