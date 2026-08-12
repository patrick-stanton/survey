# Use-Case Prioritization Survey

Extract a defensible prioritization of 50–70 use cases from your stakeholders —
asynchronously, through a web survey that needs **no server**, and pipe the
results back into your Cameo model as CSV.

```
Cameo model ──CSV──► build_survey.py ──► survey.html ──► respondents (10–60 min each)
                                                              │  results .csv files
Cameo model ◄─rank─ resolve.py ◄── data/archive/active/ ◄── ingest.py ◄── survey_inbox/
```

- The survey is **one self-contained HTML file**. Drop it on SharePoint or email
  it (zipped). It runs entirely in the respondent's browser — no network, no
  install — and produces a **legible results CSV** they send back.
- Respondents pick a time budget (~10 min or ~30–60 min) and can **quit at any
  time**: every answered screen is kept and used.
- Results pool across days and weeks: ingest 5 interviews today and 10
  tomorrow; `resolve.py` always recomputes from everything collected so far.
- **Bad data is removable** after the fact (`exclude.py`, never deletes), and a
  **changing use-case list** is handled by stable ids + guided reconciliation.
  See [docs/DATA_MODEL.md](docs/DATA_MODEL.md).
- Five aggregation profiles, from hand-checkable counting to Bayesian
  intervals, with group-agreement diagnostics. See [METHODOLOGY.md](METHODOLOGY.md).
- Cameo gets **only the rank** (`cameo_import.csv`); the full detail lives in the
  enriched CSV and a shareable **web dashboard** (`report.html`).

## Setup (once)

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

**Windows, no command line**: the `windows/` folder has double-clickable
wrappers — `1_build_survey.bat`, `2_pull_email.bat`, `3_ingest.bat`,
`4_resolve.bat` — that run the whole workflow in order. They need Python
installed (python.org installer or an approved Anaconda; no admin rights
required with the "just for me" install option).

If your network blocks some packages: the pipeline runs on just
`numpy pandas PyYAML`; installing `choix` and `scipy` unlocks the Bayesian
profile (P4) and richer diagnostics, but every core result works without them.

## The five-step workflow

### 1. Export use cases from Cameo → `data/use_cases.csv`

Start from the tracked example (your real catalog is gitignored so it can never
be committed by accident):

```bash
cp data/use_cases.sample.csv data/use_cases.csv
```

then replace its rows with your Cameo export. The CSV needs a `name` column;
`description`, `category`, `id`, and `supersedes` are understood when present.
**Every other column is passed through untouched** and comes back in the
enriched output, so your stereotype can evolve freely.

In Cameo 2026x (same steps in 2024x):

1. Create a **Generic Table** scoped to your stereotyped use-case elements
   (right-click a package ▸ Create Diagram ▸ Generic Table; set the Element
   Type to your stereotype).
