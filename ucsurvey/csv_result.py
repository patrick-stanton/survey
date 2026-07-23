"""The respondent-facing results format: one human-readable CSV per person.

The survey writes this CSV; the respondent sends it back (email attachment,
SharePoint upload, or a shared folder); ingest.py reads it. It is deliberately
legible — you can open it in Excel and read exactly what someone answered —
unlike an encoded blob.

Layout (a key/value preamble, then a screen table, then a checksum line):

    ucsurvey_csv,1
    email,alice@example.com
    name,Alice Smith
    role,Operator
    organization,Org A
    familiarity,4
    arm,short
    session_id,s1a2b3
    extra_blocks,0
    catalog_version,3761c8c7d35f0c0b
    started_at,2026-07-23T11:00:00Z
    exported_at,2026-07-23T11:06:00Z
    screen,shown,most_important,least_important,skipped,seconds
    0,UC-005|UC-012|UC-033|UC-041,UC-005,UC-041,false,7.2
    1,UC-002|UC-019|UC-041|UC-055,UC-041,UC-002,false,5.1
    checksum,9f86d081884c7d65...

ON THE CHECKSUM — read honestly: it is a corruption detector, NOT tamper-proof.
The survey that computes it runs on the respondent's own machine, so a
determined editor could recompute it. It catches accidental damage (Excel
re-saving, truncation, encoding) and casual edits. Real integrity comes from
re-deriving each respondent's expected screens at ingest (fabrication can't
pass) plus the roster and retroactive exclusion — see SECURITY.md.
"""

from __future__ import annotations

import csv
import hashlib
import io

FORMAT_VERSION = 1
PREAMBLE_FIELDS = [
    ("email", "e"), ("name", "n"), ("role", "r"), ("organization", "o"),
    ("familiarity", "f"), ("arm", "a"), ("session_id", "s"),
    ("extra_blocks", "x"), ("catalog_version", "h"),
    ("started_at", "t"), ("exported_at", "d"),
]
TABLE_HEADER = ["screen", "shown", "most_important", "least_important", "skipped", "seconds"]


class CsvResultError(ValueError):
    pass


def checksum(lines: list[str]) -> str:
    """SHA-256 over the content lines joined by newlines (mirrored in JS)."""
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def build_csv(result: dict) -> str:
    """Full result dict -> the CSV text a respondent sends back."""
    r = result["respondent"]
    values = {
        "email": r["email"], "name": r["name"], "role": r["role"],
        "organization": r["organization"], "familiarity": r["familiarity"],
        "arm": result["arm"], "session_id": result["sessionId"],
        "extra_blocks": result.get("extraBlocks", 0),
        "catalog_version": result["catalogVersionHash"],
        "started_at": result.get("startedAt", ""),
        "exported_at": result.get("exportedAt", ""),
    }
    lines = [f"ucsurvey_csv,{FORMAT_VERSION}"]
    for key, _ in PREAMBLE_FIELDS:
        lines.append(f"{key},{_csv_cell(values[key])}")
    lines.append(",".join(TABLE_HEADER))
    for s in result["sets"]:
        lines.append(",".join([
            str(s["index"]),
            "|".join(s["shown"]),
            "" if s["skipped"] else s["best"],
            "" if s["skipped"] else s["worst"],
            "true" if s["skipped"] else "false",
            f"{(s.get('responseMs') or 0) / 1000:.1f}",
        ]))
    return "\n".join(lines) + "\n" + f"checksum,{checksum(lines)}\n"


def _csv_cell(value) -> str:
    """Minimal CSV quoting matching the JS side (only when needed)."""
    text = str(value)
    if any(c in text for c in [",", '"', "\n"]):
        return '"' + text.replace('"', '""') + '"'
    return text


def parse_csv(text: str) -> dict:
    """CSV text -> result dict. Verifies the checksum; raises on malformed input.

    Returns the dict with an extra key ``checksumOk`` (False if the embedded
    checksum did not match — the caller decides whether to warn or reject).
    """
    raw_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [ln for ln in raw_lines if ln.strip() != ""]
    if not lines or not lines[0].startswith("ucsurvey_csv"):
        raise CsvResultError("not a ucsurvey results CSV")

    checksum_line = None
    content = []
    for ln in lines:
        if ln.startswith("checksum,"):
            checksum_line = ln.split(",", 1)[1].strip()
            break
        content.append(ln)
    checksum_ok = checksum_line is not None and checksum(content) == checksum_line

    rows = list(csv.reader(content))
    preamble = {}
    table_start = None
    for i, row in enumerate(rows):
        if row and row[0] == "screen":
            table_start = i
            break
        if len(row) >= 2:
            preamble[row[0]] = row[1]
    if table_start is None:
        raise CsvResultError("missing the 'screen,...' table header")

    for key, _ in PREAMBLE_FIELDS:
        if key not in preamble:
            raise CsvResultError(f"missing '{key}' in the CSV preamble")

    sets = []
    for row in rows[table_start + 1:]:
        if not row or not row[0].strip():
            continue
        if len(row) < len(TABLE_HEADER):
            raise CsvResultError(f"screen row has too few columns: {row}")
        try:
            index = int(row[0])
        except ValueError:
            raise CsvResultError(f"screen index is not a number: {row[0]!r}")
        shown = [s for s in row[1].split("|") if s]
        skipped = row[4].strip().lower() in ("true", "1", "yes")
        try:
            response_ms = int(round(float(row[5] or 0) * 1000))
        except ValueError:
            response_ms = 0
        sets.append({
            "index": index, "shown": shown,
            "best": None if skipped else (row[2] or None),
            "worst": None if skipped else (row[3] or None),
            "skipped": skipped, "answeredAt": "", "responseMs": response_ms,
        })

    try:
        familiarity = int(preamble["familiarity"])
    except ValueError:
        familiarity = preamble["familiarity"]
    try:
        extra_blocks = int(preamble["extra_blocks"])
    except ValueError:
        extra_blocks = 0

    return {
        "schemaVersion": 1, "tool": "ucsurvey",
        "sessionId": preamble["session_id"],
        "respondent": {
            "name": preamble["name"], "email": preamble["email"].lower(),
            "role": preamble["role"], "organization": preamble["organization"],
            "familiarity": familiarity,
        },
        "catalogVersionHash": preamble["catalog_version"],
        "arm": preamble["arm"], "extraBlocks": extra_blocks,
        "designSeed": preamble["email"].lower() + "|" + preamble["session_id"],
        "startedAt": preamble.get("started_at", ""),
        "exportedAt": preamble.get("exported_at", ""),
        "sets": sets, "checksumOk": checksum_ok, "fromCsv": True,
    }


def find_csv_blocks(text: str) -> list[str]:
    """Extract ucsurvey CSV blocks from a larger text (e.g. an email body).

    A block runs from a line starting 'ucsurvey_csv' through its 'checksum,'
    line. Lets ingest read results pasted into an email body, not only files.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks, current = [], None
    for ln in lines:
        if ln.startswith("ucsurvey_csv"):
            current = [ln]
        elif current is not None:
            current.append(ln)
            if ln.startswith("checksum,"):
                blocks.append("\n".join(current) + "\n")
                current = None
    return blocks
