#!/usr/bin/env python3
"""Gate A7 infrastructure smoke: deterministic output for workflow verification.

Produces summary.csv + manifest.json; exits 0 (SUCCESS) by default.
With --fail-numerical, exits 2 (FAIL_NUMERICAL).
With --fail-infra, exits 7 (FAIL_INFRA).
With --missing-output, skips writing CSV (tests structure gate).
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--fail-numerical", action="store_true")
    p.add_argument("--fail-infra", action="store_true")
    p.add_argument("--missing-output", action="store_true")
    # Accept common smoke override params (no-op for this test script)
    p.add_argument("--n_samples", type=int, default=None)
    p.add_argument("--max_steps", type=int, default=None)
    p.add_argument("--max_iter", type=int, default=None)
    p.add_argument("--timeout", type=int, default=None)
    p.add_argument("--debug", action="store_true")
    args, _ = p.parse_known_args()

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    # Write STATUS.json via wrapper or directly
    status_file = out / "STATUS.json"
    if not args.missing_output:
        csv_file = out / "summary.csv"
        rows = [
            {"sample": 0, "value": 1.0},
            {"sample": 1, "value": 2.0},
            {"sample": 2, "value": 3.0},
        ]
        with open(csv_file, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["sample", "value"])
            w.writeheader()
            w.writerows(rows)

        manifest = {
            "files": [
                {"path": "summary.csv", "bytes": csv_file.stat().st_size,
                 "sha256": "test"},
                {"path": "STATUS.json", "bytes": 0, "sha256": "test"},
            ],
            "commit": os.environ.get("OER_WF_COMMIT", "unknown"),
            "task_id": os.environ.get("OER_WF_TASK_ID", "unknown"),
        }
        with open(out / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2)

    if args.fail_numerical:
        print("Simulated numerical failure", file=sys.stderr)
        sys.exit(2)
    if args.fail_infra:
        print("Simulated infra failure", file=sys.stderr)
        sys.exit(7)

    print(f"SUCCESS: wrote to {out}")


if __name__ == "__main__":
    main()
