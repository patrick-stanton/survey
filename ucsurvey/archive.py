"""The response archive: where raw data lives and how it is protected.

Layout (see docs/DATA_MODEL.md):

    <archive>/active/         one CSV per respondent-session — the COUNTED data
    <archive>/excluded/<why>/ responses removed from analysis, KEPT for audit

Rules:
  * The raw file a respondent sent is stored VERBATIM (or, for legacy JSON/code
    inputs, converted once to the canonical CSV). Nothing is ever silently
    rewritten.
  * Removing bad data = moving its file from active/ to excluded/<reason>/
    (see exclude.py). It is never deleted, so any past result is reproducible
    and any exclusion is reversible and auditable.
  * resolve.py reads ONLY active/, and reports what is excluded.

Response files are UNTRUSTED INPUT. validate_response() turns any malformed or
hostile value into a clean ResponseError (never a crash), bounds screen width,
and rejects control characters. verify_screens_against_design() additionally
re-derives what each respondent should have seen and rejects fabricated screens.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import csv_result
from .design import derive_respondent_sets

REQUIRED_TOP = ["sessionId", "respondent", "catalogVersionHash", "arm", "sets"]
REQUIRED_RESP = ["name", "email", "role", "organization", "familiarity"]
ACTIVE = "active"
EXCLUDED = "excluded"
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class ResponseError(ValueError):
    pass


@dataclass
class IngestReport:
    accepted: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (file, reason)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation (schema / types / bounds / control chars)
# ---------------------------------------------------------------------------

def _clean_text(value, field_name: str, max_len: int = 200) -> str:
    if not isinstance(value, str):
        raise ResponseError(f"{field_name} must be text, got {type(value).__name__}")
    if _CONTROL_CHARS.search(value):
        raise ResponseError(f"{field_name} contains control characters")
    if len(value) > max_len:
        raise ResponseError(f"{field_name} is unreasonably long ({len(value)} chars)")
    return value.strip()


def validate_response(data: dict, catalog_hash: str, known_ids: set[str],
                      allow_hashes: set[str] = frozenset(),
                      items_per_screen: int | None = None) -> None:
    """Raise ResponseError if this response can't be trusted structurally."""
    if not isinstance(data, dict):
        raise ResponseError("response is not an object")
    for key in REQUIRED_TOP:
        if key not in data:
            raise ResponseError(f"missing field '{key}'")
    if not isinstance(data["respondent"], dict):
        raise ResponseError("'respondent' is not an object")
    if not isinstance(data["sets"], list):
        raise ResponseError("'sets' is not a list")
    for key in REQUIRED_RESP:
        if key not in data["respondent"]:
            raise ResponseError(f"missing respondent field '{key}'")

    email = _clean_text(data["respondent"]["email"], "email", max_len=254)
    if not email:
        raise ResponseError("empty respondent email")
    for fld in ("name", "role", "organization"):
        _clean_text(data["respondent"][fld], fld)

    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", str(data["sessionId"])):
        raise ResponseError("sessionId contains characters the survey never produces")
    if len(data["sets"]) > 500:
        raise ResponseError("more screens than any survey design contains")

    h = data["catalogVersionHash"]
    if h != catalog_hash and h not in allow_hashes:
        raise ResponseError(
            f"catalog version mismatch: collected against {h}, current is "
            f"{catalog_hash}. If the wording is still comparable, re-run with "
            f"--allow-catalog {h}")

    seen_idx = set()
    for s in data["sets"]:
        if not isinstance(s, dict):
            raise ResponseError("a set entry is not an object")
        for key in ["index", "shown", "skipped"]:
            if key not in s:
                raise ResponseError(f"set missing field '{key}'")
        if not isinstance(s["index"], int) or isinstance(s["index"], bool):
            raise ResponseError(f"set index must be an integer, got {s['index']!r}")
        if not isinstance(s["shown"], list):
            raise ResponseError(f"set {s['index']} 'shown' is not a list")
        if s["index"] in seen_idx:
            raise ResponseError(f"duplicate set index {s['index']} within response")
        seen_idx.add(s["index"])
        if items_per_screen is not None and len(s["shown"]) > items_per_screen:
            raise ResponseError(
                f"set {s['index']} shows {len(s['shown'])} items; the design uses "
                f"{items_per_screen} — not a genuine survey screen")
        if len(s["shown"]) > 16:
            raise ResponseError(f"set {s['index']} shows too many items")
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


