"""Typer-powered CLI: `mail-triage` after install, or `python -m mail_triage`."""

from __future__ import annotations

from typing import Annotated

import typer

from mail_triage import __version__, ui
from mail_triage.config import load_settings
from mail_triage.gmail_client import EmailMsg, GmailClient
from mail_triage.reply_generator import ReplyGenerator, ReplyTrio

app = typer.Typer(
    help="Triage your inbox: 3 LLM-drafted replies per email, pick one with a keypress.",
    no_args_is_help=False,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def _root(ctx: typer.Context) -> None:
    """Default action when no subcommand is given is `triage`."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(triage)


@app.command()
def version() -> None:
    """Print the installed version."""
    ui.status(f"mail-triage v{__version__}")


@app.command()
def triage(
    limit: Annotated[int, typer.Option(help="Max unread emails to triage.")] = 20,
    archive: Annotated[
        bool, typer.Option("--archive/--keep", help="Archive emails after drafting a reply.")
    ] = False,
) -> None:
    """Walk your unread inbox and draft a reply per email."""
    settings = load_settings()

    ui.banner("mail-triage")
    ui.status(f"Model: [cyan]{settings.anthropic_model}[/cyan]")
    ui.status(f"Sign-off: [cyan]{settings.user_signoff}[/cyan]")
    ui.status("Connecting to Gmail…", style="dim")

    gmail = GmailClient(
        credentials_path=settings.gmail_credentials_path,
        token_path=settings.gmail_token_path,
    )
    generator = ReplyGenerator(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        user_signoff=settings.user_signoff,
    )

    emails = gmail.fetch_unread(limit=limit)
    if not emails:
        ui.status("✨ Inbox is clean — no unread messages.", style="bold green")
        raise typer.Exit(code=0)

    ui.status(f"Found [bold]{len(emails)}[/bold] unread emails. Let's go.\n")

    for i, email in enumerate(emails, start=1):
        decision = _handle_one(email, generator, gmail, archive, i, len(emails))
        if decision == "quit":
            ui.status("\nStopped early. Bye.", style="dim")
            return

    ui.banner("Done")


def _handle_one(
    email: EmailMsg,
    generator: ReplyGenerator,
    gmail: GmailClient,
    archive: bool,
    index: int,
    total: int,
) -> str:
    """Process a single email; return 'continue' or 'quit'."""
    ui.show_header(index, total, email)

    try:
        trio: ReplyTrio = generator.generate(email)
    except Exception as exc:  # network / API failure shouldn't kill the loop
        ui.status(f"  ⚠ Reply generation failed: {exc}", style="red")
        return "continue"

    ui.show_replies(trio)
    choice = ui.ask_choice()

    if choice == "q":
        return "quit"
    if choice == "s":
        ui.status("  ↷ Skipped.\n", style="dim")
        return "continue"

    selected = {"1": trio.positive, "2": trio.neutral, "3": trio.negative}[choice]
    draft_id = gmail.create_draft(email, selected)
    ui.status(f"  ✓ Draft saved (id={draft_id[:12]}…).", style="green")

    if archive:
        gmail.archive(email)
        ui.status("  ✓ Archived.\n", style="green")
    else:
        gmail.mark_read(email)
        ui.status("  ✓ Marked as read.\n", style="green")

    return "continue"


if __name__ == "__main__":
    app()
