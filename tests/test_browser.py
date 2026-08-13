"""Drives the built survey in a real headless Chromium via Playwright:
completes the name/email form, answers screens (including a skip and an
early exit), downloads the results file, and checks its contents.

Skipped automatically when Playwright/Chromium aren't installed — this is a
dev-only check; respondents just need any browser.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api", reason="playwright not installed")

ROOT = Path(__file__).parent.parent


def launch_chromium(p):
    """Launch Playwright's Chromium, falling back to a system-provided binary
    (some environments pre-install Chromium at a fixed path instead)."""
    try:
        return p.chromium.launch()
    except Exception:
        for candidate in ("/opt/pw-browsers/chromium",
                          "/opt/pw-browsers/chromium/chrome-linux/chrome"):
            if Path(candidate).exists():
                return p.chromium.launch(executable_path=candidate)
        raise


@pytest.fixture(scope="module")
def survey_html(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [sys.executable, str(ROOT / "build_survey.py"), "--out", str(out),
         "--csv", str(ROOT / "data" / "use_cases.sample.csv")],
        check=True, capture_output=True, text=True, cwd=ROOT,
    )
    return out / "survey.html"


def mailto_url(page):
    """The draft the Send button would hand to the mail client.

    Runs the shipped doEmail with only its navigation line replaced, so what we
    inspect is the real body, not a copy of it that could drift.
    """
    return page.evaluate("""() => {
      const src = doEmail.toString()
        .replace('window.location.href = url;', 'return url;')
        .replace(/^function doEmail/, 'function _de');
      const saved = window.doDownload;
      window.doDownload = () => {};
      try { return eval('(' + src + ')')(); } finally { window.doDownload = saved; }
    }""")


def answer_screen(page, best_pos=0, worst_pos=3):
    cards = page.locator("#cards .card")
    cards.nth(best_pos).locator(".pickBest").click()
    cards.nth(worst_pos).locator(".pickWorst").click()
    page.locator("#nextBtn").click()


def test_full_short_session_with_download(survey_html, tmp_path):
    with pw.sync_playwright() as p:
        browser = launch_chromium(p)
        page = browser.new_page()
        page.goto(survey_html.as_uri())

        assert "Prioritization" in page.title()
        page.locator("#startBtn").click()

        page.fill("#fName", "Test Person")
        page.fill("#fEmail", "test.person@example.com")
        page.locator("#metaNext").click()

        # choose the short arm (first budget button)
        page.locator("#budgetButtons .btn").first.click()

        # answer 3 screens, skip 1, then exit early
        for i in range(3):
            answer_screen(page, best_pos=i % 4, worst_pos=(i + 2) % 4)
        page.locator("#skipBtn").click()
        page.locator("#exitBtn").click()

        # the finish screen leads with the big send button (return_email is
        # set in config.yaml); the copy-code button is gone
        assert page.locator("#emailBtn").is_visible()
        assert page.locator("#copyBtn").count() == 0
        # ...and it tells the respondent, unmissably, to attach the file
        assert "ATTACH" in page.locator(".attachnote").inner_text()

        # The email body carries the attach instruction and a prompt for the
        # respondent's own comments — and never the results CSV itself, which
        # travels as the attachment.
        from urllib.parse import unquote
        body = unquote(mailto_url(page))
        assert "ATTACH .CSV THAT DOWNLOADED TO EMAIL" in body
        assert "PLEASE ENTER YOUR SURVEY THOUGHTS HERE FOR OUR REVIEW" in body
        assert "ucsurvey_csv" not in body
        assert "checksum," not in body

        with page.expect_download() as dl:
            page.locator("#downloadBtn").click()
        path = tmp_path / dl.value.suggested_filename
        dl.value.save_as(path)
        browser.close()

    # The downloaded file is a legible CSV that parses and checksum-verifies.
    from ucsurvey import csv_result
    assert path.suffix == ".csv"
    result = csv_result.parse_csv(path.read_text())
    assert result["checksumOk"] is True
    assert result["respondent"]["email"] == "test.person@example.com"
    assert result["arm"] == "short"
    assert len(result["sets"]) == 4
    assert [s["skipped"] for s in result["sets"]] == [False, False, False, True]
    for s in result["sets"][:3]:
        assert s["best"] in s["shown"] and s["worst"] in s["shown"]
        assert s["best"] != s["worst"]
        assert len(set(s["shown"])) == 4

    # The browser-derived screens must equal the Python derivation (parity!)
    from ucsurvey import catalog as cat, design
    from build_survey import build_payload, load_config
    df = cat.load_catalog(ROOT / "data" / "use_cases.sample.csv")
    payload = build_payload(df, load_config(ROOT / "config.yaml"))
    expected = design.derive_respondent_sets(
        payload["arms"]["short"]["master"], [r["id"] for _, r in df.iterrows()],
        result["designSeed"],
    )
    assert [s["shown"] for s in result["sets"]] == expected[:4]
