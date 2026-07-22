"""Survey design generation: which items appear together on which screens.

Best-practice MaxDiff designs want three kinds of balance (Sawtooth/Displayr):
  1. one-way   — every item shown equally often (we guarantee within +/-1)
  2. two-way   — every pair of items co-appears about equally often
  3. positional — items appear in different on-screen positions

An exact balanced incomplete block design does not exist at arbitrary catalog
sizes, so we use the industry-standard construction: deal items round-robin
(perfect one-way balance), then hill-climb swaps to flatten pair co-occurrence,
then randomize positions. One "master" design is built per time-budget arm at
build time; each respondent's browser derives a personal variant by relabeling
items through a seeded permutation and shuffling screen order — which keeps
all balance properties and makes mid-survey aborts item-neutral.

All randomness flows through ucsurvey.rng so Python and the browser agree.
"""

from __future__ import annotations

import math

from .rng import seeded_rng, shuffled


def make_master(
    item_ids: list[str],
    exposure: int,
    set_size: int,
    categories: dict[str, str] | None,
    seed_str: str,
    iterations: int = 5000,
    category_weight: float = 0.5,
) -> list[list[str]]:
    """Build one master design: a list of screens, each a list of item ids.

    Every item appears `exposure` times (+1 for a few items when the item
    count doesn't divide evenly into full screens), never twice on a screen.
    """
    if set_size < 3:
        raise ValueError("set_size must be at least 3 for best/worst questions")
    if len(item_ids) < 2 * set_size:
        raise ValueError(
            f"Need at least {2 * set_size} items for {set_size}-item screens; "
            f"got {len(item_ids)}. A list this small is better ranked directly."
        )

    rand = seeded_rng(seed_str)
    n_sets = math.ceil(len(item_ids) * exposure / set_size)

    # Fill the last partial screen by giving one extra appearance to a few
    # randomly chosen items (keeps every screen a full set of set_size).
    slots = [item for item in item_ids for _ in range(exposure)]
    n_extra = n_sets * set_size - len(slots)
    slots += shuffled(item_ids, rand)[:n_extra]

    sets = _deal_no_repeats(slots, n_sets, set_size, rand)
    _hill_climb(sets, item_ids, categories or {}, rand, iterations, category_weight)

    for s in sets:
        s[:] = shuffled(s, rand)  # positional balance in the master
    return sets


def _deal_no_repeats(slots, n_sets, set_size, rand) -> list[list[str]]:
    """Deal shuffled slots round-robin, then repair any within-set repeats."""
    slots = shuffled(slots, rand)
    sets = [slots[i::n_sets] for i in range(n_sets)]

    for _ in range(10_000):
        dirty = [
            (si, item)
            for si, s in enumerate(sets)
            for item in {x for x in s if s.count(x) > 1}
        ]
        if not dirty:
            return sets
        si, item = dirty[0]
        # Swap one duplicate into any set that lacks `item` and can give back
        # something new to set si.
        for sj in shuffled(range(n_sets), rand):
            if sj == si or item in sets[sj]:
                continue
            give = [y for y in sets[sj] if y not in sets[si]]
            if give:
                sets[si][sets[si].index(item)] = give[0]
                sets[sj][sets[sj].index(give[0])] = item
                break
        else:  # pragma: no cover - cannot trade: reshuffle everything
            return _deal_no_repeats(shuffled(slots, rand), n_sets, set_size, rand)
    raise RuntimeError("Could not remove within-screen repeats (unexpected).")


