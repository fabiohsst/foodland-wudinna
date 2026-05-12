"""
send_order_email.py — Send Order Sheet by Email
Foodland Wudinna

Used by GitHub Actions to email the generated order sheet Excel.

Usage:
    python send_order_email.py \\
        --file /tmp/order_sheet.xlsx \\
        --recipients fabio@example.com,staff@example.com

    # To send an alert instead of an order sheet:
    python send_order_email.py --alert "Specials file not found in Gmail."

Environment variables required:
    GMAIL_ADDRESS       Sender Gmail address
    GMAIL_APP_PASSWORD  Gmail App Password
    ORDER_RECIPIENTS    Comma-separated recipient list (can override --recipients)
"""

import argparse
import os
import smtplib
import sys
from datetime import date
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


GMAIL_SMTP = "smtp.gmail.com"
GMAIL_PORT = 587


def send_email(recipients: list[str], subject: str, body: str,
               attachment_path: Path | None = None):
    address  = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart()
    msg["From"]    = address
    msg["To"]      = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path and attachment_path.exists():
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=attachment_path.name)
        part["Content-Disposition"] = f'attachment; filename="{attachment_path.name}"'
        msg.attach(part)

    print(f"[email] Sending to: {', '.join(recipients)}")
    with smtplib.SMTP(GMAIL_SMTP, GMAIL_PORT) as server:
        server.starttls()
        server.login(address, password)
        server.sendmail(address, recipients, msg.as_string())
    print(f"[email] Sent: {subject}")


def send_order_sheet(file_path: Path, recipients: list[str]):
    today_str = date.today().strftime("%A %d %b %Y")
    subject   = f"FV Order Sheet — Foodland Wudinna — {today_str}"
    body = (
        f"Hi,\n\n"
        f"Please find attached the automated Fruit & Veg order sheet for {today_str}.\n\n"
        f"This order sheet was generated automatically at 1:30 PM.\n"
        f"Review it before placing the order with Freshlink.\n\n"
        f"Foodland Wudinna\n"
        f"Automated Order System"
    )
    send_email(recipients, subject, body, attachment_path=file_path)


def send_alert(message: str, recipients: list[str]):
    today_str = date.today().strftime("%A %d %b %Y")
    subject   = f"⚠️ FV Order Sheet — Action Required — {today_str}"
    body = (
        f"Hi,\n\n"
        f"The automated order sheet could NOT be generated today ({today_str}).\n\n"
        f"Reason:\n{message}\n\n"
        f"Please generate the order sheet manually using the Order App.\n\n"
        f"Foodland Wudinna\n"
        f"Automated Order System"
    )
    send_email(recipients, subject, body)


def main():
    parser = argparse.ArgumentParser(description="Send order sheet email")
    parser.add_argument("--file",       default=None, help="Path to order sheet Excel")
    parser.add_argument("--recipients", default=None, help="Comma-separated recipient emails")
    parser.add_argument("--alert",      default=None, help="Send an alert email with this message instead")
    args = parser.parse_args()

    for var in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"):
        if not os.environ.get(var):
            print(f"[error] Environment variable {var} is not set.", file=sys.stderr)
            sys.exit(1)

    # Recipients: --recipients arg → ORDER_RECIPIENTS env var
    recipients_str = args.recipients or os.environ.get("ORDER_RECIPIENTS", "")
    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
    if not recipients:
        print("[error] No recipients specified. Use --recipients or set ORDER_RECIPIENTS.", file=sys.stderr)
        sys.exit(1)

    if args.alert:
        send_alert(args.alert, recipients)
    elif args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"[error] File not found: {file_path}", file=sys.stderr)
            sys.exit(1)
        send_order_sheet(file_path, recipients)
    else:
        print("[error] Provide either --file or --alert.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