2. **Columns ▸ Select Columns**: include Name, your `surveyId` tag (see step 2
   if you don't have one yet), documentation/description, and your category tag.
3. In the table toolbar choose **Excel/CSV Sync ▸ Sync Options**: link
   `data/use_cases.csv`, comma delimiter, "First Row Contains Headings" ✔,
   "Sync Plain Text" ✔, and — important — leave the deletion policy at
   **"Mark as obsolete"** (never "Delete elements from the model", so a CSV
   that omits rows can never delete model content).
4. **Write To File** → you have your CSV.

### 2. Build the survey

```bash
python build_survey.py
```

- If your use cases had no `id`, stable ids (`UC-001`…) are minted and written
  to `data/use_cases_with_ids.csv`. **Paste them into a `surveyId` String tag
  on your stereotype once** (generic table sync makes this a copy-paste), so
  every future export carries them. These ids — not names, which get reworded —
  are what lets responses, re-surveys, and Cameo re-imports line up.
- Output: `dist/survey.html` and `dist/survey.zip` (~40 KB).
- Edit `config.yaml` to change the title, intro text, return email, or
  time-budget arms, then rebuild.

**Distribute the `.zip` or a SharePoint/OneDrive link** — many Outlook/M365
tenants block bare `.html` attachments as phishing suspects.

### 3. Respondents take the survey — and send back a CSV

Before building, set `survey.return_email` in `config.yaml` to the address where
results should land (yours, or a dedicated mailbox for the effort).

Respondents open `survey.html`, fill in their name and email, pick a time budget,
and answer best/worst screens. When they finish — or stop early — they get a
**legible results CSV**: the big **Send Your Results** button opens a
pre-addressed draft with the CSV pasted in the body (and downloads the file so
they can attach it) so they just press Send; **Download results file** saves it
directly. The CSV carries an embedded checksum (catches corruption); its
integrity against fabrication is enforced at ingest (see [SECURITY.md](SECURITY.md)).

### 4. Collect the CSVs into a folder and ingest

The tool is **folder-based**: however results arrive, gather them into
`data/survey_inbox/`. Options:

- **Manual (simplest, most resilient):** save the CSV attachments (or the whole
  email as `.txt`) into `data/survey_inbox/`. You can inspect or remove any file.
- **Automatic email pull:** fill in the `email_pull` section of `config.yaml` and
  run `python pull_email.py` (IMAP; password prompted, never stored). Some O365
  tenants disable IMAP — then use the manual path.

Then:

```bash
python ingest.py                          # validate everything in survey_inbox/
python ingest.py --roster data/roster.txt # optional: only accept invited emails
```

Each file is validated (schema, checksum) **and re-checked against the design it
claims to come from** (fabricated screens are rejected), then stored in
`data/archive/active/`. A re-submission may only ADD screens — it can never
overwrite recorded picks. Run it as often as you like.

### 5. Resolve, then import the ranking into Cameo

```bash
python resolve.py            # full run (bootstrap intervals)
python resolve.py --fast     # quick look while data is still arriving
```

Outputs in `data/out/`:

- **`cameo_import.csv`** — the file for Cameo: `surveyId`, `rank`, `n_respondents`.
  The model stays clean; the ranking is the decision.
- **`report.html`** — a shareable, self-contained **dashboard**: the full ranking
  with confidence bars, method comparison, role/organization lenses, contested
  items, quality and coverage. Hand it to anyone for the deep dive.
- **`use_cases_enriched.csv`** — your catalog plus every score, rank, interval,
  and flag (for your own analysis).
- **`resolve_report.txt`** — the same detail in plain text.

Import into Cameo: show a `rank` tag as a column on your stereotype's generic
table, link `data/out/cameo_import.csv` in Excel/CSV Sync, set **Identification
Property = `surveyId`** (never Name), deletion policy **Mark as obsolete**, and
click **Read From File**. Save the map once and future refreshes are one click.

## Removing bad data & handling a changing use-case list

These are covered in depth in **[docs/DATA_MODEL.md](docs/DATA_MODEL.md)**. In brief:

```bash
python exclude.py --list                              # audit the archive
python exclude.py --before 2026-07-01 --reason bad-link   # quarantine (never deletes)
python reconcile.py                                   # map renamed/split/merged use cases
```

`surveyId` is the permanent anchor: keep ids stable and votes carry across
rewordings automatically. When you split/merge/drop use cases, `reconcile.py`
walks you through each change once and remembers it; splits carry the parent's
priority to every child. `resolve` refuses to run on unmapped changes so real
data is never silently dropped.

## Project layout

```
config.yaml            survey + analysis configuration (commented)
build_survey.py        catalog + config → dist/survey.html (+ version snapshot)
pull_email.py          your mailbox → data/survey_inbox/  (optional IMAP)
ingest.py              survey_inbox → data/archive/active/  (validate + re-derive)
exclude.py             quarantine suspect responses (never deletes)
reconcile.py           interactively map retired use cases to current ones
resolve.py             archive → cameo_import.csv + report.html + enriched CSV
demo.py                one-command end-to-end demo on simulated data
ucsurvey/              the library behind the scripts
template/              the survey app template
windows/               double-click .bat wrappers
data/                  catalog, survey_inbox, archive, out, lineage, snapshots
tests/                 unit + end-to-end suite (pytest)
```

## Verifying the pipeline

See the whole loop in one command (simulated data, ~30 s):

```bash
python demo.py
```

Run the test suite (incl. adversarial security, split-carryover, and
retroactive-exclusion end-to-end tests):

```bash
pip install pytest && python -m pytest tests/
```

The end-to-end test simulates a population with a *known* correct priority
order — including people who quit early and one random clicker — pushes their
files through the real scripts, and asserts the truth is recovered and the
clicker flagged. Browser tests (optional, need `playwright`) drive the real
survey in headless Chromium, including an early exit and the download.

Full hands-on and edge-case checklist: [MANUAL_TESTS.md](MANUAL_TESTS.md).
Security posture and threat model: [SECURITY.md](SECURITY.md).
