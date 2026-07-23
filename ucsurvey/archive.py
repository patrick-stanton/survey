"""The append-only response archive and its pooling rules.

Raw truth lives in data/archive/ as one JSON file per (respondent, session):
files are only ever added or replaced by a newer export of the same session
(which is a superset — the survey app accumulates sets monotonically).
Nothing here ever rewrites survey answers; resolution is always recomputed
from the full pool, so responses collected on different days simply pool.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REQUIRED_TOP = ["sessionId", "respondent", "catalogVersionHash", "arm", "sets"]
REQUIRED_RESP = ["name", "email", "role", "organization", "familiarity"]


class ResponseError(ValueError):
    pass


@dataclass
class IngestReport:
    accepted: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (file, reason)


def validate_response(data: dict, catalog_hash: str, known_ids: set[str],
                      allow_hashes: set[str] = frozenset()) -> None:
    """Raise ResponseError if this response file can't be trusted.

    Response files are UNTRUSTED INPUT (anyone can email one), so beyond
    schema sanity this also rejects values that could misbehave downstream
    (e.g., path characters in identifiers that feed archive filenames).
    """
    for key in REQUIRED_TOP:
        if key not in data:
            raise ResponseError(f"missing field '{key}'")
    for key in REQUIRED_RESP:
        if key not in data["respondent"]:
            raise ResponseError(f"missing respondent field '{key}'")
    if not str(data["respondent"]["email"]).strip():
        raise ResponseError("empty respondent email")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(data["sessionId"])):
        raise ResponseError("sessionId contains characters the survey never produces")
    if len(data["sets"]) > 500:
        raise ResponseError("more screens than any survey design contains")

    h = data["catalogVersionHash"]
    if h != catalog_hash and h not in allow_hashes:
        raise ResponseError(
            f"catalog version mismatch: response was collected against catalog "
            f"{h}, current is {catalog_hash}. If the older wording is still "
            f"comparable, re-run with --allow-catalog {h}"
        )

    seen_idx = set()
    for s in data["sets"]:
        for key in ["index", "shown", "skipped"]:
            if key not in s:
                raise ResponseError(f"set missing field '{key}'")
        if s["index"] in seen_idx:
            raise ResponseError(f"duplicate set index {s['index']} within file")
        seen_idx.add(s["index"])
        if len(s["shown"]) != len(set(s["shown"])):
            raise ResponseError(f"set {s['index']} shows a repeated item")
        unknown = [i for i in s["shown"] if i not in known_ids]
        if unknown and h == catalog_hash:
            raise ResponseError(f"set {s['index']} references unknown items {unknown}")
        if not s["skipped"]:
            if s.get("best") not in s["shown"] or s.get("worst") not in s["shown"]:
                raise ResponseError(f"set {s['index']} best/worst not among shown items")
            if s["best"] == s["worst"]:
                raise ResponseError(f"set {s['index']} has best == worst")


def _slug(email: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", email.lower()).strip("-")[:80]


def archive_filename(data: dict) -> str:
    # Both parts are re-sanitized here (defense in depth — validation already
    # rejects hostile sessionIds) so this can never emit path separators.
    session = re.sub(r"[^A-Za-z0-9._-]+", "-", str(data["sessionId"]))[:64]
    return f"{_slug(data['respondent']['email'])}__{session}.json"


def ingest_file(src: Path, archive_dir: Path, catalog_hash: str,
                known_ids: set[str], report: IngestReport,
                allow_hashes: set[str] = frozenset()) -> None:
    """Validate one returned file and add/replace it in the archive."""
    if Path(src).stat().st_size > 5_000_000:
        report.rejected.append(
            (src.name, "over 5 MB — real result files are a few KB"))
        return
    try:
        data = json.loads(Path(src).read_text(encoding="utf-8"))
        validate_response(data, catalog_hash, known_ids, allow_hashes)
    except (json.JSONDecodeError, ResponseError) as exc:
        report.rejected.append((src.name, str(exc)))
        return

    dest = archive_dir / archive_filename(data)
    if dest.exists():
        old = json.loads(dest.read_text(encoding="utf-8"))
        if len(data["sets"]) < len(old["sets"]):
            report.rejected.append(
                (src.name, f"older than archived copy ({len(data['sets'])} < "
                           f"{len(old['sets'])} screens) — keeping the archive version")
            )
            return
        if len(data["sets"]) == len(old["sets"]):
            report.unchanged.append(src.name)
            return
        report.replaced.append(src.name)
    else:
        report.accepted.append(src.name)
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, indent=1), encoding="utf-8")


def load_archive(archive_dir: Path) -> pd.DataFrame:
    """All archived answers as one long table: a row per answered screen slot.

    Columns: email, name, role, organization, familiarity, session_id, arm,
    set_index, item_id, pick (best|worst|middle), skipped, response_ms,
    answered_at. Skipped sets keep their rows (pick='skipped') so exposure
    accounting can still see them, but they carry no preference signal.
    """
    rows = []
    for f in sorted(Path(archive_dir).glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        r = data["respondent"]
        for s in data["sets"]:
            for item in s["shown"]:
                if s["skipped"]:
                    pick = "skipped"
                elif item == s["best"]:
                    pick = "best"
                elif item == s["worst"]:
                    pick = "worst"
                else:
                    pick = "middle"
                rows.append({
                    "email": str(r["email"]).lower(),
                    "name": r["name"],
                    "role": r["role"],
                    "organization": r["organization"],
                    "familiarity": r["familiarity"],
                    "session_id": data["sessionId"],
                    "arm": data["arm"],
                    "set_index": s["index"],
                    "item_id": item,
                    "pick": pick,
                    "skipped": bool(s["skipped"]),
                    "response_ms": s.get("responseMs"),
                    "answered_at": s.get("answeredAt", ""),
                })
    columns = ["email", "name", "role", "organization", "familiarity", "session_id",
               "arm", "set_index", "item_id", "pick", "skipped", "response_ms",
               "answered_at"]
    return pd.DataFrame(rows, columns=columns)


def apply_lineage(long_df: pd.DataFrame, mapping: dict[str, str],
                  known_ids: set[str], mode: str) -> pd.DataFrame:
    """Resolve historical item ids against the current catalog.

    strict  : answers about ids no longer in the catalog are dropped
    inherit : predecessor ids are re-labeled to their successor first
              (a vote for the old use case counts for the merged one)
    """
    df = long_df.copy()
    if mode == "inherit" and mapping:
        df["item_id"] = df["item_id"].map(lambda i: mapping.get(i, i))
        # A merge can make two cards in one set collapse to the same successor;
        # their head-to-head comparison is then meaningless — drop extra rows,
        # keeping the most informative pick (best/worst beats middle).
        rank = {"best": 0, "worst": 0, "middle": 1, "skipped": 1}
        df["_r"] = df["pick"].map(rank)
        df = (df.sort_values("_r")
                .drop_duplicates(["email", "session_id", "set_index", "item_id"])
                .drop(columns="_r"))
    elif mode != "strict":
        raise ValueError(f"lineage mode must be 'strict' or 'inherit', got {mode!r}")
    return df[df["item_id"].isin(known_ids)].reset_index(drop=True)
