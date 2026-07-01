import base64
import email as email_lib
from email.mime.text import MIMEText
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ── Service factory ──────────────────────────────────────────────────────────

def _get_service(creds):
    """Build Gmail API service."""
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_message_headers(msg: dict) -> dict:
    """Extract subject, sender, date from message headers."""
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": headers.get("subject", "(no subject)"),
        "from": headers.get("from", "unknown"),
        "date": headers.get("date", "unknown"),
        "snippet": msg.get("snippet", ""),
    }


def _decode_body_part(part: dict) -> str:
    """Decode a MIME body part to plain text."""
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    return decoded


def _extract_body(payload: dict) -> str:
    """Recursively extract text/plain body from a message payload."""
    mime_type = payload.get("mimeType", "")

    # Direct text
    if mime_type == "text/plain":
        return _decode_body_part(payload)

    # Multipart — recurse
    parts = payload.get("parts", [])
    for part in parts:
        text = _extract_body(part)
        if text:
            return text

    return ""


# ── Tool functions ────────────────────────────────────────────────────────────

def get_latest_emails(creds, count: int = 5) -> dict[str, Any]:
    """
    Fetch the latest emails from Gmail inbox.

    Args:
        creds: Google OAuth2 credentials.
        count: Number of emails to return (default 5, max 20).

    Returns:
        dict with 'emails' list or 'error' string.
    """
    count = min(max(1, count), 20)
    try:
        service = _get_service(creds)
        result = service.users().messages().list(
            userId="me",
            maxResults=count,
            labelIds=["INBOX"],
        ).execute()

        messages = result.get("messages", [])
        if not messages:
            return {"emails": [], "message": "No emails found in inbox."}

        emails = []
        for msg_ref in messages:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            emails.append(_parse_message_headers(msg))

        return {"emails": emails, "count": len(emails)}

    except HttpError as e:
        return {"error": f"Gmail API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error fetching emails: {str(e)}"}


def search_emails(creds, query: str, max_results: int = 10) -> dict[str, Any]:
    """
    Search Gmail using a query string (same syntax as Gmail search bar).

    Args:
        creds: Google OAuth2 credentials.
        query: Search query, e.g. 'from:boss@company.com subject:invoice is:unread'.
        max_results: Maximum emails to return.

    Returns:
        dict with 'emails' list or 'error' string.
    """
    max_results = min(max(1, max_results), 50)
    try:
        service = _get_service(creds)
        result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()

        messages = result.get("messages", [])
        if not messages:
            return {"emails": [], "message": f"No emails found for query: '{query}'"}

        emails = []
        for msg_ref in messages:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            emails.append(_parse_message_headers(msg))

        return {
            "emails": emails,
            "count": len(emails),
            "query": query,
        }

    except HttpError as e:
        return {"error": f"Gmail API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error searching emails: {str(e)}"}


def get_email_body(creds, email_id: str) -> dict[str, Any]:
    """
    Read the full body of an email by its ID.

    Args:
        creds: Google OAuth2 credentials.
        email_id: The Gmail message ID.

    Returns:
        dict with 'body', 'subject', 'from', 'date', or 'error'.
    """
    try:
        service = _get_service(creds)
        msg = service.users().messages().get(
            userId="me",
            id=email_id,
            format="full",
        ).execute()

        meta = _parse_message_headers(msg)
        body = _extract_body(msg["payload"])

        # Fallback to snippet if body extraction fails
        if not body.strip():
            body = msg.get("snippet", "(body could not be extracted)")

        return {
            "id": email_id,
            "subject": meta["subject"],
            "from": meta["from"],
            "date": meta["date"],
            "body": body[:8000],  # Limit to 8k chars for context window
            "truncated": len(body) > 8000,
        }

    except HttpError as e:
        return {"error": f"Gmail API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error reading email: {str(e)}"}


def send_email(creds, to: str, subject: str, body: str) -> dict[str, Any]:
    """
    Send an email via Gmail.

    Args:
        creds: Google OAuth2 credentials.
        to: Recipient email address.
        subject: Email subject line.
        body: Plain text email body.

    Returns:
        dict with 'message_id' and 'status', or 'error'.
    """
    try:
        service = _get_service(creds)

        # Build MIME message
        mime_msg = MIMEText(body, "plain")
        mime_msg["to"] = to
        mime_msg["subject"] = subject

        # Encode to base64url
        encoded = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("utf-8")

        sent = service.users().messages().send(
            userId="me",
            body={"raw": encoded},
        ).execute()

        return {
            "status": "sent",
            "message_id": sent["id"],
            "to": to,
            "subject": subject,
        }

    except HttpError as e:
        return {"error": f"Gmail API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error sending email: {str(e)}"}