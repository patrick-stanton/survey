"""Synthetic respondents for the end-to-end test: simulate people with known
ground-truth priorities answering the survey exactly as a browser would
(same seeded design derivation), so we can verify the pipeline recovers the
truth from the files it will actually receive."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

from ucsurvey import design


def true_utilities(item_ids: list[str], seed: int = 99) -> dict[str, float]:
    """A hidden 'correct' priority order with evenly spaced strengths."""
    order = list(item_ids)
    random.Random(seed).shuffle(order)
    return {item: -0.12 * pos for pos, item in enumerate(order)}


def _softmax_pick(items, util, temp, rnd):
    weights = [math.exp(util[i] / temp) for i in items]
    total = sum(weights)
    x = rnd.random() * total
    for item, w in zip(items, weights):
        x -= w
        if x <= 0:
            return item
    return items[-1]


def simulate_respondent(
    payload: dict,
    email: str,
    role: str,
    org: str,
    arm: str,
    utilities: dict[str, float],
    seed: int,
    temp: float = 0.25,
    abort_after: int | None = None,
    random_clicker: bool = False,
) -> dict:
    """One result-file dict, answered under a noisy version of `utilities`."""
    rnd = random.Random(seed)
    item_ids = [it["id"] for it in payload["catalog"]]
    session_id = f"s{seed:06d}"
    design_seed = f"{email}|{session_id}"
    sets = design.derive_respondent_sets(
        payload["arms"][arm]["master"], item_ids, design_seed
    )
    if abort_after is not None:
        sets = sets[:abort_after]

    records = []
    for i, shown in enumerate(sets):
        if random_clicker:
            best = rnd.choice(shown)
            worst = rnd.choice([x for x in shown if x != best])
            ms = rnd.randint(300, 900)
        else:
            best = _softmax_pick(shown, utilities, temp, rnd)
            rest = [x for x in shown if x != best]
            worst = _softmax_pick(rest, {k: -v for k, v in utilities.items()}, temp, rnd)
            ms = rnd.randint(2500, 9000)
        records.append({
            "index": i, "shown": shown, "best": best, "worst": worst,
            "skipped": False, "answeredAt": "2026-07-22T12:00:00Z", "responseMs": ms,
        })

    return {
        "schemaVersion": 1, "tool": "ucsurvey", "sessionId": session_id,
        "respondent": {"name": email.split("@")[0], "email": email, "role": role,
                       "organization": org, "familiarity": 4},
        "catalogVersionHash": payload["catalogVersionHash"],
        "arm": arm, "designSeed": design_seed,
        "startedAt": "2026-07-22T11:00:00Z", "exportedAt": "2026-07-22T12:00:00Z",
        "plannedScreens": len(sets), "extraBlocks": 0, "sets": records,
    }


def write_inbox(files: list[dict], inbox: Path) -> None:
    """Write each simulated result as the CSV a respondent would send back."""
    from ucsurvey import csv_result
    inbox.mkdir(parents=True, exist_ok=True)
    for data in files:
        name = f"{data['respondent']['email'].replace('@', '-at-')}_{data['sessionId']}.csv"
        (inbox / name).write_text(csv_result.build_csv(data))
