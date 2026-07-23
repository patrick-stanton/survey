"""Catalog version snapshots.

Every survey build saves a snapshot of the catalog it was built from, keyed by
its content hash: data/catalog_versions/<hash>.csv. This is what lets the tool,
months later, tell you what a now-retired use-case id USED to be ("UC-005 was
'Rehearse a mission virtually'") during reconciliation, and detect when an id's
meaning has drifted (accidental id reuse). Snapshots are tiny and safe to commit.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SNAPSHOT_COLUMNS = ["id", "name", "description", "category"]


def snapshot_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "catalog_versions"


def save_snapshot(df: pd.DataFrame, data_dir: Path, catalog_hash: str) -> Path:
    """Write <hash>.csv if it doesn't already exist (versions are immutable)."""
    d = snapshot_dir(data_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{catalog_hash}.csv"
    if not path.exists():
        df[SNAPSHOT_COLUMNS].to_csv(path, index=False)
    return path


def load_snapshot(data_dir: Path, catalog_hash: str) -> dict[str, dict] | None:
    """{id -> {name, description, category}} for a past version, or None."""
    path = snapshot_dir(data_dir) / f"{catalog_hash}.csv"
    if not path.exists():
        return None
    snap = pd.read_csv(path, dtype=str).fillna("")
    return {r["id"]: {"name": r["name"], "description": r.get("description", ""),
                      "category": r.get("category", "")}
            for _, r in snap.iterrows()}


def known_name(data_dir: Path, item_id: str, version_hashes) -> str:
    """Best-effort historical name for an id, searching the given versions."""
    for h in version_hashes:
        snap = load_snapshot(data_dir, h)
        if snap and item_id in snap:
            return snap[item_id]["name"]
    return item_id
