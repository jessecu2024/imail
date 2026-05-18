# Slim Python base — keyring's `keyrings.alt` file backend gives us a
# storage path that doesn't depend on the host OS keychain (macOS Keychain
# / Windows Credential Manager / D-Bus Secret Service). Bind-mount
# /root/.config/imail when running so accounts.json + replies-*.json
# survive container restarts.
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Force keyring to its file backend — no system service available
    # inside the container.
    PYTHON_KEYRING_BACKEND=keyrings.alt.file.PlaintextKeyring \
    IMAIL_HOST=0.0.0.0 \
    IMAIL_PORT=8765 \
    IMAIL_CONFIG_DIR=/root/.config/imail

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install from PyPI (the latest release). `keyrings.alt` is needed at
# runtime because the in-container backend env var above points at it.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir "imail-cli" "keyrings.alt>=5"

RUN mkdir -p /root/.config/imail \
 && chmod 700 /root/.config/imail

EXPOSE 8765

# `--no-browser` because there's no display inside the container; the
# user opens http://localhost:8765 in their own browser via the mapped
# port.
ENTRYPOINT ["imail", "--no-browser"]
