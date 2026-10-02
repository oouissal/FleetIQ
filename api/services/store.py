"""Gold store: reads gold tables from the local filesystem or MinIO.

Handles both producers of gold data:
  * batch builder (ml/gold.py)        -> flat parquet files
  * Spark streaming (aggregates.py)   -> directories of appended parquet
    files with a `window` struct column {start, end}

Both shapes are normalised to pandas DataFrames with a `window_start`
timestamp column. Reads are cached for a short TTL so streaming output is
picked up without hammering storage.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import pandas as pd

from api.config import ApiConfig

log = logging.getLogger("api.store")


def _s3_fs(cfg: ApiConfig):
    import s3fs

    return s3fs.S3FileSystem(
        anon=False,
        key=cfg.s3_access_key or None,
        secret=cfg.s3_secret_key or None,
        client_kwargs={"endpoint_url": cfg.s3_endpoint},
    )


class GoldStore:
    def __init__(self, cfg: ApiConfig) -> None:
        self.cfg = cfg
        self._cache: dict[str, tuple[float, pd.DataFrame]] = {}

    # ------------------------------------------------------------------ io
    def _is_s3(self) -> bool:
        return self.cfg.lake_base.startswith("s3a://")

    def _path_for(self, table: str) -> str:
        root = self.cfg.gold_root
        if self._is_s3():
            # s3a://gold/<table> -> s3://<bucket>/<table>
            bucket = root.replace("s3a://", "").rstrip("/")
            return f"s3://{bucket}/{table}"
        return str(Path(root) / table)

    def _read_table(self, table: str) -> Optional[pd.DataFrame]:
        path = self._path_for(table)
        try:
            if self._is_s3():
                fs = _s3_fs(self.cfg)
                # streaming writes a DIRECTORY of parquet files; the batch
                # builder writes a single flat file. Prefer the directory.
                if fs.exists(f"{path}/") and fs.ls(f"{path}/"):
                    with fs.open(f"{path}/*.parquet") as f:
                        return pd.read_parquet(f)
                if fs.exists(f"{path}.parquet"):
                    with fs.open(f"{path}.parquet") as f:
                        return pd.read_parquet(f)
                return None
            # local: flat file or directory of parquet files
            p = Path(path)
            if p.is_dir():
                files = list(p.glob("*.parquet"))
                if not files:
                    return None
                return pd.read_parquet(p)
            if p.with_suffix(".parquet").exists() and not p.exists():
                return pd.read_parquet(p.with_suffix(".parquet"))
            if p.exists():
                return pd.read_parquet(p)
            return None
        except FileNotFoundError:
            return None
        except Exception as exc:  # noqa: BLE001 - graceful fallback for API
            log.warning("Could not read gold table %s: %s", table, exc)
            return None

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        if "window" in df.columns:
            # Spark struct {start, end} or nested dicts from pandas
            df["window_start"] = df["window"].apply(
                lambda w: w.get("start") if isinstance(w, dict) else getattr(w, "start", None))
            df = df.drop(columns=["window"])
        for col in ("window_start", "timestamp", "last_seen"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")
        return df

    def read(self, table: str, ttl: Optional[int] = None) -> pd.DataFrame:
        """Cached read; empty DataFrame when the table is missing."""
        ttl = self.cfg.store_ttl_seconds if ttl is None else ttl
        now = time.time()
        hit = self._cache.get(table)
        if hit and now - hit[0] < ttl:
            return hit[1]
        df = self._read_table(table)
        if df is None:
            df = pd.DataFrame()
        else:
            df = self._normalize(df)
        self._cache[table] = (now, df)
        return df

    def exists(self, table: str) -> bool:
        return len(self.read(table, ttl=0)) > 0

    # ------------------------------------------------------------ raw files
    def read_raw(self, filename: str) -> pd.DataFrame:
        """Read a raw parquet file (local path or MinIO raw bucket).
        Returns empty DataFrame if unavailable."""
        try:
            if self._is_s3():
                fs = _s3_fs(self.cfg)
                path = f"{self.cfg.raw_root.rstrip('/')}/{filename}"
                with fs.open(path) as f:
                    return pd.read_parquet(f)
            path = Path(self.cfg.raw_root) / filename
            if path.exists():
                return pd.read_parquet(path)
        except Exception as exc:  # noqa: BLE001 - graceful fallback for API
            log.warning("Could not read raw %s: %s", filename, exc)
        return pd.DataFrame()
