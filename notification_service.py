from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from hashlib import sha256
import json
import os
from pathlib import Path
import smtplib
from typing import Any, Iterable, Protocol

import requests

from database import connect
from state_contracts import MarketMoverAlert


SEVERITY_RANK = {"WATCH": 1, "ALERT": 2, "CRITICAL": 3}
NOTIFIABLE_STATUSES = {"ACTIVE", "CONFIRMED"}


@dataclass(frozen=True, slots=True)
class NotificationConfig:
    minimum_severity: str = "ALERT"
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    email_to: tuple[str, ...] = ()
    smtp_use_ssl: bool = True
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_ids: tuple[str, ...] = ()
    dashboard_url: str = ""

    @classmethod
    def from_env(cls) -> "NotificationConfig":
        email_to = tuple(item.strip() for item in os.getenv("PRICEGAUGER_ALERT_EMAIL_TO", "").split(",") if item.strip())
        chat_ids = tuple(item.strip() for item in os.getenv("PRICEGAUGER_TELEGRAM_CHAT_IDS", "").split(",") if item.strip())
        use_ssl = os.getenv("PRICEGAUGER_SMTP_USE_SSL", "1").strip().lower() not in {"0", "false", "no"}
        minimum = os.getenv("PRICEGAUGER_ALERT_MIN_SEVERITY", "ALERT").strip().upper()
        if minimum not in SEVERITY_RANK:
            minimum = "ALERT"
        return cls(
            minimum_severity=minimum,
            email_enabled=bool(email_to and os.getenv("PRICEGAUGER_SMTP_HOST")),
            smtp_host=os.getenv("PRICEGAUGER_SMTP_HOST", "").strip(),
            smtp_port=int(os.getenv("PRICEGAUGER_SMTP_PORT", "465")),
            smtp_username=os.getenv("PRICEGAUGER_SMTP_USERNAME", "").strip(),
            smtp_password=os.getenv("PRICEGAUGER_SMTP_PASSWORD", ""),
            smtp_from=os.getenv("PRICEGAUGER_SMTP_FROM", "").strip(),
            email_to=email_to,
            smtp_use_ssl=use_ssl,
            telegram_enabled=bool(chat_ids and os.getenv("PRICEGAUGER_TELEGRAM_BOT_TOKEN")),
            telegram_bot_token=os.getenv("PRICEGAUGER_TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_ids=chat_ids,
            dashboard_url=os.getenv("PRICEGAUGER_DASHBOARD_URL", "").strip(),
        )


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    channel: str
    recipient: str
    delivered: bool
    detail: str = ""


class AlertNotifier(Protocol):
    channel: str

    def send(self, alert: MarketMoverAlert, *, dashboard_url: str = "") -> list[DeliveryResult]: ...


class NotificationStore:
    """Persistent idempotency store shared by worker restarts and deployments."""

    def __init__(self, path: str | Path = "pricegauger.db") -> None:
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_mover_deliveries (
                    channel TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    alert_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    delivered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (channel, recipient, alert_id, fingerprint)
                );
                """
            )

    def _connect(self):
        return connect(self.path)

    def was_delivered(self, *, channel: str, recipient: str, alert_id: str, fingerprint: str) -> bool:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT 1 AS present
                FROM market_mover_deliveries
                WHERE channel=? AND recipient=? AND alert_id=? AND fingerprint=?
                """,
                (channel, recipient, alert_id, fingerprint),
            ).fetchone()
        return row is not None

    def mark_delivered(self, *, channel: str, recipient: str, alert_id: str, fingerprint: str) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO market_mover_deliveries(channel, recipient, alert_id, fingerprint)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(channel, recipient, alert_id, fingerprint) DO NOTHING
                """,
                (channel, recipient, alert_id, fingerprint),
            )


def alert_fingerprint(alert: MarketMoverAlert) -> str:
    payload = {
        "alert_id": alert.alert_id,
        "updated_at": alert.updated_at,
        "status": alert.status,
        "severity": alert.severity,
        "confirmation_status": alert.confirmation_status,
        "expected_direction": alert.expected_direction,
        "expected_move_low_pct": alert.expected_move_low_pct,
        "expected_move_high_pct": alert.expected_move_high_pct,
        "price_confirmation": alert.price_confirmation,
        "headline": alert.headline,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()[:24]


def should_notify(alert: MarketMoverAlert, *, minimum_severity: str = "ALERT") -> bool:
    threshold = SEVERITY_RANK.get(minimum_severity.upper(), SEVERITY_RANK["ALERT"])
    return alert.status in NOTIFIABLE_STATUSES and SEVERITY_RANK.get(alert.severity, 0) >= threshold


def format_alert_text(alert: MarketMoverAlert, *, dashboard_url: str = "") -> str:
    confirmation = alert.confirmation_status.replace("_", " ").title()
    lines = [
        f"{alert.severity} · {alert.market} MARKEDSFLYTTER",
        alert.headline,
        "",
        alert.summary,
        "",
        f"Retning: {alert.expected_direction}",
        f"Estimert bevegelse: {alert.expected_move_low_pct:+.2f}% til {alert.expected_move_high_pct:+.2f}%",
        f"Horisont: {alert.horizon_hours:g} timer",
        f"Status: {alert.status} · {confirmation}",
        f"Kildekvalitet: {alert.source_quality:.0%} · Nyhetsverdi: {alert.novelty:.0%}",
        f"Tilstandsnudge: {alert.state_delta:+.2f} · Kontekstfaktor: {alert.context_multiplier:.2f}",
    ]
    if abs(alert.price_confirmation) > 0:
        lines.append(f"Prisbekreftelse: {alert.price_confirmation:+.2f}")
    if dashboard_url:
        lines.extend(["", f"PriceGauger: {dashboard_url}"])
    return "\n".join(lines)


class EmailNotifier:
    channel = "email"

    def __init__(self, config: NotificationConfig, *, smtp_factory: Any = None) -> None:
        self.config = config
        self.smtp_factory = smtp_factory

    def send(self, alert: MarketMoverAlert, *, dashboard_url: str = "") -> list[DeliveryResult]:
        if not self.config.email_enabled:
            return []
        sender = self.config.smtp_from or self.config.smtp_username
        if not sender:
            return [DeliveryResult(self.channel, recipient, False, "missing sender") for recipient in self.config.email_to]
        message = EmailMessage()
        message["From"] = sender
        message["To"] = ", ".join(self.config.email_to)
        message["Subject"] = f"[{alert.severity}] {alert.market}: {alert.headline}"
        message.set_content(format_alert_text(alert, dashboard_url=dashboard_url))
        factory = self.smtp_factory or (smtplib.SMTP_SSL if self.config.smtp_use_ssl else smtplib.SMTP)
        try:
            with factory(self.config.smtp_host, self.config.smtp_port, timeout=20) as client:
                if not self.config.smtp_use_ssl:
                    client.starttls()
                if self.config.smtp_username:
                    client.login(self.config.smtp_username, self.config.smtp_password)
                client.send_message(message)
            return [DeliveryResult(self.channel, recipient, True) for recipient in self.config.email_to]
        except Exception as exc:
            return [DeliveryResult(self.channel, recipient, False, str(exc)) for recipient in self.config.email_to]


class TelegramNotifier:
    channel = "telegram"

    def __init__(self, config: NotificationConfig, *, session: Any = requests) -> None:
        self.config = config
        self.session = session

    def send(self, alert: MarketMoverAlert, *, dashboard_url: str = "") -> list[DeliveryResult]:
        if not self.config.telegram_enabled:
            return []
        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        text = format_alert_text(alert, dashboard_url=dashboard_url)
        results: list[DeliveryResult] = []
        for chat_id in self.config.telegram_chat_ids:
            try:
                response = self.session.post(
                    url,
                    timeout=20,
                    json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                )
                response.raise_for_status()
                results.append(DeliveryResult(self.channel, chat_id, True))
            except Exception as exc:
                results.append(DeliveryResult(self.channel, chat_id, False, str(exc)))
        return results


def configured_notifiers(config: NotificationConfig) -> tuple[AlertNotifier, ...]:
    notifiers: list[AlertNotifier] = []
    if config.email_enabled:
        notifiers.append(EmailNotifier(config))
    if config.telegram_enabled:
        notifiers.append(TelegramNotifier(config))
    return tuple(notifiers)


def dispatch_market_mover(
    alert: MarketMoverAlert,
    *,
    config: NotificationConfig | None = None,
    store: NotificationStore | None = None,
    notifiers: Iterable[AlertNotifier] | None = None,
) -> list[DeliveryResult]:
    selected_config = config or NotificationConfig.from_env()
    if not should_notify(alert, minimum_severity=selected_config.minimum_severity):
        return []
    selected_store = store or NotificationStore()
    selected_notifiers = tuple(notifiers) if notifiers is not None else configured_notifiers(selected_config)
    fingerprint = alert_fingerprint(alert)
    results: list[DeliveryResult] = []
    for notifier in selected_notifiers:
        pending_results = notifier.send(alert, dashboard_url=selected_config.dashboard_url)
        for result in pending_results:
            if selected_store.was_delivered(
                channel=result.channel,
                recipient=result.recipient,
                alert_id=alert.alert_id,
                fingerprint=fingerprint,
            ):
                results.append(DeliveryResult(result.channel, result.recipient, True, "duplicate skipped"))
                continue
            if result.delivered:
                selected_store.mark_delivered(
                    channel=result.channel,
                    recipient=result.recipient,
                    alert_id=alert.alert_id,
                    fingerprint=fingerprint,
                )
            results.append(result)
    return results
