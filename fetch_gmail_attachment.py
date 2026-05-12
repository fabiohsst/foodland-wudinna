"""
fetch_gmail_attachment.py — Fetch Email Attachments from Gmail
Foodland Wudinna

Used by GitHub Actions to retrieve the SOH and Specials files
from Gmail before running the headless order generator.

Usage:
    python fetch_gmail_attachment.py \\
        --sender postmaster@mg.gapsolutions.com.au \\
        --subject "Stock on Hand - FV" \\
        --output /tmp/soh.xlsx

    python fetch_gmail_attachment.py \\
        --sender admin@wudinnafoodland.com.au \\
        --subject "FRESHLINK PRICE GUIDE" \\
        --output /tmp/specials.docx \\
        --days 14

Exit codes:
    0  Attachment found and saved
    2  Email not found (used by workflow to detect missing specials)
    1  Other error
"""

import argparse
import email
import imaplib
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta


GMAIL_IMAP = "imap.gmail.com"


def fetch_attachment(sender: str, subject_contains: str, output_path: Path,
                     days_back: int = 7) -> bool:
    """
    Search Gmail for the most recent email matching sender + subject fragment,
    download the first attachment, and save it to output_path.
    Returns True on success.
    """
    address  = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]

    print(f"[fetch] Connecting to Gmail as {address}…")
    mail = imaplib.IMAP4_SSL(GMAIL_IMAP)
    mail.login(address, password)
    mail.select("INBOX")

    # Build search criteria
    since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
    criteria = (
        f'(FROM "{sender}" SUBJECT "{subject_contains}" SINCE "{since_date}")'
    )
    print(f"[fetch] Searching: {criteria}")

    _, data = mail.search(None, criteria)
    msg_ids = data[0].split()

    if not msg_ids:
        print(f"[fetch] No matching emails found.", file=sys.stderr)
        mail.logout()
        return False

    # Use the most recent match
    latest_id = msg_ids[-1]
    print(f"[fetch] Found {len(msg_ids)} match(es) — fetching most recent (id={latest_id.decode()})…")

    _, msg_data = mail.fetch(latest_id, "(RFC822)")
    mail.logout()

    raw = msg_data[0][1]
    msg = email.message_from_bytes(raw)
    print(f"[fetch] Subject: {msg['Subject']}")
    print(f"[fetch] Date:    {msg['Date']}")

    # Find the first usable attachment
    for part in msg.walk():
        content_disposition = str(part.get("Content-Disposition", ""))
        if "attachment" not in content_disposition.lower():
            continue

        filename = part.get_filename()
        if not filename:
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(payload)
        print(f"[fetch] Saved attachment '{filename}' ({len(payload):,} bytes) → {output_path}")
        return True

    print(f"[fetch] Email found but no attachment.", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description="Fetch Gmail attachment")
    parser.add_argument("--sender",  required=True, help="Sender email address")
    parser.add_argument("--subject", required=True, help="Subject line (partial match)")
    parser.add_argument("--output",  required=True, help="Output file path")
    parser.add_argument("--days",    type=int, default=7, help="Search last N days (default: 7)")
    args = parser.parse_args()

    for var in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"):
        if not os.environ.get(var):
            print(f"[error] Environment variable {var} is not set.", file=sys.stderr)
            sys.exit(1)

    found = fetch_attachment(
        sender=args.sender,
        subject_contains=args.subject,
        output_path=Path(args.output),
        days_back=args.days,
    )

    if not found:
        sys.exit(2)   # exit 2 = email not found


if __name__ == "__main__":
    main()
