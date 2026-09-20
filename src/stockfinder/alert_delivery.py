"""Optional deduplicated email delivery for cached Stockfinder alerts."""

import argparse
import hashlib
import json
import os
import smtplib
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

import pandas as pd

from stockfinder.config import AnalysisConfigStore, configured_alert_rules
from stockfinder.portfolio import (
    fx_conversion_symbols,
    latest_conversion_rate,
    portfolio_alerts,
    portfolio_exposure_snapshot,
)
from stockfinder.runtime import application_data_dir
from stockfinder.storage import (
    MarketHistoryCache,
    Repository,
    ScanSnapshotStore,
)


@dataclass(frozen=True)
class SmtpSettings:
    """SMTP connection settings sourced without exposing credentials."""

    host: str
    port: int
    sender: str
    recipients: tuple[str, ...]
    username: str | None = None
    password: str | None = None
    starttls: bool = True

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "SmtpSettings":
        host = environment.get("STOCKFINDER_SMTP_HOST", "").strip()
        sender = environment.get("STOCKFINDER_ALERT_FROM", "").strip()
        recipients = tuple(
            item.strip()
            for item in environment.get("STOCKFINDER_ALERT_TO", "").split(",")
            if item.strip()
        )
        if not host or not sender or not recipients:
            raise ValueError(
                "SMTP delivery requires STOCKFINDER_SMTP_HOST, "
                "STOCKFINDER_ALERT_FROM, and STOCKFINDER_ALERT_TO"
            )
        username = environment.get("STOCKFINDER_SMTP_USER", "").strip() or None
        password = environment.get("STOCKFINDER_SMTP_PASSWORD") or None
        if username and not password:
            raise ValueError("STOCKFINDER_SMTP_PASSWORD is required with SMTP user")
        try:
            port = int(environment.get("STOCKFINDER_SMTP_PORT", "587"))
        except ValueError as error:
            raise ValueError("STOCKFINDER_SMTP_PORT must be an integer") from error
        if not 1 <= port <= 65535:
            raise ValueError("STOCKFINDER_SMTP_PORT must be between 1 and 65535")
        starttls = environment.get("STOCKFINDER_SMTP_STARTTLS", "true").lower()
        return cls(
            host=host,
            port=port,
            sender=sender,
            recipients=recipients,
            username=username,
            password=password,
            starttls=starttls not in {"0", "false", "no"},
        )


class AlertDeliveryState:
    """Persist only the digest of the last successfully delivered alert set."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_digest(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            digest = payload.get("digest")
            return str(digest) if digest else None
        except (OSError, json.JSONDecodeError, AttributeError):
            return None

    def save_digest(self, digest: str) -> None:
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        payload = {
            "digest": digest,
            "delivered_at": datetime.now(UTC).isoformat(),
        }
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()


def alert_digest(alerts: pd.DataFrame) -> str:
    """Return a stable digest for one ordered or unordered alert set."""
    columns = ["Severity", "Category", "Symbol", "Message"]
    normalized = alerts.reindex(columns=columns).fillna("").astype(str)
    normalized = normalized.sort_values(columns).reset_index(drop=True)
    payload = normalized.to_json(orient="records")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def format_alert_email(alerts: pd.DataFrame) -> tuple[str, str]:
    """Build a concise plain-text subject and body from alert evidence."""
    if alerts.empty:
        return "Stockfinder alerts cleared", "All cached-data alerts are clear."
    counts = alerts["Severity"].value_counts()
    subject = (
        f"Stockfinder alerts: {int(counts.get('Critical', 0))} critical, "
        f"{int(counts.get('Warning', 0))} warning, "
        f"{int(counts.get('Review', 0))} review"
    )
    lines = [subject, ""]
    for row in alerts.itertuples(index=False):
        lines.append(
            f"[{row.Severity}] {row.Symbol} · {row.Category} · {row.Message}"
        )
    lines.extend(
        [
            "",
            "Evidence comes from the latest cached end-of-day scan.",
            "This message is not real-time market monitoring.",
        ]
    )
    return subject, "\n".join(lines)


def deliver_if_changed(
    alerts: pd.DataFrame,
    settings: SmtpSettings,
    state: AlertDeliveryState,
    *,
    smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
) -> str:
    """Deliver changed alerts once, including one recovery message when cleared."""
    digest = alert_digest(alerts)
    previous = state.load_digest()
    if previous == digest:
        return "unchanged"
    if alerts.empty and previous is None:
        return "clear"
    subject, body = format_alert_email(alerts)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.recipients)
    message.set_content(body)
    with smtp_factory(settings.host, settings.port, timeout=30) as client:
        if settings.starttls:
            client.starttls(context=ssl.create_default_context())
        if settings.username:
            client.login(settings.username, settings.password)
        client.send_message(message)
    state.save_digest(digest)
    return "cleared" if alerts.empty else "delivered"


def smtp_settings_from_environment() -> SmtpSettings:
    """Load SMTP settings from the current process environment."""
    return SmtpSettings.from_environment(os.environ)


def build_cached_alerts(
    data_dir: str | Path,
    base_currency: str = "EUR",
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Build alerts without provider calls from the latest persistent state."""
    path = Path(data_dir)
    repository = Repository(path / "stockfinder.db")
    positions = repository.positions()
    watchlist = repository.watchlist()
    snapshot = ScanSnapshotStore(path / "latest_scan").load()
    if snapshot is None:
        risk_profiles = pd.DataFrame()
        universe = pd.DataFrame()
        warnings = ["No completed scan snapshot is available."]
    else:
        risk_profiles = snapshot.risk_profiles
        universe = snapshot.universe
        warnings = [snapshot.warning] if snapshot.warning else []
    rates, missing_currencies = _cached_fx_rates(
        positions,
        base_currency,
        MarketHistoryCache(path / "market"),
    )
    exposure = portfolio_exposure_snapshot(
        positions,
        risk_profiles,
        universe,
        account_value=1.0,
        fx_rates=rates,
        base_currency=base_currency,
    )
    if missing_currencies:
        warnings.append(
            "Missing cached FX rates: " + ", ".join(sorted(missing_currencies))
        )
    config = AnalysisConfigStore(path / "analysis_config.json").load()
    return (
        portfolio_alerts(
            exposure,
            watchlist,
            risk_profiles,
            configured_alert_rules(config),
        ),
        tuple(warnings),
    )


