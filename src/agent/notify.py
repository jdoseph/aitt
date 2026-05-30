"""Notification dispatch.

Channels implement the :class:`Notifier` interface so new ones (email, Discord,
Slack, SMS) can be added without touching callers. v1 ships console logging +
desktop notifications via ``plyer``. 3-star alerts are made more prominent
(longer-lived desktop toast).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from loguru import logger

from src.core.config import Settings, settings
from src.core.signals import Alert

_SEVERITY_PREFIX = {"entry": "🟢 ENTRY", "secondary": "🟡 DIP", "warning": "🔴 WARNING"}


def format_alert(alert: Alert) -> str:
    prefix = _SEVERITY_PREFIX.get(alert.severity, alert.severity.upper())
    head = f"[{prefix}] {alert.message}"
    if alert.action:
        head += f"  →  {alert.action}"
    return head


def composite_block(alert: Alert) -> str:
    """Headline plus the indented scorecard checks (when the alert was graded)."""
    lines = [format_alert(alert)]
    lines.extend(f"    {line}" for line in alert.scorecard_lines)
    return "\n".join(lines)


class Notifier(ABC):
    """A delivery channel for alerts."""

    @abstractmethod
    def send(self, alert: Alert) -> None: ...


class ConsoleNotifier(Notifier):
    """Logs alerts through loguru (always safe, no external deps)."""

    def send(self, alert: Alert) -> None:
        block = composite_block(alert)
        if alert.severity == "warning":
            logger.warning(block)
        else:
            logger.info(block)


class DesktopNotifier(Notifier):
    """OS desktop toast via plyer. 3-star alerts linger longer; failures degrade
    to a logged warning rather than crashing the agent."""

    APP_NAME = "AI Infra Tracker"

    def send(self, alert: Alert) -> None:
        try:
            from plyer import notification

            timeout = 25 if alert.confidence >= 3 else 12
            title = f"{'⭐' * alert.confidence or '•'} {alert.ticker} — {alert.strategy}"
            body = alert.message if not alert.action else f"{alert.message}\n→ {alert.action}"
            notification.notify(
                title=title[:64],
                message=body[:240],
                app_name=self.APP_NAME,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - desktop backend is best-effort
            logger.warning("desktop notification failed ({}): {}", type(exc).__name__, exc)


def build_notifiers(cfg: Settings | None = None) -> list[Notifier]:
    """Construct the enabled notifiers from config."""
    cfg = cfg or settings
    notifiers: list[Notifier] = []
    if cfg.alert_console:
        notifiers.append(ConsoleNotifier())
    if cfg.alert_desktop:
        notifiers.append(DesktopNotifier())
    return notifiers


def dispatch(alerts: list[Alert], notifiers: list[Notifier] | None = None) -> int:
    """Send each alert through each notifier. Returns the count dispatched."""
    notifiers = notifiers if notifiers is not None else build_notifiers()
    for alert in alerts:
        for n in notifiers:
            n.send(alert)
    return len(alerts)
