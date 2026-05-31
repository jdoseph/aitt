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
from src.core.regime import RISK_OFF, RISK_ON
from src.core.signals import Alert, CycleResult

_SEVERITY_PREFIX = {"entry": "🟢 ENTRY", "secondary": "🟡 DIP", "warning": "🔴 WARNING"}


def format_alert(alert: Alert) -> str:
    prefix = _SEVERITY_PREFIX.get(alert.severity, alert.severity.upper())
    head = f"[{prefix}] {alert.message}"
    score_label = alert.score_label()
    if score_label:
        head += f"  |  {score_label}"
    if alert.action:
        head += f"  →  {alert.action}"
    return head


_REGIME_BADGE = {"RISK_ON": "🟢 RISK_ON", "NEUTRAL": "🟡 NEUTRAL", "RISK_OFF": "🔴 RISK_OFF"}


def composite_block(alert: Alert) -> str:
    """Headline, the scorecard checks, and the top 'why NOT buy' factors."""
    lines = [format_alert(alert)]
    # Surface the tape when it isn't clean risk-on.
    if alert.regime and alert.regime != "RISK_ON":
        lines.append(f"    Regime: {_REGIME_BADGE.get(alert.regime, alert.regime)}")
    lines.extend(f"    {line}" for line in alert.scorecard_lines)
    if alert.gate_flags:
        lines.append(f"    ⚠ Flagged (downgraded): {' · '.join(alert.gate_flags)}")
    if alert.bear_reasons:
        lines.append(f"    Why NOT: {' · '.join(alert.bear_reasons)}")
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


_DIAL = {RISK_ON: "🟢", RISK_OFF: "🔴"}


def portfolio_summary_lines(result: CycleResult) -> list[str]:
    """Human-readable paper-portfolio summary: exposure dial, NAV, holdings, suggestions."""
    dial = _DIAL.get(result.regime_label, "🟡")
    lines = [
        f"{dial} Paper portfolio — {result.exposure * 100:.0f}% invested "
        f"({result.regime_label}) · NAV ${result.portfolio_nav:,.0f}"
    ]
    exp = result.exposure_result
    if exp is not None and exp.pending is not None:
        lines.append(
            f"  ⏳ {exp.pending} building ({exp.days_pending}/{settings.regime_confirm_days}d) "
            "— dial unchanged until confirmed"
        )
    if result.portfolio_weights:
        holdings = ", ".join(
            f"{t} {w * 100:.0f}%"
            for t, w in sorted(result.portfolio_weights.items(), key=lambda kv: -kv[1])
        )
        lines.append(f"  Holdings: {holdings}")
    if result.rebalance_suggestions:
        lines.append("  Rebalance suggestions (paper — not executed):")
        lines.extend(f"    • {s}" for s in result.rebalance_suggestions)
    return lines


def log_portfolio_summary(result: CycleResult) -> None:
    """Emit the portfolio summary via the console logger."""
    if not settings.enable_portfolio:
        return
    for line in portfolio_summary_lines(result):
        logger.info(line)