def _cached_fx_rates(
    positions: pd.DataFrame,
    base_currency: str,
    cache: MarketHistoryCache,
) -> tuple[dict[str, float], set[str]]:
    currencies = (
        positions.get("currency", pd.Series(dtype=str))
        .fillna("USD")
        .astype(str)
        .str.upper()
        .unique()
    )
    base = base_currency.upper()
    rates = {base: 1.0}
    missing = set()
    for currency in currencies:
        if currency == base:
            continue
        direct_symbol, inverse_symbol = fx_conversion_symbols(currency, base)
        direct_history = cache.load(direct_symbol)
        inverse_history = cache.load(inverse_symbol)
        rate, _ = latest_conversion_rate(
            currency,
            base,
            direct_history if direct_history is not None else pd.DataFrame(),
            inverse_history if inverse_history is not None else pd.DataFrame(),
        )
        if rate is None:
            missing.add(currency)
        else:
            rates[currency] = rate
    return rates, missing


def main(argv: list[str] | None = None) -> int:
    """Evaluate cached alerts and optionally send a changed email digest."""
    parser = argparse.ArgumentParser(
        description="Evaluate and email Stockfinder cached-data alerts."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the current report without sending or changing delivery state.",
    )
    parser.add_argument(
        "--base-currency",
        default=os.environ.get("STOCKFINDER_ALERT_BASE_CURRENCY", "EUR"),
        help="ISO currency used for portfolio concentration calculations.",
    )
    arguments = parser.parse_args(argv)
    data_dir = application_data_dir()
    alerts, warnings = build_cached_alerts(data_dir, arguments.base_currency)
    subject, body = format_alert_email(alerts)
    if arguments.dry_run:
        print(subject)
        print(body)
        for warning in warnings:
            print(f"Warning: {warning}")
        return 0

    state = AlertDeliveryState(data_dir / "alert-delivery.json")
    digest = alert_digest(alerts)
    previous = state.load_digest()
    if previous == digest:
        print("Alert delivery skipped: unchanged.")
        return 0
    if alerts.empty and previous is None:
        print("Alert delivery skipped: no active alerts.")
        return 0
    try:
        settings = smtp_settings_from_environment()
        status = deliver_if_changed(alerts, settings, state)
    except (ValueError, OSError, smtplib.SMTPException) as error:
        print(f"Alert delivery failed: {error}")
        return 2
    print(f"Alert delivery status: {status}.")
    for warning in warnings:
        print(f"Warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())