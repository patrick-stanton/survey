"""Seeded random number generation, bit-identical to the survey's JavaScript.

The browser derives each respondent's personal survey layout from a string
seed (their email + session id). For tests and the end-to-end simulation to
reproduce exactly what a browser would show, Python must generate the same
random streams. These are ports of two small, widely used public-domain
functions (xmur3 string hash + mulberry32 PRNG); tests/test_js_parity.py
verifies bit-for-bit agreement against Node.
"""

M32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & M32


def xmur3(seed_str: str):
    """Hash a string into a stream of 32-bit seeds (call the result repeatedly)."""
    h = (1779033703 ^ len(seed_str)) & M32
    for ch in seed_str:
        h = _imul(h ^ ord(ch), 3432918353)
        h = ((h << 13) | (h >> 19)) & M32

    def next_seed() -> int:
        nonlocal h
        h = _imul(h ^ (h >> 16), 2246822507)
        h = _imul(h ^ (h >> 13), 3266489909)
        h = (h ^ (h >> 16)) & M32
        return h

    return next_seed


def mulberry32(a: int):
    """32-bit PRNG returning floats in [0, 1). Same stream as the JS version."""
    a &= M32

    def next_float() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & M32
        t = _imul(a ^ (a >> 15), (1 | a) & M32)
        t = ((t + _imul(t ^ (t >> 7), (61 | t) & M32)) ^ t) & M32
        return ((t ^ (t >> 14)) & M32) / 4294967296

    return next_float


def seeded_rng(seed_str: str):
    """Convenience: string seed -> float PRNG (the composition the app uses)."""
    return mulberry32(xmur3(seed_str)())


def shuffled(items, rand) -> list:
    """Fisher-Yates shuffle (copy), consuming rand identically to the JS."""
    arr = list(items)
    for i in range(len(arr) - 1, 0, -1):
        j = int(rand() * (i + 1))
        arr[i], arr[j] = arr[j], arr[i]
    return arr
