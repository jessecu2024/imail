"""Email provider implementations (Gmail, IMAP).

All providers conform to `providers.base.MailProvider` so the rest of the
app stays provider-agnostic.
"""

from imail.providers.base import EmailMsg, MailProvider, ProviderError

__all__ = ["EmailMsg", "MailProvider", "ProviderError"]
