#!/usr/bin/env python3
"""Create exploratory-only Tafel audits from CHI cyclic-voltammetry files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.cv_tafel_audit import audit_chi_cv


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in args.input:
        source = source.resolve()
        destination = output_dir / f"{source.stem}_audit.json"
        if destination.exists():
            raise FileExistsError(f"refusing to overwrite audit: {destination}")
        report = audit_chi_cv(source)
        destination.write_text(json.dumps(report, indent=2) + "\n")
        print(destination)


if __name__ == "__main__":
    main()