def verify_screens_against_design(data: dict, payload: dict) -> None:
    """Re-derive the screens this respondent should have seen and confirm the
    reported 'shown' items match. Blocks fabricated screens — the core integrity
    control that makes a legible CSV as trustworthy as an encoded blob.

    Only checked when the response was collected against the CURRENT catalog
    (an --allow-catalog older response was built from a design we no longer have).
    """
    if data["catalogVersionHash"] != payload["catalogVersionHash"]:
        return
    arm = data["arm"]
    if arm not in payload["arms"]:
        raise ResponseError(f"unknown arm {arm!r}")
    item_ids = [it["id"] for it in payload["catalog"]]
    email = str(data["respondent"]["email"]).lower()
    seed = f"{email}|{data['sessionId']}"
    plan = derive_respondent_sets(payload["arms"][arm]["master"], item_ids, seed)
    extra = int(data.get("extraBlocks", 0) or 0)
    for b in range(1, extra + 1):
        plan += derive_respondent_sets(payload["continuationMaster"], item_ids,
                                       f"{seed}|cont{b}")
    for s in data["sets"]:
        i = s["index"]
        if not isinstance(i, int) or i < 0 or i >= len(plan):
            raise ResponseError(f"screen index {i} outside this respondent's design")
        if list(s["shown"]) != list(plan[i]):
            raise ResponseError(
                f"screen {i} shows items this respondent's survey never presented "
                "(fabricated or corrupted) — rejected")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _slug(email: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", email.lower()).strip("-")[:80]


def archive_basename(data: dict) -> str:
    session = re.sub(r"[^A-Za-z0-9._-]+", "-", str(data["sessionId"]))[:64]
    return f"{_slug(data['respondent']['email'])}__{session}.csv"


def _same_screen(a: dict, b: dict) -> bool:
    return (list(a.get("shown") or []) == list(b.get("shown") or [])
            and a.get("best") == b.get("best") and a.get("worst") == b.get("worst")
            and bool(a.get("skipped")) == bool(b.get("skipped")))


def load_result_file(path: Path) -> dict:
    """Read a stored/received result file (.csv canonical, or legacy .json)."""
    text = Path(path).read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return csv_result.parse_csv(text)


def ingest_result(data: dict, active_dir: Path, report: IngestReport,
                  source_name: str) -> None:
    """Write a validated response into active/ as canonical CSV, honoring the
    append-only supersede rule (a larger re-export may only ADD screens)."""
    dest = active_dir / archive_basename(data)
    if dest.exists():
        try:
            old = csv_result.parse_csv(dest.read_text(encoding="utf-8"))
        except (csv_result.CsvResultError, OSError) as exc:
            report.rejected.append((source_name, f"archived copy unreadable: {exc}"))
            return
        if len(data["sets"]) < len(old["sets"]):
            report.rejected.append(
                (source_name, f"older than archived copy ({len(data['sets'])} < "
                              f"{len(old['sets'])} screens) — keeping the archive version"))
            return
        old_by_index = {s["index"]: s for s in old["sets"]}
        for s in data["sets"]:
            prior = old_by_index.get(s["index"])
            if prior is not None and not _same_screen(s, prior):
                report.rejected.append(
                    (source_name, f"screen {s['index']} differs from the archived copy "
                                  "for this session — not an append-only re-export; "
                                  "keeping the original"))
                return
        if len(data["sets"]) == len(old["sets"]):
            report.unchanged.append(source_name)
            return
        report.replaced.append(source_name)
    else:
        report.accepted.append(source_name)
    active_dir.mkdir(parents=True, exist_ok=True)
    dest.write_text(csv_result.build_csv(data), encoding="utf-8")


def active_dir(archive_dir: Path) -> Path:
    return Path(archive_dir) / ACTIVE


def load_archive(archive_dir: Path) -> pd.DataFrame:
    """Every ACTIVE answer as one long table (a row per answered screen slot).

    Columns: email, name, role, organization, familiarity, session_id, arm,
    set_index, item_id, pick (best|worst|middle|skipped), skipped, response_ms.
    """
    adir = active_dir(archive_dir)
    search = adir if adir.exists() else Path(archive_dir)  # tolerate flat layout
    rows = []
    for f in sorted(list(search.glob("*.csv")) + list(search.glob("*.json"))):
        try:
            data = load_result_file(f)
        except (csv_result.CsvResultError, json.JSONDecodeError):
            continue
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
                    "email": str(r["email"]).lower(), "name": r["name"],
                    "role": r["role"], "organization": r["organization"],
                    "familiarity": r["familiarity"], "session_id": data["sessionId"],
                    "arm": data["arm"], "set_index": s["index"], "item_id": item,
                    "pick": pick, "skipped": bool(s["skipped"]),
                    "response_ms": s.get("responseMs"), "answered_at": s.get("answeredAt", ""),
                })
    columns = ["email", "name", "role", "organization", "familiarity", "session_id",
               "arm", "set_index", "item_id", "pick", "skipped", "response_ms",
               "answered_at"]
    return pd.DataFrame(rows, columns=columns)


