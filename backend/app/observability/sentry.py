from __future__ import annotations

import logging
import os
from typing import Optional

try:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]
    LoggingIntegration = None  # type: ignore[assignment]

log = logging.getLogger(__name__)


def init_sentry(
    dsn: str,
    *,
    traces_sample_rate: float = 0.1,
    environment: str = "production",
    release: Optional[str] = None,
    server_name: Optional[str] = None,
) -> None:
    if not dsn:
        log.info("sentry.disabled (no dsn)")
        return
    if sentry_sdk is None:
        log.warning("sentry.disabled (sdk not installed)")
        return
    integrations = [LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)]
    try:
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        integrations.append(FastApiIntegration())
    except Exception:
        pass
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        environment=environment,
        release=release or os.environ.get("GITHUB_SHA") or None,
        server_name=server_name,
        integrations=integrations,
    )
    log.info("sentry.initialized env=%s server=%s", environment, server_name)


def init_from_env(server_name: Optional[str] = None) -> None:
    init_sentry(
        os.environ.get("SENTRY_DSN", ""),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        server_name=server_name,
    )