def _hill_climb(sets, item_ids, categories, rand, iterations, category_weight):
    """Flatten pair co-occurrence (+ discourage same-category pairs) by
    accepting swaps between screens that reduce the objective:

        sum over item pairs of count^2  +  weight * (same-category co-occurrences)

    Minimizing the sum of squared pair counts is equivalent to minimizing
    their variance, since the total number of pairs is fixed.
    """
    index = {item: i for i, item in enumerate(item_ids)}
    k = len(item_ids)
    counts = [[0] * k for _ in range(k)]
    for s in sets:
        for a_pos in range(len(s)):
            for b_pos in range(a_pos + 1, len(s)):
                a, b = index[s[a_pos]], index[s[b_pos]]
                counts[a][b] += 1
                counts[b][a] += 1

    def same_cat(x, y):
        cx = categories.get(x, "")
        return cx != "" and cx == categories.get(y, "")

    def delta_side(moved_out, moved_in, others):
        """Objective change on one screen when moved_out is replaced by moved_in."""
        d = 0.0
        for o in others:
            c_out = counts[index[moved_out]][index[o]]
            c_in = counts[index[moved_in]][index[o]]
            d += (-2 * c_out + 1) + (2 * c_in + 1)  # (c-1)^2-c^2 and (c+1)^2-c^2
            d += category_weight * ((1 if same_cat(moved_in, o) else 0)
                                    - (1 if same_cat(moved_out, o) else 0))
        return d

    def apply_side(moved_out, moved_in, others, sign):
        for o in others:
            counts[index[moved_out]][index[o]] -= sign
            counts[index[o]][index[moved_out]] -= sign
            counts[index[moved_in]][index[o]] += sign
            counts[index[o]][index[moved_in]] += sign

    n_sets = len(sets)
    for _ in range(iterations):
        si = int(rand() * n_sets)
        sj = int(rand() * n_sets)
        if si == sj:
            continue
        a = sets[si][int(rand() * len(sets[si]))]
        b = sets[sj][int(rand() * len(sets[sj]))]
        if a == b or a in sets[sj] or b in sets[si]:
            continue
        others_i = [x for x in sets[si] if x != a]
        others_j = [x for x in sets[sj] if x != b]
        if delta_side(a, b, others_i) + delta_side(b, a, others_j) < 0:
            apply_side(a, b, others_i, 1)
            apply_side(b, a, others_j, 1)
            sets[si][sets[si].index(a)] = b
            sets[sj][sets[sj].index(b)] = a


def derive_respondent_sets(
    master: list[list[str]], item_ids: list[str], seed_str: str
) -> list[list[str]]:
    """A respondent's personal design: relabel items through a seeded
    permutation of the catalog, shuffle screen order, shuffle positions.

    MUST stay in lockstep with deriveRespondentSets() in the survey template —
    tests/test_js_parity.py holds them together.
    """
    rand = seeded_rng(seed_str)
    perm = shuffled(item_ids, rand)
    relabel = {item: perm[i] for i, item in enumerate(item_ids)}
    sets = [[relabel[item] for item in s] for s in master]
    sets = shuffled(sets, rand)
    return [shuffled(s, rand) for s in sets]


# ---------------------------------------------------------------------------
# Introspection helpers (tests + build-time report)
# ---------------------------------------------------------------------------

def exposure_counts(sets: list[list[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in sets:
        for item in s:
            counts[item] = counts.get(item, 0) + 1
    return counts


def cooccurrence_spread(sets: list[list[str]]) -> tuple[int, int]:
    """(min, max) co-appearance count over all item pairs that ever co-appear,
    with min reported as 0 if some pair never co-appears (typical at 1x)."""
    pairs: dict[tuple[str, str], int] = {}
    items = sorted({i for s in sets for i in s})
    for s in sets:
        ordered = sorted(s)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                pairs[(ordered[i], ordered[j])] = pairs.get((ordered[i], ordered[j]), 0) + 1
    n_possible = len(items) * (len(items) - 1) // 2
    lo = 0 if len(pairs) < n_possible else min(pairs.values())
    return lo, max(pairs.values())


def check_master(sets: list[list[str]], item_ids: list[str], set_size: int) -> None:
    """Raise if the design violates its guarantees. Run at build time."""
    for s in sets:
        if len(s) != set_size or len(set(s)) != set_size:
            raise AssertionError(f"Screen is not {set_size} distinct items: {s}")
    counts = exposure_counts(sets)
    if set(counts) != set(item_ids):
        raise AssertionError("Design does not cover exactly the catalog items.")
    if max(counts.values()) - min(counts.values()) > 1:
        raise AssertionError(f"Exposure imbalance >1: {sorted(set(counts.values()))}")

    # Connectivity: preference estimation needs one linked comparison graph.
    # At 1x exposure screens are disjoint by construction — a lone short-arm
    # respondent cannot be connected; pooling across respondents (each with a
    # different item permutation) is what connects the data, and resolve.py
    # verifies exactly that on the pooled archive before model fitting.
    if min(counts.values()) < 2:
        return
    parent = {i: i for i in item_ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s in sets:
        for other in s[1:]:
            parent[find(other)] = find(s[0])
    if len({find(i) for i in item_ids}) != 1:
        raise AssertionError("Comparison graph is not connected.")