def excluded_summary(archive_dir: Path) -> dict[str, int]:
    """{reason: file count} for everything currently quarantined."""
    base = Path(archive_dir) / EXCLUDED
    out: dict[str, int] = {}
    if base.exists():
        for reason_dir in sorted(base.iterdir()):
            if reason_dir.is_dir():
                out[reason_dir.name] = len(list(reason_dir.glob("*.csv")) +
                                           list(reason_dir.glob("*.json")))
    return out


# ---------------------------------------------------------------------------
# Lineage (merge, split, rename) — applied at analysis time, never to raw data
# ---------------------------------------------------------------------------

def apply_lineage(long_df: pd.DataFrame, mapping: dict[str, list[str]],
                  known_ids: set[str], mode: str) -> pd.DataFrame:
    """Resolve historical item ids against the current catalog.

    mapping: {old_id -> [successor_id, ...]} (one successor = merge/rename;
             many successors = a split, where each child inherits the votes).

    strict  : answers about ids no longer in the catalog are dropped.
    inherit : each old id is re-labeled to its successor(s). For a split, the
              old item's slot is duplicated so every child inherits the parent's
              comparisons; explode.py then suppresses any within-screen pair
              between two items that share an ancestor (no phantom child-vs-child).
    """
    if mode not in ("strict", "inherit"):
        raise ValueError(f"lineage mode must be 'strict' or 'inherit', got {mode!r}")
    df = long_df.copy()
    df["ancestor"] = df["item_id"]  # provenance for phantom-pair suppression

    if mode == "inherit" and mapping:
        expanded = []
        for _, row in df.iterrows():
            successors = mapping.get(row["item_id"])
            if successors is None:
                expanded.append(row.to_dict())
            else:
                for succ in successors:
                    nr = row.to_dict()
                    nr["item_id"] = succ
                    nr["ancestor"] = row["item_id"]  # all children share the ancestor
                    expanded.append(nr)
        df = pd.DataFrame(expanded, columns=list(df.columns))
        # A merge can collapse two cards in one screen onto the same successor;
        # keep the most informative pick and drop the duplicate slot.
        rank = {"best": 0, "worst": 0, "middle": 1, "skipped": 1}
        df["_r"] = df["pick"].map(rank)
        df = (df.sort_values("_r")
                .drop_duplicates(["email", "session_id", "set_index", "item_id"])
                .drop(columns="_r"))

    return df[df["item_id"].isin(known_ids)].reset_index(drop=True)
