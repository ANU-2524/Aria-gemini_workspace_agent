import os
import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from rich.console import Console

console = Console()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_credentials(
    credentials_file: str = "credentials.json",
    token_file: str = "token.json",
) -> Credentials:
    """
    Load or create Google OAuth2 credentials.

    Flow:
    1. If token.json exists and is valid → return it
    2. If token.json is expired but refreshable → refresh and return
    3. If no token → run OAuth2 browser flow, save token, return
    """
    creds = None
    token_path = Path(token_file)
    credentials_path = Path(credentials_file)

    # --- Load existing token ---
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load token file: {e}[/yellow]")
            creds = None

    # --- Refresh or re-authorize ---
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            console.print("[cyan]Refreshing access token...[/cyan]")
            try:
                creds.refresh(Request())
                console.print("[green]✓ Token refreshed successfully.[/green]")
            except Exception as e:
                console.print(f"[yellow]Token refresh failed: {e}. Re-authorizing...[/yellow]")
                creds = None

        if not creds:
            if not credentials_path.exists():
                raise FileNotFoundError(
                    f"\n[bold red]credentials.json not found![/bold red]\n"
                    f"Please download it from Google Cloud Console:\n"
                    f"  Console → APIs & Services → Credentials → OAuth 2.0 Client IDs → Download JSON\n"
                    f"Save it as: [bold]{credentials_path.resolve()}[/bold]"
                )

            console.print("\n[cyan]Opening browser for Google authorization...[/cyan]")
            console.print("[dim]You only need to do this once.[/dim]\n")

            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(
                port=0,
                prompt="consent",
                access_type="offline",
            )
            console.print("[green]✓ Authorization successful![/green]")

        # --- Persist token ---
        token_path.write_text(creds.to_json())
        console.print(f"[dim]Token saved to {token_path}[/dim]")

    return creds


def get_credentials_info(creds: Credentials) -> dict:
    """Return human-readable info about current credentials."""
    return {
        "valid": creds.valid,
        "expired": creds.expired,
        "has_refresh_token": bool(creds.refresh_token),
        "scopes": creds.scopes,
    }
    