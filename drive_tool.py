"""
drive_tool.py — Google Drive operations for the ADK Agent.

Tools:
  - search_files(query)
  - read_file(file_id)
  - list_recent_files(count)
"""

import io
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload


# ── Service factories ─────────────────────────────────────────────────────────

def _get_drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_docs_service(creds):
    return build("docs", "v1", credentials=creds, cache_discovery=False)


# ── Helpers ──────────────────────────────────────────────────────────────────

# MIME types that can be read as text
READABLE_MIME_TYPES = {
    "application/vnd.google-apps.document": "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "text/plain": "Text File",
    "text/csv": "CSV File",
    "text/markdown": "Markdown File",
    "application/json": "JSON File",
}

# Export formats for Google Workspace files
EXPORT_FORMATS = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

FILE_FIELDS = "id, name, mimeType, size, modifiedTime, webViewLink, owners, parents"


def _format_file(f: dict) -> dict:
    """Normalize a Drive file object."""
    return {
        "id": f.get("id", ""),
        "name": f.get("name", "(unnamed)"),
        "type": f.get("mimeType", "unknown"),
        "type_label": READABLE_MIME_TYPES.get(f.get("mimeType", ""), f.get("mimeType", "unknown")),
        "modified": f.get("modifiedTime", ""),
        "size_bytes": int(f.get("size", 0)) if f.get("size") else None,
        "link": f.get("webViewLink", ""),
        "readable": f.get("mimeType", "") in READABLE_MIME_TYPES,
    }


# ── Tool functions ────────────────────────────────────────────────────────────

def search_files(creds, query: str, max_results: int = 10) -> dict[str, Any]:
    """
    Search Google Drive files by name or content keyword.

    Args:
        creds: Google OAuth2 credentials.
        query: Search term (file name, keyword, type).
        max_results: Max results to return.

    Returns:
        dict with 'files' list or 'error' string.
    """
    max_results = min(max(1, max_results), 50)
    try:
        service = _get_drive_service(creds)

        # Build Drive query — supports name contains AND fullText contains
        # Try matching on name first, then full text
        drive_query = (
            f"(name contains '{query}' or fullText contains '{query}') "
            f"and trashed = false"
        )

        result = service.files().list(
            q=drive_query,
            pageSize=max_results,
            fields=f"files({FILE_FIELDS})",
            orderBy="modifiedTime desc",
        ).execute()

        files = result.get("files", [])
        if not files:
            return {
                "files": [],
                "message": f"No files found matching '{query}'.",
                "query": query,
            }

        return {
            "files": [_format_file(f) for f in files],
            "count": len(files),
            "query": query,
        }

    except HttpError as e:
        return {"error": f"Drive API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error searching Drive: {str(e)}"}


def list_recent_files(creds, count: int = 10) -> dict[str, Any]:
    """
    List recently modified files in Google Drive.

    Args:
        creds: Google OAuth2 credentials.
        count: Number of files to return (default 10, max 50).

    Returns:
        dict with 'files' list or 'error' string.
    """
    count = min(max(1, count), 50)
    try:
        service = _get_drive_service(creds)

        result = service.files().list(
            pageSize=count,
            fields=f"files({FILE_FIELDS})",
            orderBy="modifiedTime desc",
            q="trashed = false",
        ).execute()

        files = result.get("files", [])
        if not files:
            return {"files": [], "message": "No files found in Drive."}

        return {
            "files": [_format_file(f) for f in files],
            "count": len(files),
        }

    except HttpError as e:
        return {"error": f"Drive API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error listing Drive files: {str(e)}"}


def read_file(creds, file_id: str) -> dict[str, Any]:
    """
    Read the text content of a Google Drive file.

    Supports: Google Docs, Google Sheets (as CSV), plain text, markdown, JSON.

    Args:
        creds: Google OAuth2 credentials.
        file_id: The Drive file ID.

    Returns:
        dict with 'content', 'name', 'type', or 'error'.
    """
    try:
        service = _get_drive_service(creds)

        # Get file metadata
        file_meta = service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, size, webViewLink",
        ).execute()

        name = file_meta.get("name", "(unnamed)")
        mime_type = file_meta.get("mimeType", "")

        # ── Google Workspace files — export as text ──
        if mime_type in EXPORT_FORMATS:
            export_mime = EXPORT_FORMATS[mime_type]
            request = service.files().export_media(
                fileId=file_id,
                mimeType=export_mime,
            )
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            content = buffer.getvalue().decode("utf-8", errors="replace")

        # ── Plain text / other readable files — download directly ──
        elif mime_type in READABLE_MIME_TYPES:
            request = service.files().get_media(fileId=file_id)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            content = buffer.getvalue().decode("utf-8", errors="replace")

        else:
            return {
                "error": (
                    f"File '{name}' has type '{mime_type}' which cannot be read as text. "
                    f"Readable types: {list(READABLE_MIME_TYPES.keys())}"
                )
            }

        # Truncate for context window
        truncated = len(content) > 10000
        return {
            "id": file_id,
            "name": name,
            "type": READABLE_MIME_TYPES.get(mime_type, mime_type),
            "content": content[:10000],
            "truncated": truncated,
            "char_count": len(content),
            "link": file_meta.get("webViewLink", ""),
        }

    except HttpError as e:
        return {"error": f"Drive API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error reading file: {str(e)}"}