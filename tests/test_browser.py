"""Drives the built survey in a real headless Chromium via Playwright:
completes the metadata form, answers screens (including a skip and an
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
        page.select_option("#fRole", index=1)
        page.select_option("#fOrg", index=1)
        page.locator("#famRow button").nth(3).click()
        page.locator("#metaNext").click()

        # choose the short arm (first budget button)
        page.locator("#budgetButtons .btn").first.click()

        # answer 3 screens, skip 1, then exit early
        for i in range(3):
            answer_screen(page, best_pos=i % 4, worst_pos=(i + 2) % 4)
        page.locator("#skipBtn").click()
        page.locator("#exitBtn").click()

        with page.expect_download() as dl:
            page.locator("#downloadBtn").click()
        path = tmp_path / dl.value.suggested_filename
        dl.value.save_as(path)
        page_code = page.evaluate("buildCompactCode()")
        browser.close()

    result = json.loads(path.read_text())
    assert result["tool"] == "ucsurvey"
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

    # The page's emailable compact code must decode to the same answers
    from ucsurvey import compact
    decoded = compact.decode(page_code, payload)
    assert [(s["best"], s["worst"], s["skipped"]) for s in decoded["sets"]] == \
           [(s["best"], s["worst"], s["skipped"]) for s in result["sets"]]


def test_resume_after_abort(survey_html):
    with pw.sync_playwright() as p:
        browser = launch_chromium(p)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(survey_html.as_uri())
        page.locator("#startBtn").click()
        page.fill("#fName", "Abort Tester")
        page.fill("#fEmail", "abort@example.com")
        page.select_option("#fRole", index=2)
        page.select_option("#fOrg", index=2)
        page.locator("#famRow button").nth(2).click()
        page.locator("#metaNext").click()
        page.locator("#budgetButtons .btn").first.click()
        answer_screen(page)
        answer_screen(page)
        # simulate a crash: navigate away without downloading
        page.goto("about:blank")

        page.goto(survey_html.as_uri())  # same browser profile -> localStorage
        resume = page.locator("#resumeBtn")
        assert resume.is_visible()
        resume.click()
        # continues at screen 3 of the same session
        assert "Screen 3" in page.locator("#taskCount").inner_text()
        browser.close()
