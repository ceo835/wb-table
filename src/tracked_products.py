from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
TRACKED_PRODUCTS_PATH = ROOT_DIR / "data" / "config" / "tracked_products.csv"
TRACKED_PRODUCT_COLUMNS = [
    "nm_id",
    "item_label",
    "is_tracked",
    "lifecycle_status",
    "source",
]
DEFAULT_LIFECYCLE_STATUS = "not_tracked"


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "" or value != value:
        return False
    return str(value).strip().lower() == "true"


def load_tracked_products(path: Path | None = None) -> pd.DataFrame:
    csv_path = path or TRACKED_PRODUCTS_PATH
    if not csv_path.exists():
        return pd.DataFrame(columns=TRACKED_PRODUCT_COLUMNS + ["tracked_label"])

    tracked_df = pd.read_csv(csv_path)
    for column in TRACKED_PRODUCT_COLUMNS:
        if column not in tracked_df.columns:
            tracked_df[column] = pd.NA

    tracked_df = tracked_df[TRACKED_PRODUCT_COLUMNS].copy()
    tracked_df["nm_id"] = pd.to_numeric(tracked_df["nm_id"], errors="coerce")
    tracked_df = tracked_df.dropna(subset=["nm_id"]).copy()
    tracked_df["nm_id"] = tracked_df["nm_id"].astype(int)
    tracked_df["is_tracked"] = tracked_df["is_tracked"].map(_normalize_bool)
    tracked_df["lifecycle_status"] = (
        tracked_df["lifecycle_status"]
        .fillna(DEFAULT_LIFECYCLE_STATUS)
        .astype(str)
        .str.strip()
        .str.lower()
        .replace("", DEFAULT_LIFECYCLE_STATUS)
    )
    tracked_df["tracked_label"] = (
        tracked_df["item_label"]
        .fillna("")
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
    )
    return tracked_df.drop_duplicates(subset=["nm_id"], keep="first")


def get_tracked_nm_ids(path: Path | None = None) -> list[int]:
    tracked_df = load_tracked_products(path)
    if tracked_df.empty:
        return []
    return tracked_df.loc[tracked_df["is_tracked"], "nm_id"].astype(int).tolist()


def apply_tracked_products(df: pd.DataFrame, path: Path | None = None) -> pd.DataFrame:
    enriched = df.copy()
    if "nm_id" not in enriched.columns:
        if "is_tracked" not in enriched.columns:
            enriched["is_tracked"] = False
        if "tracked_label" not in enriched.columns:
            enriched["tracked_label"] = pd.NA
        if "lifecycle_status" not in enriched.columns:
            enriched["lifecycle_status"] = DEFAULT_LIFECYCLE_STATUS
        return enriched

    tracked_df = load_tracked_products(path)
    for column in ("is_tracked", "tracked_label", "lifecycle_status"):
        if column in enriched.columns:
            enriched = enriched.drop(columns=[column])

    enriched["nm_id"] = pd.to_numeric(enriched["nm_id"], errors="coerce")
    if tracked_df.empty:
        enriched["is_tracked"] = False
        enriched["tracked_label"] = pd.NA
        enriched["lifecycle_status"] = DEFAULT_LIFECYCLE_STATUS
        return enriched

    merged = enriched.merge(
        tracked_df[["nm_id", "is_tracked", "tracked_label", "lifecycle_status"]],
        on="nm_id",
        how="left",
    )
    merged["is_tracked"] = merged["is_tracked"].where(merged["is_tracked"].notna(), False).astype(bool)
    merged["lifecycle_status"] = (
        merged["lifecycle_status"]
        .fillna(DEFAULT_LIFECYCLE_STATUS)
        .astype(str)
        .replace("", DEFAULT_LIFECYCLE_STATUS)
    )
    return merged
