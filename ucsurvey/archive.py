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


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _clean_text(value, field_name: str, max_len: int = 200) -> str:
    """A respondent free-text field, guaranteed printable and bounded.

    Rejects control/escape characters (block terminal-escape and CSV/formula
    tricks in the report) and over-long values. Returns the trimmed string.
    """
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
    """Raise ResponseError if this response file can't be trusted.

    Response files are UNTRUSTED INPUT (anyone can email one), so every branch
    below turns a malformed or hostile value into a clean ResponseError rather
    than letting a TypeError/KeyError escape and abort the whole ingest batch.
    It also rejects values that could misbehave downstream: path characters in
    identifiers (archive filenames), control characters in free text (terminal
    escapes / CSV-formula tricks in the report), over-wide screens (which would
    let one respondent inject a full ordering), and absurd counts.
    """
    if not isinstance(data, dict):
        raise ResponseError("top-level JSON is not an object")
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

    # Free-text respondent fields: printable, bounded, control-char free.
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
            f"catalog version mismatch: response was collected against catalog "
            f"{h}, current is {catalog_hash}. If the older wording is still "
            f"comparable, re-run with --allow-catalog {h}"
        )

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
            raise ResponseError(f"duplicate set index {s['index']} within file")
        seen_idx.add(s["index"])
        # Bound screen width: a hand-crafted wide screen would explode into a
        # whole self-consistent ordering and dominate the pooled models.
        if items_per_screen is not None and len(s["shown"]) > items_per_screen:
            raise ResponseError(
                f"set {s['index']} shows {len(s['shown'])} items; the design "
                f"uses {items_per_screen} — not a genuine survey screen")
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


def _slug(email: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", email.lower()).strip("-")[:80]


def archive_filename(data: dict) -> str:
    # Both parts are re-sanitized here (defense in depth — validation already
    # rejects hostile sessionIds) so this can never emit path separators.
    session = re.sub(r"[^A-Za-z0-9._-]+", "-", str(data["sessionId"]))[:64]
    return f"{_slug(data['respondent']['email'])}__{session}.json"


def _same_screen(a: dict, b: dict) -> bool:
    """True if two set records show the same items and the same picks."""
    return (a.get("shown") == b.get("shown") and a.get("best") == b.get("best")
            and a.get("worst") == b.get("worst")
            and bool(a.get("skipped")) == bool(b.get("skipped")))


def ingest_file(src: Path, archive_dir: Path, catalog_hash: str,
                known_ids: set[str], report: IngestReport,
                allow_hashes: set[str] = frozenset(),
                items_per_screen: int | None = None,
                roster: set[str] | None = None) -> None:
    """Validate one returned file and add/replace it in the archive.

    Any unexpected error is turned into a REJECTED entry for THIS file so a
    single malformed or hostile file can never abort the whole ingest batch.
    """
    try:
        if Path(src).stat().st_size > 5_000_000:
            report.rejected.append(
                (src.name, "over 5 MB — real result files are a few KB"))
            return
        data = json.loads(Path(src).read_text(encoding="utf-8"))
        validate_response(data, catalog_hash, known_ids, allow_hashes,
                          items_per_screen=items_per_screen)
        if roster is not None:
            email = str(data["respondent"]["email"]).strip().lower()
            if email not in roster:
                report.rejected.append(
                    (src.name, f"respondent '{email}' is not on the invited "
                               "roster (--roster) — possible fabricated identity"))
                return
    except (json.JSONDecodeError, ResponseError) as exc:
        report.rejected.append((src.name, str(exc)))
        return
    except RecursionError:
        report.rejected.append((src.name, "JSON nested too deeply"))
        return
    except Exception as exc:  # never let one file crash the batch
        report.rejected.append((src.name, f"unreadable ({type(exc).__name__}: {exc})"))
        return

    dest = archive_dir / archive_filename(data)
    if dest.exists():
        try:
            old = json.loads(dest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            report.rejected.append((src.name, f"archived copy unreadable: {exc}"))
            return
        if len(data["sets"]) < len(old["sets"]):
            report.rejected.append(
                (src.name, f"older than archived copy ({len(data['sets'])} < "
                           f"{len(old['sets'])} screens) — keeping the archive version")
            )
            return
        # A genuine re-export only APPENDS screens; the overlap must be
        # identical. A file that changes already-recorded picks is rejected,
        # so nobody can overwrite an existing session with different answers.
        old_by_index = {s["index"]: s for s in old["sets"]}
        for s in data["sets"]:
            prior = old_by_index.get(s["index"])
            if prior is not None and not _same_screen(s, prior):
                report.rejected.append(
                    (src.name, f"screen {s['index']} differs from the archived "
                               "copy for this session — not an append-only "
                               "re-export; keeping the original"))
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
