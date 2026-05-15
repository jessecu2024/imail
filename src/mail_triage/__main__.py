"""Allow `python -m mail_triage` to invoke the CLI."""

from mail_triage.cli import app

if __name__ == "__main__":
    app()
