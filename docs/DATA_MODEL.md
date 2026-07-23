# Data Model & Operations

Where every file lives, how data flows, and how to handle the two things that
make a long-running survey hard: **bad data** and a **changing use-case list**.

## The one principle

**`surveyId` is permanent and is the only thing that identifies a use case.**
Names and wording are labels that can drift; votes attach to the *id*. Two rules
follow, and keeping them makes almost all versioning worries disappear:

- Never mint a new id for the same concept.
- Never reuse an id for a different concept.

## Folder structure

```
data/
├── use_cases.sample.csv   tracked example catalog (copy it to start)
├── use_cases.csv          YOUR catalog (gitignored — may hold internal names)
├── survey_inbox/          drop received result files here (CSV / saved email .txt)
├── archive/
│   ├── active/            COUNTED responses, one CSV per respondent-session
│   └── excluded/<reason>/ responses removed from analysis, KEPT for audit
├── catalog_versions/      immutable snapshot of each catalog version (by hash)
├── lineage.csv            id→id mappings for renamed/split/merged use cases (COMMIT this)
├── roster.txt             optional list of invited emails (gitignored)
└── out/                   enriched CSV · report.txt · report.html · cameo_import.csv
```

What's committed to git: the sample catalog, `lineage.csv` (no PII — it's just
id mappings, and sharing it keeps everyone's reconciliation decisions in sync).
What's **not**: your real catalog, the archive (respondent PII), roster, and
outputs. Keep the archive on a backed-up internal location and treat it as PII.

## Data lifecycle

```
Cameo ─build_survey.py─► survey.html ─(respondents)─► result CSVs
   │                          │                            │
   │                    catalog_versions/<hash>.csv   survey_inbox/
   │                                                       │
   └──────── cameo_import.csv ◄─resolve.py─ archive/active/ ◄─ingest.py
```

- **build** writes a version snapshot so we always know what each id meant.
- **ingest** validates each file (schema, checksum, and — the real integrity
  check — re-derives the screens the respondent should have seen and rejects
  fabricated ones), then stores it in `archive/active/` as canonical CSV.
- **resolve** reads only `active/`, applies lineage, and writes the outputs.

## Removing bad data (six weeks in, you find garbage)

Nothing is ever deleted — suspect responses are **quarantined**, which keeps the
result reproducible and the exclusion auditable and reversible.

```bash
python exclude.py --list                                  # see what's in the archive
python exclude.py --before 2026-07-01 --reason week1-bad-link
python exclude.py --email bob@corp.com   --reason known-bad-actor
python exclude.py --session s1a2b3       --reason duplicate-interview
python exclude.py --restore week1-bad-link                # changed your mind
python resolve.py                                         # recompute from what remains
```

Each command moves matching files from `active/` to `excluded/<reason>/`.
`resolve` reports what's excluded. "The fifth interview on day 3 of week 2" =
find it with `--list`, exclude it by `--session` or `--email`, re-resolve.

## Changing the use-case list

You change the model in Cameo, rebuild, and keep surveying. Old responses now
reference ids that may not be in the new catalog. Here's how each change is handled.

### Rename or reword (same concept, same id)
Keep the id. Votes carry automatically. If you changed the *wording*, ingest of
any straggler old-version file will flag the catalog-hash mismatch; accept it
with `--allow-catalog <hash>` once you've confirmed it's still comparable.

### Split one use case into several (priority carries to all children)
In Cameo, create the new use cases with NEW ids and set each one's `supersedes`
tag to the old id; delete the old one. Example — UC-005 → UC-061 + UC-062:

| Source | references | after `resolve --lineage inherit` |
|---|---|---|
| week-1 files | `UC-005` | replayed for **both** UC-061 and UC-062 |
| week-2 files | `UC-061`,`UC-062` | used as-is |

Both children inherit the parent's record against every other item, so they
**start at the parent's priority** and diverge as new data distinguishes them.
(Right after the split, before new data, they rank adjacent — correct: the data
can't split the parent's value until people weigh in on the distinction.)

### Merge several into one, or drop
Merge: the survivor lists the old ids in `supersedes`; their votes combine.
Drop: mark it dropped (its votes stop counting). Both via `supersedes` or
reconcile.

### Drop and bring back later
- Same id → votes reconnect automatically (the id is the anchor).
- New id → map old→new in reconcile so the history carries over.

## Reconciliation — you answer each change once

The tool can detect *what* changed (ids that vanished/appeared) but not the
*meaning* (only you know UC-061 came from UC-005). So when `resolve` finds an
**orphan** — a historical id that's neither current nor mapped — it refuses to
run (nothing silently dropped) and points you to:

```bash
python reconcile.py
```

which, for each orphan, shows its old name and how many votes are at stake and
offers: **renamed / split / merged / dropped / revived-under-new-id**. Your
answers save to `data/lineage.csv`, so every future resolve is automatic. You
can also declare changes ahead of time with the `supersedes` tag in Cameo; both
feed the same map, and chains resolve transitively (UC-005→UC-062→UC-070 works).

## Safety nets

- **Unmapped orphans** → resolve refuses (or `--drop-unmapped` to proceed).
- **Id-reuse drift** → if an id's name changed a lot between the version a
  response was collected under and now, resolve warns (`DRIFT?`) so accidental
  id reuse can't quietly corrupt results.
- **Dangling lineage** → a mapping pointing at a non-existent use case is flagged.
- **Reproducibility** → resolve is a pure function of (active archive, lineage,
  config, seed, `--as-of`); the same inputs always regenerate the same outputs.
