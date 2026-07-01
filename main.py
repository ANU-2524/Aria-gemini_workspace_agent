
import os
import sys
import asyncio
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown
from rich.rule import Rule
from rich.spinner import Spinner
from rich.live import Live
from rich.theme import Theme
from rich import print as rprint

# Load .env before any imports that use env vars
load_dotenv()

from auth import get_credentials
from agent import create_agent

# ── Rich console theme ────────────────────────────────────────────────────────

custom_theme = Theme({
    "user": "bold cyan",
    "agent": "bold green",
    "system": "bold yellow",
    "error": "bold red",
    "dim": "dim white",
    "accent": "bold magenta",
})

console = Console(theme=custom_theme)


# ── Startup banner ────────────────────────────────────────────────────────────

def print_banner():
    banner = Text()
    banner.append("  🤖 AI Task Automation Agent\n", style="bold magenta")
    banner.append("  Powered by Gemini 2.0 Flash + Google ADK\n", style="dim white")
    banner.append(f"  {datetime.now().strftime('%A, %B %d, %Y')}\n", style="dim white")

    console.print(Panel(
        banner,
        border_style="magenta",
        padding=(0, 2),
    ))

    console.print(
        "\n[dim]Commands:[/dim] "
        "[cyan]exit[/cyan] / [cyan]quit[/cyan] — end session  |  "
        "[cyan]clear[/cyan] — clear screen  |  "
        "[cyan]help[/cyan] — show example prompts\n"
    )


def print_help():
    examples = [
        ("📧 Gmail", [
            "What are my last 5 emails?",
            "Summarize my unread emails from today",
            "Search my emails for invoices",
            "Send an email to john@example.com saying I'll be late",
        ]),
        ("📅 Calendar", [
            "Do I have any meetings tomorrow?",
            "What's on my calendar this week?",
            "Schedule a team standup for Monday at 10am",
            "Check if I'm free this Friday afternoon",
            "Am I available for lunch at noon today?",
        ]),
        ("📂 Drive", [
            "Find the project proposal in my Drive",
            "What are my most recent files?",
            "Search for documents about Q4 budget",
            "Read the content of my meeting notes doc",
        ]),
        ("🔗 Multi-step", [
            "Check my latest emails and add any meetings to my calendar",
            "Find the proposal doc in Drive and email it to the team",
            "What meetings do I have today and am I free for a 2pm call?",
        ]),
    ]

    console.print(Rule("[bold yellow]Example Prompts[/bold yellow]"))
    for category, prompts in examples:
        console.print(f"\n[accent]{category}[/accent]")
        for p in prompts:
            console.print(f"  [dim]•[/dim] [italic]{p}[/italic]")
    console.print()


# ── ADK session runner ────────────────────────────────────────────────────────

async def run_agent_turn(runner, session_id: str, user_message: str) -> str:
    """
    Send one user message to the ADK agent and return its response text.

    Uses ADK's async runner with the current session for memory persistence.
    """
    from google.adk.runners import InMemoryRunner
    from google.genai.types import Content, Part

    content = Content(role="user", parts=[Part(text=user_message)])

    full_response = ""
    async for event in runner.run_async(
        user_id="user",
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response():
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, "text") and part.text:
                        full_response += part.text

    return full_response.strip()


# ── Main CLI loop ─────────────────────────────────────────────────────────────

async def main():
    print_banner()

    # ── Auth ──
    console.print("[system]Setting up Google authentication...[/system]")
    try:
        credentials_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
        creds = get_credentials(credentials_file=credentials_file, token_file=token_file)
        console.print("[green]✓ Google authentication ready[/green]\n")
    except FileNotFoundError as e:
        console.print(f"\n[error]Authentication Error:[/error] {e}")
        console.print("\n[dim]See README.md for setup instructions.[/dim]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[error]Authentication failed:[/error] {str(e)}")
        sys.exit(1)

    # ── Agent ──
    console.print("[system]Initializing agent...[/system]")
    try:
        agent = create_agent(creds)
    except ValueError as e:
        console.print(f"\n[error]Configuration Error:[/error] {e}")
        sys.exit(1)

    # ── ADK Runner ──
    try:
        from google.adk.runners import InMemoryRunner
        runner = InMemoryRunner(agent=agent)
        session = await runner.session_service.create_session(
            app_name=agent.name,
            user_id="user",
        )
        session_id = session.id
        console.print(f"[green]✓ Agent ready[/green] [dim](session: {session_id[:8]}...)[/dim]\n")
    except Exception as e:
        console.print(f"\n[error]Failed to start agent session:[/error] {str(e)}")
        console.print("[dim]Make sure google-adk is installed: pip install google-adk[/dim]")
        sys.exit(1)

    console.print(Rule("[dim]Session started — type your request below[/dim]"))
    console.print()

    # ── Chat loop ──
    while True:
        try:
            # User input
            console.print("[user]You:[/user] ", end="")
            user_input = input().strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n\n[dim]Session ended. Goodbye![/dim]")
            break

        if not user_input:
            continue

        # Special commands
        cmd = user_input.lower()
        if cmd in ("exit", "quit", "bye", "q"):
            console.print("\n[dim]Goodbye! Session ended.[/dim]")
            break
        elif cmd == "clear":
            console.clear()
            print_banner()
            continue
        elif cmd == "help":
            print_help()
            continue

        # Run agent with spinner
        console.print()
        response = ""
        with Live(
            Spinner("dots", text="[dim]Agent is thinking...[/dim]", style="cyan"),
            console=console,
            refresh_per_second=10,
            transient=True,
        ):
            try:
                response = await run_agent_turn(runner, session_id, user_input)
            except Exception as e:
                response = f"❌ Error: {str(e)}"

        # Display response
        console.print("[agent]Agent:[/agent]")
        if response:
            # Render markdown for nice formatting
            try:
                console.print(Panel(
                    Markdown(response),
                    border_style="green",
                    padding=(0, 1),
                ))
            except Exception:
                console.print(response)
        else:
            console.print("[dim](No response received)[/dim]")
        console.print()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n\n[dim]Interrupted. Goodbye![/dim]")