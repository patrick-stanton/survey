import numpy as np
import pandas as pd
import pytest

from ucsurvey.explode import exploded_pairs, sets_per_respondent
from ucsurvey.profiles import p1_counts, p2_copeland, p3_bradley_terry


def long_row(email, sess, idx, item, pick, skipped=False):
    return {"email": email, "name": email, "role": "r", "organization": "o",
            "familiarity": 3, "session_id": sess, "set_index": idx,
            "item_id": item, "pick": pick, "skipped": skipped,
            "response_ms": 3000, "answered_at": ""}


def make_long(sets):
    """sets: list of (email, sess, idx, shown, best, worst) — best/worst None = skipped."""
    rows = []
    for email, sess, idx, shown, best, worst in sets:
        for item in shown:
            if best is None:
                rows.append(long_row(email, sess, idx, item, "skipped", True))
            else:
                pick = "best" if item == best else "worst" if item == worst else "middle"
                rows.append(long_row(email, sess, idx, item, pick))
    return pd.DataFrame(rows)


def test_explosion_yields_exactly_2k_minus_3_pairs():
    long_df = make_long([("a@x", "s1", 0, ["A", "B", "C", "D"], "A", "D")])
    pairs = exploded_pairs(long_df)
    got = set(zip(pairs["winner"], pairs["loser"]))
    # best A beats B,C,D; middles B,C beat worst D  ->  2*4-3 = 5 pairs
    assert got == {("A", "B"), ("A", "C"), ("A", "D"), ("B", "D"), ("C", "D")}


def test_explosion_ignores_skipped_sets():
    long_df = make_long([("a@x", "s1", 0, ["A", "B", "C", "D"], None, None)])
    assert exploded_pairs(long_df).empty


def test_p1_hand_computed_fixture():
    # Respondent 1: A best twice, D worst twice (2 screens).
    # Respondent 2: one screen, B best, A worst.
    long_df = make_long([
        ("r1@x", "s1", 0, ["A", "B", "C", "D"], "A", "D"),
        ("r1@x", "s1", 1, ["A", "B", "C", "D"], "A", "D"),
        ("r2@x", "s2", 0, ["A", "B", "C", "D"], "B", "A"),
    ])
    scores = p1_counts.scores(long_df, ["A", "B", "C", "D"])
    # A: r1 gives (2-0)/2 = 1, r2 gives (0-1)/1 = -1 -> mean 0 -> 50 rescaled
    assert scores["A"] == pytest.approx(50.0)
    # B: r1 (0-0)/2 = 0, r2 (1-0)/1 = 1 -> mean .5 -> 75
    assert scores["B"] == pytest.approx(75.0)
    # D: r1 (0-2)/2 = -1, r2 0 -> mean -.5 -> 25
    assert scores["D"] == pytest.approx(25.0)
    ranks = p1_counts.ranks(scores)
    assert ranks["B"] == 1 and ranks["D"] == 4


def test_p1_partial_sessions_do_not_bias():
    # Heavy responder loves A; light responder hates A. Equal weight per person.
    sets = [("heavy@x", "s1", i, ["A", "B", "C", "D"], "A", "B") for i in range(20)]
    sets.append(("light@x", "s2", 0, ["A", "B", "C", "D"], "B", "A"))
    scores = p1_counts.scores(make_long(sets), ["A", "B", "C", "D"])
    assert scores["A"] == pytest.approx(50.0)  # (+1 and -1) / 2 respondents


def test_copeland_fixture_with_majority():
    long_df = make_long([
        ("r1@x", "s1", 0, ["A", "B", "C", "D"], "A", "D"),
        ("r2@x", "s2", 0, ["A", "B", "C", "D"], "A", "D"),
        ("r3@x", "s3", 0, ["A", "B", "C", "D"], "B", "C"),
    ])
    pairs = exploded_pairs(long_df)
    out = p2_copeland.scores_and_ranks(pairs, ["A", "B", "C", "D"])
    assert out.loc["A", "copeland"] == 3   # beats everyone by majority
    assert out.loc["A", "rank"] == 1
    assert out.loc["D", "copeland"] == -3  # loses to everyone


