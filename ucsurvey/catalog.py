"""The CSV contract with Cameo.

Only five columns mean anything to this tool:

    id          stable survey key (minted here as UC-001... if missing)
    name        required, shown on survey screens
    description shown when the respondent expands a card
    category    optional grouping, shown as a chip + used as an analysis lens
    supersedes  optional; semicolon-separated ids of merged/renamed predecessors

Every other column is preserved untouched and re-emitted by resolve.py, so
the Cameo stereotype can evolve freely without breaking the pipeline.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd

SPECIAL_COLUMNS = ["id", "name", "description", "category", "supersedes"]


class CatalogError(ValueError):
    pass


def load_catalog(csv_path: str | Path) -> pd.DataFrame:
    """Read use_cases.csv, validate, and mint ids for rows that lack one.

    Returns a DataFrame whose columns include all SPECIAL_COLUMNS (created
    empty when absent) plus every passthrough column from the file. The
    attribute df.attrs["minted"] lists any newly minted ids.
    """
    path = Path(csv_path)
    if not path.exists():
        raise CatalogError(f"Use-case CSV not found: {path}")

    df = pd.read_csv(path, dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]

    # Accept common aliases so a raw Cameo generic-table export works as-is.
    aliases = {"surveyid": "id", "survey_id": "id", "documentation": "description"}
    df = df.rename(columns={c: aliases[c.lower()] for c in df.columns if c.lower() in aliases})
    df = df.rename(columns={c: c.lower() for c in df.columns if c.lower() in SPECIAL_COLUMNS})

    if "name" not in df.columns:
        raise CatalogError(
            f"CSV must have a 'name' column. Found columns: {list(df.columns)}"
        )
    for col in SPECIAL_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    for col in SPECIAL_COLUMNS:
        df[col] = df[col].astype(str).str.strip()

    df = df[df["name"] != ""].reset_index(drop=True)
    if len(df) == 0:
        raise CatalogError("CSV contains no rows with a non-empty name.")

    dup_names = df["name"][df["name"].duplicated()].unique()
    if len(dup_names) > 0:
        raise CatalogError(f"Duplicate use-case names: {list(dup_names)}")

    df.attrs["minted"] = _mint_missing_ids(df)

    dup_ids = df["id"][df["id"].duplicated()].unique()
    if len(dup_ids) > 0:
        raise CatalogError(f"Duplicate ids: {list(dup_ids)}")

    self_ref = [
        row["id"]
        for _, row in df.iterrows()
        if row["id"] in parse_supersedes(row["supersedes"])
    ]
    if self_ref:
        raise CatalogError(f"Items list themselves in 'supersedes': {self_ref}")

    return df


def _mint_missing_ids(df: pd.DataFrame) -> list[str]:
    """Fill empty id cells with UC-001-style ids, continuing past existing ones."""
    taken = set(df["id"]) - {""}
    numbered = [int(m.group(1)) for i in taken if (m := re.fullmatch(r"UC-(\d+)", i))]
    counter = max(numbered, default=0)
    minted = []
    for idx in df.index[df["id"] == ""]:
        counter += 1
        while f"UC-{counter:03d}" in taken:
            counter += 1
        df.at[idx, "id"] = f"UC-{counter:03d}"
        minted.append(f"UC-{counter:03d}")
    return minted


def catalog_hash(df: pd.DataFrame) -> str:
    """Fingerprint of what respondents actually see (id + wording).

    Response files carry this hash so ingest.py can tell whether old data
    was collected against different item wording. Category and passthrough
    columns are cosmetic and deliberately excluded.
    """
    lines = sorted(f"{r['id']}|{r['name']}|{r['description']}" for _, r in df.iterrows())
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()[:16]


def parse_supersedes(cell: str) -> list[str]:
    return [p.strip() for p in str(cell).split(";") if p.strip()]


def lineage_map(df: pd.DataFrame) -> dict[str, str]:
    """{predecessor id -> current successor id} from the supersedes column."""
    mapping: dict[str, str] = {}
    current = set(df["id"])
    for _, row in df.iterrows():
        for old in parse_supersedes(row["supersedes"]):
            if old in current:
                raise CatalogError(
                    f"'{row['id']}' claims to supersede '{old}', which still "
                    "exists in the catalog. Remove one or the other."
                )
            if old in mapping and mapping[old] != row["id"]:
                raise CatalogError(
                    f"'{old}' is superseded by both '{mapping[old]}' and '{row['id']}'."
                )
            mapping[old] = row["id"]
    return mapping


def write_catalog_with_ids(df: pd.DataFrame, out_path: str | Path) -> None:
    """Write the catalog back out (used when ids were minted, so the user can
    paste them into the Cameo surveyId tag once)."""
    ordered = SPECIAL_COLUMNS + [c for c in df.columns if c not in SPECIAL_COLUMNS]
    df[ordered].to_csv(out_path, index=False)
