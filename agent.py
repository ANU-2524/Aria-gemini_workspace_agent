import os
import json
from typing import Any
from datetime import datetime

import google.generativeai as genai
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from google.oauth2.credentials import Credentials

import gmail_tool
import calendar_tool
import drive_tool


# ── Tool wrapper factory ──────────────────────────────────────────────────────

def make_gmail_tools(creds: Credentials) -> list:
    """Create Gmail tool functions bound to OAuth credentials."""

    def get_latest_emails(count: int = 5) -> dict:
        """
        Fetch the latest emails from your Gmail inbox.

        Args:
            count: Number of emails to retrieve (1-20, default 5).

        Returns:
            A dict with an 'emails' list containing subject, sender, date, and snippet for each email.
        """
        return gmail_tool.get_latest_emails(creds, count=count)

    def search_emails(query: str, max_results: int = 10) -> dict:
        """
        Search your Gmail using any query (same syntax as Gmail's search bar).

        Args:
            query: Search query, e.g. 'from:boss@company.com', 'subject:invoice', 'is:unread', 'has:attachment'.
            max_results: Maximum number of results (1-50, default 10).

        Returns:
            A dict with an 'emails' list of matching emails.
        """
        return gmail_tool.search_emails(creds, query=query, max_results=max_results)

    def get_email_body(email_id: str) -> dict:
        """
        Read the full body/content of a specific email by its ID.

        Args:
            email_id: The Gmail message ID (obtained from get_latest_emails or search_emails).

        Returns:
            A dict with 'subject', 'from', 'date', and full 'body' text.
        """
        return gmail_tool.get_email_body(creds, email_id=email_id)

    def send_email(to: str, subject: str, body: str) -> dict:
        """
        Send an email via Gmail. IMPORTANT: Always confirm with the user before calling this.

        Args:
            to: Recipient's email address.
            subject: Email subject line.
            body: Email body (plain text).

        Returns:
            A dict with 'status' and 'message_id' if successful.
        """
        return gmail_tool.send_email(creds, to=to, subject=subject, body=body)

    return [get_latest_emails, search_emails, get_email_body, send_email]


def make_calendar_tools(creds: Credentials) -> list:
    """Create Calendar tool functions bound to OAuth credentials."""

    def get_upcoming_events(days: int = 7) -> dict:
        """
        List your upcoming calendar events.

        Args:
            days: How many days ahead to look (1-90, default 7).

        Returns:
            A dict with an 'events' list containing title, start, end, location, and attendees.
        """
        return calendar_tool.get_upcoming_events(creds, days=days)

    def create_event(
        title: str,
        date: str,
        time: str = "09:00",
        duration_minutes: int = 60,
        description: str = "",
        attendees: list[str] | None = None,
    ) -> dict:
        """
        Create a new event on your Google Calendar. IMPORTANT: Confirm with user before calling this.

        Args:
            title: Event title/name.
            date: Date for the event. Accepts 'YYYY-MM-DD', 'Monday', 'tomorrow', 'today'.
            time: Start time. Accepts '14:00', '2:00 PM', '10am' (default '09:00').
            duration_minutes: Duration in minutes (default 60).
            description: Optional description or notes for the event.
            attendees: Optional list of attendee email addresses to invite.

        Returns:
            A dict with created event details and a calendar link.
        """
        return calendar_tool.create_event(
            creds,
            title=title,
            date=date,
            time=time,
            duration_minutes=duration_minutes,
            description=description,
            attendees=attendees,
        )

    def check_availability(date: str) -> dict:
        """
        Check your free/busy slots for a specific date.

        Args:
            date: Date to check. Accepts 'YYYY-MM-DD', 'Monday', 'tomorrow', 'today', 'Friday'.

        Returns:
            A dict with your scheduled events and free time windows for that day.
        """
        return calendar_tool.check_availability(creds, date=date)

    return [get_upcoming_events, create_event, check_availability]


def make_drive_tools(creds: Credentials) -> list:
    """Create Drive tool functions bound to OAuth credentials."""

    def search_files(query: str, max_results: int = 10) -> dict:
        """
        Search Google Drive for files by name or content.

        Args:
            query: Search term — file name, keyword, or topic.
            max_results: Max files to return (1-50, default 10).

        Returns:
            A dict with a 'files' list containing name, type, modified date, and link.
        """
        return drive_tool.search_files(creds, query=query, max_results=max_results)

    def list_recent_files(count: int = 10) -> dict:
        """
        List your most recently modified files in Google Drive.

        Args:
            count: Number of files to return (1-50, default 10).

        Returns:
            A dict with a 'files' list of recent files.
        """
        return drive_tool.list_recent_files(creds, count=count)

    def read_file(file_id: str) -> dict:
        """
        Read the text content of a Google Drive file (Google Docs, Sheets, plain text, etc.).

        Args:
            file_id: The Drive file ID (obtained from search_files or list_recent_files).

        Returns:
            A dict with the file 'name', 'type', and full 'content' text.
        """
        return drive_tool.read_file(creds, file_id=file_id)

    return [search_files, list_recent_files, read_file]


# ── Agent factory ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a helpful AI Task Automation Agent with access to the user's Gmail, Google Calendar, and Google Drive.

Today's date and time: {current_datetime}

## Your capabilities:
- **Gmail**: Read, search, and send emails
- **Google Calendar**: View upcoming events, create events, check availability
- **Google Drive**: Search files, list recent files, read document content

## Behavioral rules:
1. **Always confirm before taking action**: Before sending emails or creating calendar events, summarize what you're about to do and ask the user to confirm.
2. **Be specific and clear**: When showing emails or events, format them readably with key details.
3. **Handle errors gracefully**: If a tool call fails, explain what went wrong and suggest alternatives.
4. **Multi-step reasoning**: For complex tasks, break them down and execute steps sequentially.
5. **Be concise but complete**: Don't dump raw JSON — summarize and format results for the user.
6. **Remember context**: Use information from earlier in the conversation when relevant.
7. **Suggest next actions**: After completing a task, offer relevant follow-up actions.

## Formatting:
- Use bullet points for lists of emails/events/files
- Use **bold** for important items (names, dates, subjects)
- Always show dates/times in human-readable format
- For emails: show sender, subject, date, and a brief preview
- For events: show title, date/time, duration, and location if available

## Example multi-step tasks you can handle:
- "Check my latest emails and schedule a meeting mentioned in them"
- "Find the project proposal in Drive and send it to john@example.com"
- "What meetings do I have today, and am I free for lunch at noon?"
"""


def create_agent(creds: Credentials) -> Agent:
    """
    Create and return the configured ADK Agent with all tools.

    Args:
        creds: Valid Google OAuth2 credentials.

    Returns:
        Configured google.adk.agents.Agent instance.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in environment. Check your .env file.")

    # Collect all tool functions
    all_tools = (
        make_gmail_tools(creds)
        + make_calendar_tools(creds)
        + make_drive_tools(creds)
    )

    # Format system prompt with current datetime
    system_prompt = SYSTEM_PROMPT.format(
        current_datetime=datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    )

    agent = Agent(
        name=os.getenv("AGENT_NAME", "TaskAutomationAgent"),
        model="gemini-2.0-flash",
        description="AI Task Automation Agent with Gmail, Calendar, and Drive access",
        instruction=system_prompt,
        tools=all_tools,
    )

    return agent
