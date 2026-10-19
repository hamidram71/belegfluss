"""Command line entry point: ``belegfluss-synth --sets 200 --seed 42 --out data/synthetic``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from belegfluss.synth.dataset import write_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a labeled synthetic dataset.")
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--sets", type=int, default=200, help="number of document sets")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--suppliers", type=int, default=12)
    parser.add_argument(
        "--p-discrepant",
        type=float,
        default=0.45,
        help="share of sets that contain at least one discrepancy",
    )
    parser.add_argument("--force", action="store_true", help="write into a non-empty directory")
    args = parser.parse_args(argv)

    if args.out.exists() and any(args.out.iterdir()) and not args.force:
        print(f"{args.out} is not empty; use --force to overwrite files.", file=sys.stderr)
        return 1

    def progress(done: int, total: int) -> None:
        if done % 25 == 0 or done == total:
            print(f"  {done}/{total} sets", file=sys.stderr)

    manifest = write_dataset(
        args.out, args.sets, args.seed, args.p_discrepant, args.suppliers, progress
    )
    print(manifest.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
