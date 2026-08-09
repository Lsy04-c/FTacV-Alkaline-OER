#!/usr/bin/env python3
"""Materialize a post-experiment target bundle; never starts inversion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "code" / "python" / "src"))

from oer_aem.post_experiment import build_post_experiment_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feature-mode", default="hybrid")
    args = parser.parse_args(argv)
    summary = build_post_experiment_bundle(
        args.project_root, args.manifest, args.output, feature_mode=args.feature_mode
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "TARGET_BUNDLE_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
