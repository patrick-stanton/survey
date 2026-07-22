"""Bit-for-bit parity between the survey's JavaScript RNG/design derivation
and the Python mirror in ucsurvey. If these ever diverge, the end-to-end
simulation would no longer prove anything about real browser sessions.

Skipped automatically when Node.js is not installed (it is a dev-only check;
the shipped pipeline never needs Node).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ucsurvey import design
from ucsurvey.rng import seeded_rng, shuffled

TEMPLATE = Path(__file__).parent.parent / "template" / "survey_template.html"

node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def extract_parity_js() -> str:
    html = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(r"//<RNG-PARITY-START>[^\n]*\n(.*?)//<RNG-PARITY-END>", html, re.S)
    assert m, "parity markers missing from survey template"
    return m.group(1)


def run_js(snippet: str):
    out = subprocess.run(
        [node, "-e", extract_parity_js() + "\n" + snippet],
        capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(out.stdout)


def test_rng_stream_parity():
    js = run_js(
        'var r = seededRng("parity-seed-1");'
        "var out = []; for (var i=0;i<50;i++) out.push(r());"
        "console.log(JSON.stringify(out));"
    )
    r = seeded_rng("parity-seed-1")
    py = [r() for _ in range(50)]
    assert js == py  # exact float equality: both are IEEE-754 / 2^32


def test_shuffle_parity():
    items = [f"UC-{i:03d}" for i in range(1, 61)]
    js = run_js(
        f"var items = {json.dumps(items)};"
        'console.log(JSON.stringify(shuffled(items, seededRng("shuffle-seed"))));'
    )
    assert js == shuffled(items, seeded_rng("shuffle-seed"))


def test_derive_respondent_sets_parity():
    items = [f"UC-{i:03d}" for i in range(1, 61)]
    master = design.make_master(items, 3, 4, None, "parity-master", iterations=500)
    seed = "alice@example.com|s123abc"
    js = run_js(
        f"var master = {json.dumps(master)}; var items = {json.dumps(items)};"
        f"console.log(JSON.stringify(deriveRespondentSets(master, items, {json.dumps(seed)})));"
    )
    assert js == design.derive_respondent_sets(master, items, seed)
