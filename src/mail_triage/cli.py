"""Entrypoint: `mail-triage` boots the FastAPI server and opens a browser tab."""

from __future__ import annotations

import argparse
import contextlib
import logging
import threading
import time
import webbrowser

import uvicorn

from mail_triage import __version__
from mail_triage.config import load_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="mail-triage", description="Inbox triage as a local app.")
    parser.add_argument("--host", default=None, help="Bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    parser.add_argument("--version", action="version", version=f"mail-triage {__version__}")
    args = parser.parse_args()

    settings = load_settings(require_anthropic=False)
    host = args.host or settings.server_host
    port = args.port or settings.server_port
    url = f"http://{host}:{port}"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-5s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("mail-triage")
    logger.info("mail-triage %s starting at %s", __version__, url)
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY is unset — UI will load but triage will fail.")

    if not args.no_browser:
        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()

    uvicorn.run(
        "mail_triage.server:app",
        host=host,
        port=port,
        log_level="info",
        access_log=False,
    )


def _open_browser_when_ready(url: str) -> None:
    """Tiny delay so uvicorn binds before the browser hits the URL."""
    time.sleep(0.8)
    with contextlib.suppress(webbrowser.Error):
        webbrowser.open(url)


if __name__ == "__main__":
    main()
