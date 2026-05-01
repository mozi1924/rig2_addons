#!/usr/bin/env python3
"""Validate extracted Rig2 runtime native binaries before artifact upload."""

from __future__ import annotations

import argparse
from pathlib import Path

from native_artifacts import validate_runtime_layout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Native distribution root to validate")
    parser.add_argument(
        "--require-complete-matrix",
        action="store_true",
        help="Fail unless every expected OS/arch runtime tag is present",
    )
    args = parser.parse_args()

    if not args.root.is_dir():
        raise FileNotFoundError(f"native distribution root not found: {args.root}")

    errors = validate_runtime_layout(
        args.root,
        require_complete_matrix=args.require_complete_matrix,
    )
    if errors:
        raise SystemExit("Invalid runtime layout:\n" + "\n".join(errors))

    print(f"[verify-native-dist] layout OK: {args.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