def test_bradley_terry_mm_matches_choix():
    choix = pytest.importorskip("choix")
    rng = np.random.default_rng(42)
    true = np.array([2.0, 1.2, 0.6, 0.1, -0.5, -1.1, -1.6, -2.0])
    items = [f"I{i}" for i in range(8)]
    rows = []
    for _ in range(600):
        i, j = rng.choice(8, size=2, replace=False)
        p = 1 / (1 + np.exp(true[j] - true[i]))
        w, l = (i, j) if rng.random() < p else (j, i)
        rows.append({"email": "x@x", "session_id": "s", "set_index": len(rows),
                     "winner": items[w], "loser": items[l]})
    pairs = pd.DataFrame(rows)

    ours = p3_bradley_terry.fit_mm(
        p2_copeland.win_matrix(pairs, items), alpha=0.05)
    theirs = np.exp(choix.ilsr_pairwise(
        8, [(int(r["winner"][1]), int(r["loser"][1])) for _, r in pairs.iterrows()],
        alpha=0.05))
    theirs /= theirs.sum()
    # same likelihood, slightly different regularization formulations ->
    # near-identical shares and identical rankings
    assert np.abs(ours - theirs).max() < 0.02
    assert list(np.argsort(-ours)) == list(np.argsort(-theirs))


def test_bradley_terry_recovers_known_order():
    rng = np.random.default_rng(7)
    items = [f"I{i}" for i in range(10)]
    true = {item: 1.5 - 0.3 * i for i, item in enumerate(items)}
    rows = []
    for n in range(800):
        i, j = rng.choice(10, size=2, replace=False)
        p = 1 / (1 + np.exp(true[items[j]] - true[items[i]]))
        w, l = (i, j) if rng.random() < p else (j, i)
        rows.append({"email": "x@x", "session_id": "s", "set_index": n,
                     "winner": items[w], "loser": items[l]})
    shares = p3_bradley_terry.fit(pd.DataFrame(rows), items, alpha=0.05)
    recovered = list(shares.sort_values(ascending=False).index)
    # adjacent items differ by only 0.3 utils, so allow local swaps but
    # demand near-perfect rank correlation with the truth
    rho = pd.Series(range(10), index=items).corr(
        pd.Series(range(10), index=recovered), method="spearman")
    assert rho > 0.95
    assert recovered[0] == items[0] and recovered[-1] == items[-1]


def test_bt_regularization_handles_disconnected_graph():
    # Two islands never compared: without alpha the MLE would not exist.
    long_df = make_long([
        ("r1@x", "s1", 0, ["A", "B", "C", "D"], "A", "D"),
        ("r2@x", "s2", 0, ["E", "F", "G", "H"], "E", "H"),
    ])
    items = list("ABCDEFGH")
    pairs = exploded_pairs(long_df)
    assert p3_bradley_terry.connectivity_report(pairs, items) == 2
    shares = p3_bradley_terry.fit(pairs, items, alpha=0.05)
    assert np.isfinite(shares.to_numpy()).all()
    assert shares["A"] > shares["D"] and shares["E"] > shares["H"]


def test_equalized_weights_flatten_heavy_contributors():
    sets = [("heavy@x", "s1", i, ["A", "B", "C", "D"], "A", "D") for i in range(30)]
    sets += [("light@x", "s2", 0, ["A", "B", "C", "D"], "B", "A")]
    long_df = make_long(sets)
    pairs = exploded_pairs(long_df)
    spr = sets_per_respondent(long_df)
    assert spr["heavy@x"] == 30 and spr["light@x"] == 1
    pooled = p3_bradley_terry.fit(pairs, ["A", "B", "C", "D"], 0.05)
    weights = p3_bradley_terry.equalized_weights(pairs, spr)
    equal = p3_bradley_terry.fit(pairs, ["A", "B", "C", "D"], 0.05, weights=weights)
    # pooled: heavy's 30 screens swamp light -> A far ahead of B.
    assert pooled["A"] > pooled["B"]
    # equalized: light's opposite view counts as one full person.
    assert equal["A"] - equal["B"] < pooled["A"] - pooled["B"]
