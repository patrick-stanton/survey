"""Cross-version use-case lineage: how retired ids map to current ones.

Two sources feed one map, both saying "old id X was superseded by new id(s) Y":
  * the `supersedes` column in use_cases.csv (declared in Cameo)
  * data/lineage.csv (built interactively by reconcile.py, git-committable)

A retired id can map to zero successors (dropped), one (rename or merge target),
or several (a split — each child inherits the parent's votes). Chains resolve
transitively to CURRENT ids: if UC-005 -> UC-062 and UC-062 -> UC-070, then
UC-005 -> UC-070. Any historical id that is neither current nor mapped is an
UNMAPPED ORPHAN; resolve.py refuses to run until reconcile.py handles it, so
real data is never silently dropped.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd

from . import catalog as cat

LINEAGE_COLUMNS = ["old_id", "disposition", "new_ids", "note", "decided_on"]
DISPOSITIONS = ["renamed", "split", "merged", "dropped", "revived"]


# ---------------------------------------------------------------------------
# The lineage.csv file (managed by reconcile.py, editable by hand)
# ---------------------------------------------------------------------------

def default_path(data_dir: Path) -> Path:
    return Path(data_dir) / "lineage.csv"


def load_lineage_rows(path: Path) -> list[dict]:
    if not Path(path).exists():
        return []
    df = pd.read_csv(path, dtype=str).fillna("")
    return [{c: r.get(c, "") for c in LINEAGE_COLUMNS} for _, r in df.iterrows()]


def write_lineage_rows(path: Path, rows: list[dict]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=LINEAGE_COLUMNS).to_csv(path, index=False)


def append_lineage_row(path: Path, old_id: str, disposition: str,
                       new_ids: list[str], note: str = "") -> None:
    rows = [r for r in load_lineage_rows(path) if r["old_id"] != old_id]
    rows.append({
        "old_id": old_id, "disposition": disposition,
        "new_ids": ";".join(new_ids), "note": note,
        "decided_on": datetime.date.today().isoformat(),
    })
    write_lineage_rows(path, rows)


# ---------------------------------------------------------------------------
# Building the map and resolving it transitively
# ---------------------------------------------------------------------------

def raw_map(df: pd.DataFrame, lineage_path: Path) -> dict[str, list[str]]:
    """Merge the catalog's supersedes column and lineage.csv into
    {old_id -> [successor_id, ...]}. An explicit 'dropped' maps to []."""
    merged: dict[str, list[str]] = {}
    for old, succs in cat.lineage_map(df).items():  # supersedes column
        merged[old] = list(succs)
    for row in load_lineage_rows(lineage_path):
        old = row["old_id"].strip()
        if not old:
            continue
        succ = [s.strip() for s in row["new_ids"].split(";") if s.strip()]
        merged[old] = succ  # lineage.csv wins over supersedes if both present
    return merged


def resolve_to_current(item_id: str, raw: dict[str, list[str]],
                       current_ids: set[str], _seen=None) -> list[str]:
    """Follow the lineage chain from item_id down to CURRENT ids (dead/dropped
    branches contribute nothing). Cycle-guarded."""
    if item_id in current_ids:
        return [item_id]
    _seen = _seen or set()
    if item_id in _seen or item_id not in raw:
        return []
    _seen = _seen | {item_id}
    out: list[str] = []
    for succ in raw[item_id]:
        for cur in resolve_to_current(succ, raw, current_ids, _seen):
            if cur not in out:
                out.append(cur)
    return out


def closure(raw: dict[str, list[str]], current_ids: set[str]) -> dict[str, list[str]]:
    """{old_id -> [current successor ids]} for every mapped, non-current id."""
    return {old: resolve_to_current(old, raw, current_ids)
            for old in raw if old not in current_ids}


def unmapped_orphans(historical_ids: set[str], current_ids: set[str],
                     raw: dict[str, list[str]]) -> list[str]:
    """Historical ids that are neither current nor given any disposition."""
    return sorted(i for i in historical_ids
                  if i not in current_ids and i not in raw)


def dangling_targets(raw: dict[str, list[str]], current_ids: set[str]) -> list[str]:
    """Mapped successors that resolve to nothing current (points to a ghost)."""
    bad = []
    for old in raw:
        if old in current_ids:
            continue
        if raw[old] and not resolve_to_current(old, raw, current_ids):
            bad.append(old)
    return bad


def historical_ids(long_df: pd.DataFrame) -> set[str]:
    return set(long_df["item_id"].unique()) if not long_df.empty else set()


# ---------------------------------------------------------------------------
# ID-reuse drift detection (warn if an id's meaning changed between versions)
# ---------------------------------------------------------------------------

def _similar(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def name_drift_warnings(long_df: pd.DataFrame, df: pd.DataFrame, data_dir: Path,
                        threshold: float = 0.4) -> list[str]:
    """For each current id, compare its current name to the name in the version
    each response was collected under; warn on a big change (possible id reuse)."""
    from . import versions
    if long_df.empty:
        return []
    current_name = dict(zip(df["id"], df["name"]))
    # versions actually present in the data would require the per-response hash;
    # load_archive drops it, so scan all snapshots and compare to current.
    warnings = []
    snap_dir = versions.snapshot_dir(data_dir)
    if not snap_dir.exists():
        return []
    for snap_file in sorted(snap_dir.glob("*.csv")):
        snap = versions.load_snapshot(data_dir, snap_file.stem)
        if not snap:
            continue
        for item_id, cur_name in current_name.items():
            if item_id in snap:
                old_name = snap[item_id]["name"]
                if old_name and _similar(old_name, cur_name) < threshold:
                    msg = (f"{item_id}: name changed from '{old_name[:40]}' to "
                           f"'{cur_name[:40]}' since version {snap_file.stem} — "
                           "confirm this is the SAME use case (never reuse an id).")
                    if msg not in warnings:
                        warnings.append(msg)
    return warnings
