# Use-Case Prioritization Survey

Extract a defensible prioritization of 50–70 use cases from your stakeholders —
asynchronously, through a web survey that needs **no server**, and pipe the
results back into your Cameo model as CSV.

```
Cameo model ──CSV──► build_survey.py ──► survey.html ──► respondents (10–60 min each)
                                                              │  results .json files
Cameo model ◄──CSV── resolve.py ◄── data/archive/ ◄── ingest.py
```

- The survey is **one self-contained HTML file**. Email it (zipped) or drop it
  on SharePoint. It runs entirely in the respondent's browser — no network, no
  install — and produces a small `.json` results file they send back.
- Respondents pick a time budget (~10 min or ~30–60 min) and can **quit at any
  time**: every answered screen is kept and used.
- Results pool across days and weeks: ingest 5 interviews today and 10
  tomorrow; `resolve.py` always recomputes from everything collected so far.
- Five aggregation profiles, from hand-checkable counting to Bayesian
  intervals, with group-agreement diagnostics. See [METHODOLOGY.md](METHODOLOGY.md).

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

The CSV needs a `name` column; `description`, `category`, `id`, and
`supersedes` are understood when present. **Every other column is passed
through untouched** and comes back in the enriched output, so your stereotype
can evolve freely.

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
- Edit `config.yaml` to change the title, intro text, role/organization
  dropdowns, or time-budget arms, then rebuild.

**Distribute the `.zip` or a SharePoint/OneDrive link** — many Outlook/M365
tenants block bare `.html` attachments as phishing suspects.

### 3. Respondents take the survey — and one-click email it back

Before building, set `survey.return_email` in `config.yaml` to the address
where results should land (yours, or a mailbox you create for the effort).

Respondents open `survey.html`, fill in who they are, pick a time budget, and
answer best/worst screens. Their browser saves progress after every screen
(they can close and resume). When they finish — or stop early — they click
**Email my results**: their own mail client opens a pre-addressed draft whose
body contains a short `UCS1...` results code (the whole session compressed —
no attachment to find, nothing to save), and they press Send. Fallbacks are
always visible: **Download results file** (`.json`) and **Copy results code**.

### 4. Get the results into data/inbox/ and ingest

Any mix of these works — everything funnels into the same archive:

- **Automatic**: fill in the `email_pull` section of `config.yaml` and run
  `python pull_email.py` — it connects to your mailbox over IMAP (password
  prompted, never stored), finds the survey emails, and drops their codes and
  attachments into `data/inbox/`. Some corporate O365 tenants disable IMAP;
  then use:
- **Manual, still easy**: select the result emails in Outlook and save them as
  `.txt` into `data/inbox/` (ingest reads `UCS1` codes straight out of saved
  emails), and/or drop returned `.json` files there.

Then:

```bash
python ingest.py
```

Files are validated and moved into the append-only `data/archive/`. Run it as
often as you like; re-submissions of the same session replace their older,
shorter copy, and nothing else is ever modified. If a file was collected
against an older wording of the catalog, ingest refuses it and shows the
`--allow-catalog <hash>` flag to accept it deliberately.

### 5. Resolve and re-import into Cameo

```bash
python resolve.py            # full run
python resolve.py --fast     # quick look while data is still arriving
```

Outputs in `data/out/`:

- **`use_cases_enriched.csv`** — your original CSV plus, per use case:
  `p1_score`/`p1_rank` (hand-checkable counting), `p2_copeland`/`p2_rank`
  (majority logic), `p3_bt_share`/`p3_rank` (statistical model),
  `rank_low90`/`rank_high90`/`p_top10` (how certain the rank is),
  `n_respondents`, `n_exposures`, `consensus_flag`, `last_aggregated`,
  `profiles_used`.
- **`resolve_report.txt`** — the full ranking with uncertainty, where the
  profiles disagree, how stakeholder groups (roles/organizations) agree or
  conflict, response-quality flags, and coverage warnings.

To pull the scores into Cameo: add tags for the result columns you want on
your stereotype (`Real` for scores, `Integer` for ranks, `String` for flags),
show them as columns in the same generic table, link
`data/out/use_cases_enriched.csv` in Excel/CSV Sync, set the sync's
**Identification Property to `surveyId`** (never Name — renames would create
duplicates), and click **Read From File**. Save the mapping once
(File ▸ Import From ▸ Excel/CSV File ▸ *Saving an Import Map*) and every
future refresh is one click.

## When use cases change between survey rounds

Reword freely — the catalog hash tells ingest when wording changed, and you
decide with `--allow-catalog` whether old answers still apply. When you
**merge or replace** use cases, give the successor a `supersedes` column entry
listing the old ids (`UC-004;UC-017`), then choose at resolve time:

```bash
python resolve.py --lineage strict    # current items only (default)
python resolve.py --lineage inherit   # predecessors' votes count for the successor
```

Raw archived answers are never rewritten either way — the mapping is applied
at analysis time and recorded in the outputs, which is what keeps the process
auditable.

## Project layout

```
config.yaml            survey + analysis configuration (commented)
build_survey.py        CSV + config → dist/survey.html
pull_email.py          your mailbox → data/inbox/  (optional IMAP automation)
ingest.py              returned .json/.txt results → data/archive/
resolve.py             archive → enriched CSV + report  → import into Cameo
ucsurvey/              the library behind the scripts
template/              the survey app template
windows/               double-click .bat wrappers for the four steps
data/use_cases.csv     your catalog (example included)
data/inbox|archive|out collection folders
tests/                 unit + end-to-end simulation suite (pytest)
```

## Verifying the pipeline

```bash
pip install pytest && python -m pytest tests/
```

The end-to-end test simulates a population with a *known* correct priority
order — including people who quit early and one random clicker — pushes their
files through the real scripts, and asserts the truth is recovered and the
clicker flagged. Browser tests (optional, need `playwright`) drive the real
survey in headless Chromium, including abort-and-resume and the download.
