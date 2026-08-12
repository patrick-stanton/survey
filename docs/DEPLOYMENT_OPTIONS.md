# Deployment & Data-Return Options

Practical menu for running this on a restricted corporate network, with
trade-offs. The tool already supports the recommended paths; the others are here
so you can choose deliberately and defend the choice.

---

## Part A — How respondents get and run the survey (5 options)

The survey is one self-contained HTML file. The question is only how it reaches
people and how they open it.

### 1. SharePoint / OneDrive link ✓ *(recommended)*
Upload `survey.html` (or `survey.zip`) to a SharePoint doc library or OneDrive
folder and send the link.
- **Pros:** Nothing to install; works for a 5-person session or a 200-person
  townhall blast; stays inside the corporate boundary; you can update the file in
  place; opens in-browser or downloads depending on tenant settings.
- **Cons:** Requires a SharePoint/OneDrive location you can share broadly; some
  tenants force download rather than in-browser open (still fine).
- **Effort:** Lowest. You already have the file.

### 2. Zipped email attachment ✓ *(recommended fallback)*
Email `survey.zip` directly.
- **Pros:** No shared location needed; everyone has email.
- **Cons:** Outlook/M365 frequently **block bare `.html`** attachments as phishing
  — hence the `.zip`; even zips are sometimes stripped; attachment size limits
  (~10 MB, we're at ~40 KB so fine); recipients must extract before opening.
- **Effort:** Low. Pilot with one recipient in your tenant first.

### 3. Shared network drive / file share
Drop `survey.html` on a `\\server\share` everyone can reach; send the path.
- **Pros:** Trivial inside a LAN; no internet at all; central copy you control.
- **Cons:** Only reaches people with drive access (weak for townhalls / partners);
  some orgs mark files opened from network shares as untrusted.
- **Effort:** Low, if such a share exists.

### 4. Embed in an Excel workbook
Put the use cases in a sheet and drive the best/worst logic with cell
formulas/VBA, so respondents "take the survey" inside Excel.
- **Pros:** Excel is universally installed and trusted; no browser question.
- **Cons:** **Significant rebuild** — the balanced-design generation, autosave,
  and compact-code return would have to be reimplemented in VBA, and **macro-
  enabled workbooks are themselves often blocked** on hardened networks (the very
  problem we're avoiding). Formula-only (no macros) can't do the adaptive design.
  Higher maintenance, worse UX than the HTML file.
- **Effort:** High. **Not recommended** — it trades a clean, tested tool for a
  fragile one to solve a problem the single-file HTML already solves.

### 5. Internal web server (small hosted app)
Stand up a tiny internal server that serves the survey and collects results
centrally.
- **Pros:** Central automatic collection (removes the return-gathering step
  entirely); real-time progress; best at 200-respondent scale.
- **Cons:** Requires hosting approval, a server to maintain, and a security
  review of a running service — exactly the friction we designed around. Overkill
  for 5-person sessions.
- **Effort:** Highest. Worth revisiting only if collection volume becomes painful;
  the code is structured so a server wrapper could reuse the same engine later.

**Recommendation:** SharePoint link as the default, zipped email as the fallback.
Both are zero-build and inside the corporate boundary. Avoid the Excel rebuild;
defer the server unless scale demands it.

---

## Part B — How results come back to you (2 options)

### 1. One-click "Send Your Results" + mailbox pull ✓ *(recommended)*
The finish screen opens the respondent's own mail client, pre-addressed to an
address **you set at build time** (`survey.return_email` in `config.yaml`), with
the whole session encoded as a short code **in the body** — no attachment. They
press Send. You collect with `pull_email.py` (IMAP), or by saving the emails as
`.txt`.
- **Pros:** Lowest possible friction — no download, no file handling; results
  land in one mailbox; `pull_email.py` automates collection; works email-client-
  agnostic (it's a standard `mailto:` link).
- **Cons:** Relies on the respondent having a configured mail client (true for
  virtually all corporate desktops); very long 60-minute sessions fall back to
  attaching the downloaded file automatically; IMAP is disabled in some O365
  tenants — then you save emails as `.txt` manually (still one drag).
- **Recommendation:** Use a **dedicated mailbox** (e.g. a shared/functional
  mailbox) as the return address so results don't clutter your inbox and
  `pull_email.py` has a clean folder to read.

### 2. Download file → SharePoint drop folder
Respondents click "Download results file" and drop the `.json` into a shared
SharePoint/OneDrive folder you point them to; you sync that folder to
`data/inbox/`.
- **Pros:** No mailbox needed; SharePoint keeps an organized record; scales well.
- **Cons:** More steps for the respondent (download, then upload); requires a drop
  location everyone can write to.

Both funnel into the same `data/inbox/` → `ingest.py` → archive, and can be
mixed freely within one collection effort.

**Recommendation:** Option 1 with a dedicated return mailbox as the primary,
Option 2 as the escape hatch for anyone whose mail client won't cooperate.

---

## A note on the "smarter" idea

The reason a raw `mailto:` with an in-body code beats a fancier auto-send is
**trust and reach**: anything that silently sends email from the browser would be
blocked (and rightly distrusted) on a hardened network, and would require
per-client configuration. Handing the respondent a pre-filled draft they visibly
send themselves is both the least-friction path that survives corporate security
*and* the most transparent one — they see exactly what leaves their machine.
