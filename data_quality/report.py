"""Data-quality report generation (batch / historical path).

Reads parquet event files, validates them with the Pandera schemas and
writes a JSON report plus the invalid rows to parquet. Invalid records are
therefore kept and traceable — they never silently disappear.

The same rules run in the Spark streaming pipeline; this module is the
batch/historical + CI equivalent.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pandera as pa

from data_quality.schemas import schema_for

log = logging.getLogger("data_quality")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s - %(message)s")


def validate_dataframe(df: pd.DataFrame, event_type: str) -> dict[str, Any]:
    """Validate one domain DataFrame (lazy: collect all failures)."""
    schema = schema_for(event_type)
    try:
        schema.validate(df, lazy=True)
        return {"valid": True, "errors": [], "n_invalid": 0}
    except pa.errors.SchemaErrors as exc:
        failures = []
        for failure in exc.failure_cases.to_dict(orient="records"):
            failures.append({
                "column": failure.get("column"),
                "check": failure.get("check"),
                "failure_case": str(failure.get("failure_case"))[:200],
                "index": failure.get("index"),
            })
        # group counts per check for the summary
        summary: dict[str, int] = {}
        for f in failures:
            key = f"{f['column']}:{f['check']}"
            summary[key] = summary.get(key, 0) + 1
        return {
            "valid": False,
            "errors": failures,
            "summary": summary,
            "n_invalid": int(exc.failure_cases["index"].nunique()) if "index" in exc.failure_cases else 0,
        }


def run_report(input_path: Path, event_type: str, output_dir: Path) -> dict[str, Any]:
    """Full quality report for one parquet file."""
    df = pd.read_parquet(input_path)
    result = validate_dataframe(df, event_type)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "input_file": str(input_path),
        "total_records": len(df),
        "valid_records": len(df) - result["n_invalid"],
        "invalid_records": result["n_invalid"],
        "validity_rate": round((len(df) - result["n_invalid"]) / max(1, len(df)), 4),
        "failure_summary": result.get("summary", {}),
        "sample_failures": result["errors"][:20],
        "note": "Synthetic data; quality report for development/CI purposes.",
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"quality_{event_type}.json").write_text(
        json.dumps(report, indent=2))

    if result["n_invalid"] > 0:
        schema = schema_for(event_type)
        invalid_df = _extract_invalid_rows(df, event_type, schema)
        invalid_df.to_parquet(output_dir / f"invalid_{event_type}.parquet", index=False)
    else:
        pd.DataFrame().to_parquet(output_dir / f"invalid_{event_type}.parquet", index=False)

    log.info("quality[%s]: %s/%s valid (%.1f%%)",
             event_type, report["valid_records"], report["total_records"],
             100 * report["validity_rate"])
    return report


def _extract_invalid_rows(df: pd.DataFrame, event_type: str,
                          schema: type[pa.DataFrameModel]) -> pd.DataFrame:
    """Row-level validity using the same pandera checks (vectorised)."""
    try:
        checked = schema.validate(df, lazy=True)
        return checked  # never reached when invalid rows exist
    except pa.errors.SchemaErrors as exc:
        bad_idx = pd.Index(exc.failure_cases["index"].dropna().astype(int).unique())
        return df.loc[bad_idx].copy()
