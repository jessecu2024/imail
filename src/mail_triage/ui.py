"""Rich-based terminal UI for the triage loop.

Layout per email:

    ┌─ From / Subject / Snippet ─────────────────────────┐
    │  Original body (truncated)                         │
    └────────────────────────────────────────────────────┘
    [1] POSITIVE   [2] NEUTRAL   [3] NEGATIVE

The user presses 1/2/3 to draft the corresponding reply, S to skip, Q to quit.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from mail_triage.gmail_client import EmailMsg
from mail_triage.reply_generator import ReplyTrio

# Single shared console so all output stays aligned.
console = Console()

TONE_COLORS = {
    "positive": "green",
    "neutral": "yellow",
    "negative": "red",
}
TONE_LABELS = {
    "positive": "1 · POSITIVE",
    "neutral": "2 · NEUTRAL",
    "negative": "3 · NEGATIVE",
}


def show_header(index: int, total: int, email: EmailMsg) -> None:
    """Render the source email."""
    header = Text()
    header.append("From    ", style="bold")
    header.append(f"{email.sender}\n")
    header.append("Subject ", style="bold")
    header.append(f"{email.subject}\n")
    header.append("\n")
    header.append(_truncate(email.body or email.snippet, 800), style="dim")

    title = f"[{index}/{total}]  {email.subject[:60]}"
    console.print(Panel(header, title=title, title_align="left", border_style="cyan"))


def show_replies(trio: ReplyTrio) -> None:
    """Render the three drafts side by side."""
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(ratio=1)
    table.add_column(ratio=1)
    table.add_column(ratio=1)

    table.add_row(
        Panel(trio.positive, title=TONE_LABELS["positive"], border_style=TONE_COLORS["positive"]),
        Panel(trio.neutral, title=TONE_LABELS["neutral"], border_style=TONE_COLORS["neutral"]),
        Panel(trio.negative, title=TONE_LABELS["negative"], border_style=TONE_COLORS["negative"]),
    )
    console.print(table)


def ask_choice() -> str:
    """Block on a single keypress-like choice. Returns the lowercase token."""
    return Prompt.ask(
        "Pick",
        choices=["1", "2", "3", "s", "q"],
        default="s",
        show_choices=True,
        show_default=False,
    ).lower()


def status(message: str, style: str = "") -> None:
    console.print(message, style=style)


def banner(message: str) -> None:
    console.rule(f"[bold]{message}[/bold]")


def _truncate(text: str, max_len: int) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + " …"
