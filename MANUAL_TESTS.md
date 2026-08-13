# Manual Test Checklist

Two layers of proof that the tool works and survives edge cases: the automated
suite (run it), and a hands-on checklist (do it once before a real engagement).

## 0. Fastest proof — the automated suite

```bash
pip install -r requirements.txt pytest
python -m pytest tests/ -v
```

Expect **67 passed** (a few *skip* without Node/Playwright — dev-only, harmless).
What the key tests prove:

| Test file | Proves |
|---|---|
| `test_end_to_end.py` | A population with a **known correct answer** — including early-quitters and a random-clicker — is recovered by every profile through the real scripts; a catalog **merge** works in both lineage modes; two resolves are **byte-identical** (reproducible). |
| `test_security.py` | Forged/huge codes are rejected instantly (no hang); malformed JSON becomes a clean rejection; **one bad file can't abort the batch**; mega-screen injection blocked; session tampering blocked; roster rejects uninvited emails. |
| `test_browser.py` | A real headless browser completes the survey (including a skip and an **early exit**), downloads, and the results CSV parses and checksum-verifies. |
| `test_design.py` | Every use case is shown equally often (±1); no screen repeats an item; the design is connected. |

## 1. One-command end-to-end demo (no survey-taking, ~30 s)

```bash
python demo.py
```

Simulates 16 respondents (both return formats — `.json` downloads and emailed
`UCS1` codes), ingests, resolves, and prints the Top-10 ranking with confidence
ranges. Nothing touches your real `data/`. Use this to show a colleague the whole
pipeline. **Expected:** a clean ranking prints; the random-clicker is noted in
`resolve_report.txt`; the output paths are shown at the end.

## 2. Hands-on smoke test (the real human loop, ~10 min)

Do this once end-to-end before sending to real people.

**Build**
- [ ] `cp data/use_cases.sample.csv data/use_cases.csv` (or use your real export).
- [ ] Set `survey.return_email` in `config.yaml` to a test address you control.
- [ ] `python build_survey.py` → confirm `dist/survey.html` and `dist/survey.zip` exist.

**Take it (in a browser)**
- [ ] Open `dist/survey.html`. Fill in your name and email — confirm it blocks a
      bad email and an empty name.
- [ ] Choose the ~10-min budget. Answer a few screens.
- [ ] Use keyboard keys 1–4 and Enter — confirm they pick and advance.
- [ ] Finish (or click **Exit & download**). Click the big pulsing **Send Your
      Results** button → confirm the `.csv` downloads and your mail client opens
      **pre-addressed**, with only the ATTACH instruction and a prompt for your
      thoughts in the body. **Attach the downloaded `.csv`**, then send it.
- [ ] Confirm the finish screen shows the attach warning and the exact filename.
- [ ] Also click **Download results file** → confirm a `.csv` lands in Downloads.

**Collect & resolve**
- [ ] Put the `.json` (and/or save the email as `.txt`) into `data/inbox/`.
- [ ] `python ingest.py` → confirm a `+ accepted` line and the archive summary.
- [ ] `python resolve.py --fast` → confirm `data/out/use_cases_enriched.csv` and
      `resolve_report.txt` are written.
- [ ] Open the CSV → confirm your use cases now carry `p1_rank`, `rank_low90/high90`,
      `p_top10`, `n_respondents`, etc.

**Cameo round-trip (on a throwaway copy of your model)**
- [ ] In the generic table, Excel/CSV Sync → link `use_cases_enriched.csv`,
      Identification Property = `surveyId`, deletion policy = **Mark as obsolete**.
- [ ] **Read From File** → confirm the score/rank tags populate on the right
      elements and no duplicates are created.

## 3. Edge-case checklist (prove resilience by hand)

Each of these is also an automated test; do a couple by hand to see the behavior.

- [ ] **Aborted survey still counts:** answer 3 screens, exit, ingest → the 3
      screens appear in the archive and resolve uses them.
- [ ] **Duplicate submission:** submit the same session twice → the second is
      `= already archived` (or `^ replaced` if longer), never double-counted.
- [ ] **Reworded catalog:** change a use-case description, rebuild, try to ingest
      an old result → it's rejected with an `--allow-catalog <hash>` hint.
- [ ] **Merged use cases:** add a `supersedes` entry, run `resolve.py --lineage
      inherit` vs `strict` → confirm the successor gains/loses the predecessor's data.
- [ ] **Junk file:** drop a `.json` of random text into `data/inbox/` → it's a
      clean `! REJECTED` line and the other files still ingest.
- [ ] **Uninvited respondent:** with `--roster data/roster.txt`, submit from an
      address not on the list → rejected.
