#!/usr/bin/env python3
"""Pull survey results out of your mailbox into data/inbox/.

Usage:
    python pull_email.py            # then run: python ingest.py

Setup: fill in the email_pull section of config.yaml (server, username).
The password is prompted each run — or set the UCSURVEY_EMAIL_PASSWORD
environment variable — and is never written to disk.

What it does: connects over IMAP (works with any IMAP-enabled account),
finds messages whose subject contains your configured phrase, and saves
their .json attachments and any UCS1 results codes from the body into
data/inbox/. Already-pulled messages are remembered (data/.pulled_messages
.json) and skipped, and your mailbox is never modified.

If your organization has disabled IMAP (some O365 tenants do): select the
result emails in Outlook, File > Save As (.txt), drop them into data/inbox/
— ingest.py reads codes straight out of saved emails.
"""

from __future__ import annotations

import email
import email.policy
import getpass
import imaplib
import json
import os
import re
import sys
from pathlib import Path

import yaml

from ucsurvey.compact import find_codes

HERE = Path(__file__).parent
SEEN_FILE = HERE / "data" / ".pulled_messages.json"


def load_seen() -> set[str]:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen)))


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s)[:80]


def main() -> int:
    cfg = yaml.safe_load((HERE / "config.yaml").read_text(encoding="utf-8"))
    pull = cfg.get("email_pull") or {}
    server = str(pull.get("imap_server") or "").strip()
    username = str(pull.get("username") or "").strip()
    if not server or not username:
        print("Fill in email_pull.imap_server and email_pull.username in config.yaml first.")
        return 1
    port = int(pull.get("imap_port", 993))
    mailbox = str(pull.get("mailbox", "INBOX"))
    subject = str(pull.get("subject_contains", "Use case survey results"))

    password = os.environ.get("UCSURVEY_EMAIL_PASSWORD") or getpass.getpass(
        f"Password for {username} (not stored): ")

    inbox = HERE / "data" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    seen = load_seen()
    n_json = n_codes = n_skipped = 0

    print(f"Connecting to {server}:{port} ...")
    try:
        conn = imaplib.IMAP4_SSL(server, port)
        conn.login(username, password)
    except imaplib.IMAP4.error as exc:
        print(f"IMAP login failed: {exc}")
        print("If your organization disables IMAP, use the manual fallback in "
              "this script's help text (save emails as .txt into data/inbox/).")
        return 1

    try:
        conn.select(mailbox, readonly=True)
        # SUBJECT search is server-side; quote and strip exotic chars for safety.
        needle = subject.replace('"', "")
        status, data = conn.search(None, "SUBJECT", f'"{needle}"')
        ids = data[0].split() if status == "OK" else []
        print(f"{len(ids)} matching message(s) in {mailbox}.")

        for msg_id in ids:
            status, fetched = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not fetched or fetched[0] is None:
                continue
            msg = email.message_from_bytes(fetched[0][1], policy=email.policy.default)
            uid = msg.get("Message-ID", "") or f"no-id-{msg_id.decode()}"
            if uid in seen:
                n_skipped += 1
                continue

            sender = safe_name(msg.get("From", "unknown"))
            for part in msg.walk():
                fname = part.get_filename() or ""
                if fname.lower().endswith((".csv", ".json")):
                    payload = part.get_payload(decode=True) or b""
                    if len(payload) > 5_000_000:  # real result files are a few KB
                        continue
                    (inbox / safe_name(fname)).write_bytes(payload)
                    n_json += 1
                elif part.get_content_type() in ("text/plain", "text/html"):
                    try:
                        text = part.get_content()
                    except Exception:
                        continue
                    # The survey pastes the CSV into the email body; save it so
                    # ingest can read it. (Legacy UCS1 codes are saved too.)
                    if "ucsurvey_csv" in text or find_codes(text):
                        out = inbox / f"email_{sender}_{safe_name(uid)}.txt"
                        out.write_text(text, encoding="utf-8")
                        n_codes += 1
            seen.add(uid)
    finally:
        conn.logout()

    save_seen(seen)
    print(f"Saved {n_json} attachment(s) and {n_codes} email-body result(s) "
          f"to {inbox} ({n_skipped} previously pulled, skipped).")
    if n_json or n_codes:
        print("Next: python ingest.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
