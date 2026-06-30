"""
calendar_tool.py — Google Calendar operations for the ADK Agent.

Tools:
  - get_upcoming_events(days)
  - create_event(title, date, time, duration, description)
  - check_availability(date)
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ── Service factory ──────────────────────────────────────────────────────────

def _get_service(creds):
    """Build Google Calendar API service."""
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_event(event: dict) -> dict:
    """Normalize a Calendar event to a clean dict."""
    start = event.get("start", {})
    end = event.get("end", {})

    # Handle all-day events (date) vs timed events (dateTime)
    start_str = start.get("dateTime", start.get("date", "unknown"))
    end_str = end.get("dateTime", end.get("date", "unknown"))

    return {
        "id": event.get("id", ""),
        "title": event.get("summary", "(untitled)"),
        "start": start_str,
        "end": end_str,
        "location": event.get("location", ""),
        "description": event.get("description", ""),
        "attendees": [
            a.get("email", "") for a in event.get("attendees", [])
        ],
        "status": event.get("status", "confirmed"),
        "html_link": event.get("htmlLink", ""),
    }


def _to_rfc3339(date_str: str, time_str: str = "00:00") -> str:
    """
    Convert a human date + time to RFC 3339 format.
    Accepts: 'YYYY-MM-DD', 'Monday', 'tomorrow', 'today', etc.
    """
    now = datetime.now()

    # Natural language shortcuts
    date_str_lower = date_str.lower().strip()
    if date_str_lower == "today":
        base = now.date()
    elif date_str_lower == "tomorrow":
        base = (now + timedelta(days=1)).date()
    elif date_str_lower in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
        weekdays = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                    "friday": 4, "saturday": 5, "sunday": 6}
        target = weekdays[date_str_lower]
        days_ahead = (target - now.weekday() + 7) % 7
        if days_ahead == 0:
            days_ahead = 7  # Next occurrence
        base = (now + timedelta(days=days_ahead)).date()
    else:
        # Try parsing ISO format
        try:
            base = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            try:
                base = datetime.strptime(date_str, "%m/%d/%Y").date()
            except ValueError:
                base = now.date()

    # Parse time
    try:
        t = datetime.strptime(time_str.strip(), "%H:%M").time()
    except ValueError:
        try:
            t = datetime.strptime(time_str.strip(), "%I:%M %p").time()
        except ValueError:
            try:
                t = datetime.strptime(time_str.strip(), "%I%p").time()
            except ValueError:
                t = datetime.strptime("09:00", "%H:%M").time()

    dt = datetime.combine(base, t)
    # Use local timezone offset (simplified; use pytz for full TZ support)
    return dt.isoformat()


# ── Tool functions ────────────────────────────────────────────────────────────

def get_upcoming_events(creds, days: int = 7) -> dict[str, Any]:
    """
    List upcoming calendar events in the next N days.

    Args:
        creds: Google OAuth2 credentials.
        days: Number of days to look ahead (default 7, max 90).

    Returns:
        dict with 'events' list or 'error' string.
    """
    days = min(max(1, days), 90)
    try:
        service = _get_service(creds)

        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()

        result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            maxResults=50,
        ).execute()

        events = result.get("items", [])
        if not events:
            return {
                "events": [],
                "message": f"No events found in the next {days} days.",
                "days_checked": days,
            }

        return {
            "events": [_parse_event(e) for e in events],
            "count": len(events),
            "days_checked": days,
        }

    except HttpError as e:
        return {"error": f"Calendar API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error fetching events: {str(e)}"}


def create_event(
    creds,
    title: str,
    date: str,
    time: str = "09:00",
    duration_minutes: int = 60,
    description: str = "",
    attendees: list[str] | None = None,
) -> dict[str, Any]:
    """
    Create a new calendar event.

    Args:
        creds: Google OAuth2 credentials.
        title: Event title/summary.
        date: Date string ('2024-12-25', 'Monday', 'tomorrow', 'today').
        time: Time string ('14:00', '2:00 PM', '10am').
        duration_minutes: Duration in minutes (default 60).
        description: Optional event description.
        attendees: Optional list of attendee email addresses.

    Returns:
        dict with created event details or 'error' string.
    """
    try:
        service = _get_service(creds)

        start_dt = _to_rfc3339(date, time)
        start = datetime.fromisoformat(start_dt)
        end = start + timedelta(minutes=duration_minutes)

        event_body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "America/New_York"},
            "end": {"dateTime": end.isoformat(), "timeZone": "America/New_York"},
        }

        if attendees:
            event_body["attendees"] = [{"email": a} for a in attendees]

        created = service.events().insert(
            calendarId="primary",
            body=event_body,
            sendNotifications=bool(attendees),
        ).execute()

        return {
            "status": "created",
            "event": _parse_event(created),
            "link": created.get("htmlLink", ""),
        }

    except HttpError as e:
        return {"error": f"Calendar API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error creating event: {str(e)}"}


def check_availability(creds, date: str) -> dict[str, Any]:
    """
    Check free/busy slots for a given date.

    Args:
        creds: Google OAuth2 credentials.
        date: Date to check ('2024-12-25', 'Monday', 'tomorrow', 'today').

    Returns:
        dict with busy slots and free windows, or 'error' string.
    """
    try:
        service = _get_service(creds)

        # Resolve date
        start_str = _to_rfc3339(date, "00:00")
        start = datetime.fromisoformat(start_str)
        end = start + timedelta(days=1)

        # Use freebusy query
        body = {
            "timeMin": start.isoformat() + "Z" if start.tzinfo is None else start.isoformat(),
            "timeMax": end.isoformat() + "Z" if end.tzinfo is None else end.isoformat(),
            "items": [{"id": "primary"}],
        }

        result = service.freebusy().query(body=body).execute()
        busy_slots = result.get("calendars", {}).get("primary", {}).get("busy", [])

        # Also fetch events for that day with details
        events_result = service.events().list(
            calendarId="primary",
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = [_parse_event(e) for e in events_result.get("items", [])]

        # Compute free windows (business hours 8am-6pm)
        day_start = start.replace(hour=8, minute=0)
        day_end = start.replace(hour=18, minute=0)

        busy_parsed = []
        for slot in busy_slots:
            bs = datetime.fromisoformat(slot["start"].replace("Z", "+00:00")).replace(tzinfo=None)
            be = datetime.fromisoformat(slot["end"].replace("Z", "+00:00")).replace(tzinfo=None)
            busy_parsed.append((bs, be))

        # Find free windows
        free_windows = []
        cursor = day_start
        for bs, be in sorted(busy_parsed):
            if cursor < bs:
                free_windows.append({
                    "from": cursor.strftime("%H:%M"),
                    "to": bs.strftime("%H:%M"),
                    "duration_minutes": int((bs - cursor).total_seconds() / 60),
                })
            cursor = max(cursor, be)
        if cursor < day_end:
            free_windows.append({
                "from": cursor.strftime("%H:%M"),
                "to": day_end.strftime("%H:%M"),
                "duration_minutes": int((day_end - cursor).total_seconds() / 60),
            })

        return {
            "date": start.strftime("%A, %B %d, %Y"),
            "events": events,
            "busy_count": len(busy_slots),
            "free_windows": free_windows,
            "is_free": len(busy_slots) == 0,
        }

    except HttpError as e:
        return {"error": f"Calendar API error: {e.reason} (status {e.resp.status})"}
    except Exception as e:
        return {"error": f"Unexpected error checking availability: {str(e)}"}