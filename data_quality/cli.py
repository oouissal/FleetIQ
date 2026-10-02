"""Run data-quality reports from the command line.

Examples:
    python -m data_quality.report --input data/raw/telemetry.parquet \
        --type telemetry --output monitoring/reports
    python -m data_quality.report --input data/raw --all \
        --output monitoring/reports
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_quality.report import run_report

FILE_MAP = {"telemetry": "telemetry.parquet", "gps": "gps.parquet",
            "delivery": "deliveries.parquet"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True,
                   help="parquet file, or a directory when --all is used")
    p.add_argument("--type", choices=sorted(FILE_MAP), default=None,
                   help="event type (single-file mode)")
    p.add_argument("--all", action="store_true",
                   help="run reports for all three domains in the directory")
    p.add_argument("--output", default="monitoring/reports",
                   help="output directory for reports")
    args = p.parse_args(argv)

    src = Path(args.input)
    out = Path(args.output)
    if args.all:
        if not src.is_dir():
            print(f"error: --all requires --input to be a directory, got {src}")
            return 2
        reports = {}
        for event_type, filename in FILE_MAP.items():
            f = src / filename
            if not f.exists():
                print(f"warning: {f} not found; skipping {event_type}")
                continue
            reports[event_type] = run_report(f, event_type, out)
        if not reports:
            print("error: no parquet files found")
            return 2
        total = sum(r["total_records"] for r in reports.values())
        bad = sum(r["invalid_records"] for r in reports.values())
        print(f"Overall: {total - bad}/{total} records valid")
        return 0

    if not args.type:
        print("error: either --type or --all is required")
        return 2
    if not src.is_file():
        print(f"error: {src} is not a file")
        return 2
    report = run_report(src, args.type, out)
    print(f"{report['valid_records']}/{report['total_records']} records valid "
          f"({report['validity_rate']:.1%})")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
