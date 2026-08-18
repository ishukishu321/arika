"""
Email reading & summarizing
============================
Uses plain stdlib imaplib (no extra dependency) against Gmail's IMAP
server, reusing the SAME email_address / email_app_password settings that
automation.send_email already uses (Settings panel -> App Password, not
your normal Gmail password: myaccount.google.com/apppasswords).

Two operations:
- fetch_recent(): pulls the last N messages (subject/from/date/snippet)
  from a folder (default INBOX). No AI involved — just raw IMAP.
- summarize_recent(): does the same fetch, then hands the bodies to
  Gemini to produce a short Hinglish-friendly summary. This is what you
  want for "mera inbox padh ke sunao" type asks.

Read-only. This module never deletes or sends anything.
"""

import email
import imaplib
from email.header import decode_header

from backend import settings_manager

IMAP_HOST = "imap.gmail.com"


def _decode(value) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(text)
    return "".join(out)


def _get_credentials():
    settings = settings_manager.load_settings()
    address = (settings.get("email_address") or "").strip()
    app_password = (settings.get("email_app_password") or "").strip()
    if not address or not app_password:
        raise RuntimeError(
            "No email account configured. Add email_address and "
            "email_app_password in Settings first."
        )
    return address, app_password


def _extract_snippet(msg, max_chars: int = 500) -> str:
    """Best-effort plain-text body extraction, trimmed short."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/plain" and "attachment" not in disposition:
                try:
                    payload = part.get_payload(decode=True) or b""
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                    break
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True) or b""
            body = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
        except Exception:
            body = ""

    body = " ".join(body.split())
    return body[:max_chars]


def fetch_recent(count: int = 5, folder: str = "INBOX", unread_only: bool = False) -> list:
    """Returns a list of {from, subject, date, snippet}, most recent first."""
    address, app_password = _get_credentials()
    count = max(1, min(int(count or 5), 25))

    conn = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        conn.login(address, app_password)
        conn.select(folder, readonly=True)

        criteria = "UNSEEN" if unread_only else "ALL"
        status, data = conn.search(None, criteria)
        if status != "OK":
            raise RuntimeError(f"IMAP search failed for folder '{folder}'.")

        ids = data[0].split()
        ids = ids[-count:] if ids else []
        ids.reverse()  # newest first

        results = []
        for msg_id in ids:
            status, msg_data = conn.fetch(msg_id, "(RFC822)")
            if status != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            results.append({
                "from": _decode(msg.get("From")),
                "subject": _decode(msg.get("Subject")),
                "date": msg.get("Date", ""),
                "snippet": _extract_snippet(msg),
            })
        return results
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def summarize_recent(count: int = 5, folder: str = "INBOX", unread_only: bool = False) -> str:
    """Fetches recent mail and asks Gemini to summarize it in short,
    scannable form. Import of gemini is local to avoid a circular import
    (gemini.py doesn't need to know about email_manager)."""
    from backend import gemini

    emails = fetch_recent(count=count, folder=folder, unread_only=unread_only)
    if not emails:
        return "No emails found."

    lines = []
    for i, e in enumerate(emails, 1):
        lines.append(
            f"{i}. From: {e['from']} | Subject: {e['subject']} | Date: {e['date']}\n"
            f"   Snippet: {e['snippet']}"
        )
    joined = "\n".join(lines)

    prompt = (
        "Summarize the following emails for the Admin. For each email give "
        "a one-line takeaway (what it's about / any action needed). Keep it "
        "short and scannable, not a full essay.\n\n" + joined
    )
    return gemini.ask_gemini(prompt)
