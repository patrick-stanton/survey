#!/usr/bin/env python3
"""Build the survey: use_cases.csv + config.yaml -> dist/survey.html (+ .zip)

Usage:
    python build_survey.py                       # defaults shown below
    python build_survey.py --csv data/use_cases.csv --config config.yaml --out dist
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
import zipfile
from pathlib import Path

import yaml

from ucsurvey import catalog as cat
from ucsurvey import design
from ucsurvey.compact import design_hash

HERE = Path(__file__).parent
TEMPLATE = HERE / "template" / "survey_template.html"
MARKER = "__SURVEY_DATA__"


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_payload(df, cfg: dict) -> dict:
    survey = cfg["survey"]
    build_cfg = cfg.get("build", {})
    seed = str(build_cfg.get("seed", "ucsurvey-v1"))
    iterations = int(build_cfg.get("hill_climb_iterations", 5000))
    cat_weight = float(build_cfg.get("category_mix_weight", 0.5))
    set_size = int(survey.get("items_per_screen", 4))

    item_ids = list(df["id"])
    categories = {r["id"]: r["category"] for _, r in df.iterrows()}

    arms = {}
    for arm_key, arm_cfg in survey["arms"].items():
        exposure = int(arm_cfg["exposure"])
        master = design.make_master(
            item_ids, exposure, set_size, categories,
            f"{seed}|{arm_key}", iterations, cat_weight,
        )
        design.check_master(master, item_ids, set_size)
        arms[arm_key] = {"label": str(arm_cfg["label"]), "exposure": exposure, "master": master}

    continuation = design.make_master(
        item_ids, 1, set_size, categories, f"{seed}|continuation", iterations, cat_weight
    )
    design.check_master(continuation, item_ids, set_size)

    payload = {
        "title": str(survey.get("title", "Use Case Prioritization Survey")),
        "intro": " ".join(str(survey.get("intro", "")).split()),
        "returnEmail": str(survey.get("return_email") or "").strip(),
        "returnSubject": str(survey.get("return_subject") or "Use case survey results"),
        "roles": [str(r) for r in survey.get("roles", ["Other"])],
        "organizations": [str(o) for o in survey.get("organizations", ["Other"])],
        "catalog": [
            {"id": r["id"], "name": r["name"], "description": r["description"],
             "category": r["category"]}
            for _, r in df.iterrows()
        ],
        "catalogVersionHash": cat.catalog_hash(df),
        "arms": arms,
        "continuationMaster": continuation,
        "maxExposure": int(survey.get("max_exposure", 5)),
        "itemsPerScreen": set_size,
        "screensPerBlock": int(survey.get("screens_per_block", 12)),
        "secondsPerScreen": int(survey.get("seconds_per_screen", 22)),
        "buildSeed": seed,
        "builtAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    payload["designHash"] = design_hash(payload)
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=HERE / "data" / "use_cases.csv", type=Path)
    ap.add_argument("--config", default=HERE / "config.yaml", type=Path)
    ap.add_argument("--out", default=HERE / "dist", type=Path)
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    df = cat.load_catalog(args.csv)

    if df.attrs["minted"]:
        with_ids = args.csv.with_name(args.csv.stem + "_with_ids.csv")
        cat.write_catalog_with_ids(df, with_ids)
        print(f"NOTE: {len(df.attrs['minted'])} use cases had no id. Minted "
              f"{df.attrs['minted'][0]}..{df.attrs['minted'][-1]} and wrote {with_ids}.")
        print("      Paste these ids into the surveyId tag in Cameo (see README) so\n"
              "      future exports carry them — they are the permanent key.\n")

    payload = build_payload(df, cfg)
    if payload["returnEmail"]:
        print(f"Results will be emailed to: {payload['returnEmail']}")
    else:
        print("NOTE: survey.return_email is empty in config.yaml — the 'Email my "
              "results' button will be hidden (download-only).")

    html = TEMPLATE.read_text(encoding="utf-8")
    if MARKER not in html:
        print(f"ERROR: template {TEMPLATE} lost its {MARKER} marker.", file=sys.stderr)
        return 1
    # </ must not appear inside the inline <script> JSON block
    injected = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace(MARKER, injected).replace(
        "<title>Use Case Prioritization Survey</title>",
        f"<title>{payload['title']}</title>",
    )

    args.out.mkdir(parents=True, exist_ok=True)
    out_html = args.out / "survey.html"
    out_html.write_text(html, encoding="utf-8")
    out_zip = args.out / "survey.zip"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(out_html, "survey.html")

    n = len(df)
    print(f"Built survey for {n} use cases (catalog version {payload['catalogVersionHash']}).")
    for arm_key, arm in payload["arms"].items():
        mins = round(len(arm["master"]) * payload["secondsPerScreen"] / 60)
        print(f"  {arm_key:>6} arm: {len(arm['master'])} screens (~{mins} min), "
              f"each item shown {arm['exposure']}x")
    print(f"  keep-going blocks: +{len(payload['continuationMaster'])} screens each, "
          f"up to {payload['maxExposure']}x total exposure")
    kb = out_html.stat().st_size / 1024
    print(f"Wrote {out_html} ({kb:.0f} KB) and {out_zip}")
    print("Distribute the .zip (or a SharePoint link) — many mail systems block bare .html files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
