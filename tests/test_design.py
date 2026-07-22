import pytest

from ucsurvey import design
from ucsurvey.rng import seeded_rng, shuffled

ITEMS_60 = [f"UC-{i:03d}" for i in range(1, 61)]
CATS = {item: f"cat{int(item[3:]) % 6}" for item in ITEMS_60}


@pytest.mark.parametrize("n_items,exposure", [(50, 1), (60, 1), (60, 3), (70, 3), (57, 3)])
def test_master_design_properties(n_items, exposure):
    items = ITEMS_60[:n_items] if n_items <= 60 else [f"UC-{i:03d}" for i in range(1, n_items + 1)]
    sets = design.make_master(items, exposure, 4, None, "seed-a", iterations=2000)
    design.check_master(sets, items, 4)  # raises on any violation
    counts = design.exposure_counts(sets)
    assert min(counts.values()) >= exposure
    assert max(counts.values()) <= exposure + 1


def test_hill_climb_improves_pair_balance():
    rand = seeded_rng("no-climb")
    sets_raw = design.make_master(ITEMS_60, 3, 4, None, "seed-b", iterations=0)
    sets_opt = design.make_master(ITEMS_60, 3, 4, None, "seed-b", iterations=5000)

    def sum_sq(sets):
        pairs = {}
        for s in sets:
            o = sorted(s)
            for i in range(4):
                for j in range(i + 1, 4):
                    pairs[(o[i], o[j])] = pairs.get((o[i], o[j]), 0) + 1
        return sum(v * v for v in pairs.values())

    assert sum_sq(sets_opt) < sum_sq(sets_raw)
    lo, hi = design.cooccurrence_spread(sets_opt)
    assert hi <= 3  # at 3x exposure on 60 items no pair should meet more than 3 times


def test_category_mixing_reduces_same_category_pairs():
    def same_cat_pairs(sets):
        return sum(
            1
            for s in sets
            for i in range(len(s))
            for j in range(i + 1, len(s))
            if CATS[s[i]] == CATS[s[j]]
        )

    plain = design.make_master(ITEMS_60, 3, 4, None, "seed-c", iterations=4000)
    mixed = design.make_master(ITEMS_60, 3, 4, CATS, "seed-c", iterations=4000, category_weight=0.5)
    assert same_cat_pairs(mixed) < same_cat_pairs(plain)


def test_derivation_is_deterministic_and_preserves_balance():
    master = design.make_master(ITEMS_60, 1, 4, None, "seed-d", iterations=1000)
    a = design.derive_respondent_sets(master, ITEMS_60, "alice@example.com|s1")
    b = design.derive_respondent_sets(master, ITEMS_60, "alice@example.com|s1")
    c = design.derive_respondent_sets(master, ITEMS_60, "bob@example.com|s2")
    assert a == b  # same seed, same personal design
    assert a != c  # different respondents get different layouts
    design.check_master(a, ITEMS_60, 4)


def test_seeded_shuffle_is_stable():
    # Locks the RNG stream: if this changes, browser and Python have diverged.
    rand = seeded_rng("stability-check")
    assert shuffled(list(range(8)), rand) == [3, 0, 1, 5, 6, 4, 2, 7]


def test_too_few_items_rejected():
    with pytest.raises(ValueError, match="better ranked directly"):
        design.make_master(ITEMS_60[:7], 1, 4, None, "s")
