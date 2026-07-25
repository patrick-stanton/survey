# Project Handoff — Use-Case Prioritization Survey Tool

Context for a developer (human or AI) picking this up in a terminal session.
Read this first, then `README.md` (operator guide) and `docs/DESIGN.md` (why).

---

## 1. What this is

A tool for a defense/aerospace MBSE team that keeps ~50–70 use cases in a
**Cameo Systems Modeler 2026x** model and must prioritize them across up to
~200 stakeholders — replacing live interviews + manual data entry.

**Pipeline:** Cameo → CSV → generated single-file HTML survey → respondents
answer best/worst screens (MaxDiff) → they return a results CSV → ingest into
an append-only archive → resolve into rankings → **rank back into Cameo**.

The operator (repo owner) is a self-described novice programmer. Clarity,
guardrails, and defensibility to leadership matter as much as correctness.

---

## 2. Current state — what exists and is verified

All of this is implemented, tested (68 passing tests), and pushed.

| Script | Purpose |
|---|---|
| `build_survey.py` | catalog CSV + `config.yaml` → `dist/survey.html` (+ `.zip`); saves a catalog **version snapshot** |
| `simulate_respondents.py` | **test helper** — writes N fake respondent CSVs into `data/survey_inbox/` answering a hidden ground-truth order |
| `ingest.py` | validates results (CSV / saved-email .txt / legacy JSON) → `data/archive/active/` |
| `resolve.py` | pooled archive → `cameo_import.csv` (**rank only**), `use_cases_enriched.csv`, `resolve_report.txt`, `report.html` |
| `exclude.py` | quarantine suspect responses (`--email/--session/--before/--after`, `--restore`) — never deletes |
| `reconcile.py` | interactive mapping when use cases are renamed/split/merged/dropped/revived |
| `demo.py` | one-command end-to-end demo on throwaway temp data |
| `pull_email.py` | optional IMAP puller into the inbox |

**Verified working end-to-end** (I ran each in a clean sandbox):
- 20 simulated respondents → ingest → resolve **recovers the hidden true ranking**.
- `exclude.py` removes a random-clicker; resolve recomputes (20 → 19 respondents).
- Splitting `UC-027` into `UC-101`/`UC-102` with `supersedes=UC-027` → **both
  children inherit rank #1** (carryover works).
- Deleting a use case *without* declaring lineage → resolve **refuses** with
  "unmapped orphan … votes at stake"; `reconcile.py` maps it; resolve proceeds.

**Design decisions locked in** (do not silently revert):
- Results come back as a **legible CSV** (not an encoded blob), with an embedded
  SHA-256 checksum for *corruption* detection. Real integrity = ingest
  **re-derives** each respondent's expected screens and rejects fabrications.
- **Only `rank`** goes into Cameo (`cameo_import.csv`); depth lives in the
  enriched CSV + `report.html`.
- Archive is **append-only**, `active/` vs `excluded/<reason>/`; resolve reads
  only `active/` and reports exclusions. Nothing is ever deleted.
- Lineage (rename/split/merge/drop/revive) is applied **at analysis time**, never
  by rewriting raw data. `surveyId` is the permanent key; never reuse an id.
- Unmapped orphans → **refuse to run** (`--drop-unmapped` to override).
- Methods: P1 counts (headline), P2 Copeland, P3 Bradley-Terry, P4 Bayesian,
  P5 bootstrap CIs. Excluded on purpose: hierarchical Bayes, Kemeny-Young, IRV,
  naive rank-averaging (see `METHODOLOGY.md`).

---

## 3. Known gaps — what the operator actually hit

These are the **priority work items**. The operator tried the walkthrough on a
fresh Ubuntu machine and reported:

1. **PEP 668 / externally-managed-environment.** `pip install` fails on Debian/
   Ubuntu system Python. Needs a venv step *baked into the docs and ideally a
   setup script* — not an afterthought.
2. **`simulate_respondents.py` "didn't work."** Most likely causes: run before
   `data/use_cases.csv` existed, or venv not active, or ids not persisted. The
   script errors helpfully but the *walkthrough ordering* is the real problem.
3. **`report.html` "didn't work."** `xdg-open` may be absent/headless. Needs a
   documented fallback (print the absolute path; suggest `python3 -m http.server`
   or opening the file directly).
4. **No clear way to test changing/removing use cases.** The capability exists
   but there is no guided, scripted scenario the operator can run and watch.
5. **No way to test the Cameo round-trip / traceability** — there is no Cameo on
   the Linux box. Needs a *simulated* Cameo export/import loop proving
   `surveyId` traceability survives edit → re-export → re-ingest.
6. **Walkthrough structure is wrong for this operator.** Prose steps scattered in
   chat don't work. Wants something structured, in-repo, runnable.

---

## 4. Suggested next work (proposed, not prescriptive)

- A **guided scenario harness** — e.g. `scenarios/` or `walkthrough.py` with
  numbered, self-verifying scenarios the operator runs one at a time:
  `01_first_survey`, `02_bad_actor_removal`, `03_split_use_case`,
  `04_delete_and_reconcile`, `05_revive_use_case`, `06_cameo_round_trip`.
  Each should print what it's doing, what to look for, and PASS/FAIL.
- A **`setup.sh`** (venv + deps + sanity check) so step 0 can't fail.
- A **Cameo simulator** (`cameo_sim.py`): mimic generic-table export/import
  against a fake model file so traceability is provable without Cameo.
- **`BUSINESS_SIM.md`** replacing the chat walkthrough — one structured runbook.
- Reconsider `demo.py`'s docstring (it still mentions "UCS1 email codes"; the
  code path now writes CSVs — docstring drift).

---

## 5. Environment notes

- Ubuntu/Debian: **must** use a venv (`python3 -m venv .venv && source
  .venv/bin/activate`), else PEP 668 blocks installs.
- Core deps: `numpy pandas PyYAML`. Optional: `choix scipy` (enable P4 + richer
  diagnostics), `pytest` (tests), `playwright` (browser tests, optional).
- Tests: `python -m pytest tests/ -q` → 68 passing (a few skip without node/
  playwright — harmless).
- `data/use_cases.csv` is **gitignored** (real catalog may hold internal names);
  the tracked example is `data/use_cases.sample.csv`.
- **Id persistence gotcha:** the sample has blank ids that are minted per build.
  After the first `build_survey.py`, copy `data/use_cases_with_ids.csv` over
  `data/use_cases.csv` — this is the local stand-in for "paste the surveyIds
  into Cameo." Without it, ids re-mint and catalog edits won't line up.

---

## 6. Working agreements

- Branch: `claude/usecase-prioritization-survey-o6mvu2`. Commit + push working
  increments; keep tests green.
- The operator is a novice: prefer explicit, copy-pasteable commands, obvious
  file names, and scripts that fail with actionable messages.
- Be honest about limits (e.g. a client-side checksum is *not* tamper-proof) —
  the tool's credibility with leadership depends on not overselling.
- Every claim in docs should be something you actually ran and saw work.
