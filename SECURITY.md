# Security & Threat Model

This tool is designed to be cloned from GitHub and run inside a restricted
corporate network. This document states what it does and does not do, the
adversarial review it passed, and the operator's responsibilities.

## What this tool does NOT do (adoption safety)

Independently reviewed and verified in the code:

- **No network egress.** The survey HTML makes zero external requests — no CDN,
  no fonts, no analytics, no telemetry, no phone-home. It runs entirely in the
  respondent's browser and sends nothing anywhere until the respondent chooses
  to email their own result.
- **No dynamic code execution.** No `eval`, no `exec`, no `pickle`, no shell-out
  to untrusted input. YAML is parsed with `safe_load` only.
- **No secrets in the repo.** No committed credentials, tokens, internal
  hostnames, or real personal data (the shipped catalog is fictitious). The
  optional email password (`pull_email.py`) is prompted at runtime and never
  written to disk or logged.
- **No path traversal or injection into Cameo.** Respondent-controlled strings
  are sanitized before touching filenames, and the enriched CSV imported into
  Cameo is built only from your trusted catalog plus computed numbers — no
  respondent free-text reaches it.

The Python dependencies (numpy, pandas, PyYAML, and optionally choix, scipy) are
mainstream and version-bounded; see `requirements.txt`. On a restricted network,
install from your organization's vetted internal mirror, and prefer a
hash-pinned lockfile (instructions in `requirements.txt`).

## Threat model

The realistic adversary is **not** an external attacker (there is no server to
attack) but a **survey respondent** — a semi-trusted colleague who receives the
survey and could email back a hand-crafted result instead of a genuine one.
The harms that matters are therefore (a) crashing/hanging the operator's ingest,
and (b) skewing the prioritization. Both are addressed below.

## Hardening in place (verified by `tests/test_security.py`)

| Attack | Defense |
|---|---|
| Forged code with a huge `extraBlocks` → CPU/RAM exhaustion | `extraBlocks` bounded before use; rejected instantly |
| Malformed types (`sets: 5`, nested-bracket JSON, bad arm) | Turned into a clean REJECTED line, never a crash |
| One poisoned file in a batch | Per-file isolation — every other file still ingests |
| Oversized file / code | 5 MB cap on both `.json` and `.txt` paths |
| A 60-item "mega-screen" injecting a whole ordering | Screen width validated against the design |
| Control/terminal-escape chars in name/role/org/email | Rejected at ingest |
| Overwriting a colleague's recorded session | Supersede requires an append-only match; tampered re-exports rejected |
| PII in the shareable report | Response-quality flag is an aggregate count; no emails named |
| XSS via a config label | Rendered with `textContent`, never `innerHTML`; title HTML-escaped |
| Real catalog (with internal names) committed by accident | `data/use_cases.csv` is gitignored; only the fictitious sample is tracked |

## Operator responsibilities (controls the tool cannot enforce alone)

1. **Respondent identity is self-declared and unauthenticated.** Anyone who can
   email your collection address can submit under any name. Two controls:
   - Pass `--roster data/roster.txt` (one invited email per line) to `ingest.py`
     to reject responses from addresses you did not invite.
   - `ingest.py` prints when one respondent submitted multiple sessions.
   Reconcile the archived respondent list against your actual invite list before
   treating the ranking as decision-grade.
2. **Treat results as advisory decision-support**, not an automatic funding gate.
   The report's contested-item, small-sample, and group-agreement flags exist to
   invite human judgement.
3. **The UCS1 results code is compression, not encryption.** Name/email/role and
   answers are recoverable by anyone who sees the code (as they would be in any
   emailed form). Handle result emails with the same care as any internal PII.
4. **Do not commit your real catalog** if its passthrough columns (e.g. `owner`)
   contain internal names/emails — it is gitignored by default; keep it that way.
5. **Install dependencies from your vetted internal mirror**, ideally via a
   hash-pinned lockfile.

## Reporting

This is an internal tool; route any security concern to the tool's maintainer
along with the `resolve_report.txt` and the offending input file.
