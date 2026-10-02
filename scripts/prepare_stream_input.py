"""Prepare historical generator output for the Spark streaming FILE source.

The parquet file source requires a directory of files per domain. This
script splits the generator's flat parquet files into:

    <raw>/events/telemetry/part-00000.parquet
    <raw>/events/gps/part-00000.parquet
    <raw>/events/delivery/part-00000.parquet

Usage:
    python scripts/prepare_stream_input.py --raw data/raw --chunk 50000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FILES = {"telemetry": "telemetry.parquet", "gps": "gps.parquet",
         "delivery": "deliveries.parquet"}


def prepare(raw: Path, chunk: int) -> dict[str, int]:
    counts = {}
    for domain, filename in FILES.items():
        src = raw / filename
        if not src.exists():
            print(f"warning: {src} not found; skipping {domain}")
            continue
        out_dir = raw / "events" / domain
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.parquet"):
            old.unlink()
        df = pd.read_parquet(src)
        n_files = 0
        for i in range(0, max(1, len(df)), chunk):
            part = df.iloc[i:i + chunk]
            part.to_parquet(out_dir / f"part-{n_files:05d}.parquet", index=False)
            n_files += 1
        counts[domain] = n_files
        print(f"{domain}: {len(df)} rows -> {n_files} files")
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", default="data/raw", help="directory with the flat parquet files")
    p.add_argument("--chunk", type=int, default=50_000, help="rows per split file")
    args = p.parse_args(argv)
    prepare(Path(args.raw), args.chunk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())