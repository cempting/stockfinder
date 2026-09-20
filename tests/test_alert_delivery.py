import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from stockfinder.alert_delivery import (
    AlertDeliveryState,
    SmtpSettings,
    alert_digest,
    build_cached_alerts,
    deliver_if_changed,
    main,
)
from stockfinder.storage import (
    MarketHistoryCache,
    Repository,
    ScanSnapshot,
    ScanSnapshotStore,
)


class FakeSmtp:
    instances = []

    def __init__(self, host: str, port: int, timeout: int) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.login_args = None
        self.messages = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def starttls(self, *, context) -> None:
        assert context is not None
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message) -> None:
        self.messages.append(message)


def _alerts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Severity": "Critical",
                "Category": "Position loss",
                "Symbol": "TEST",
                "Message": "Return -12.0% breached -10.0%.",
            }
        ]
    )


def test_smtp_settings_require_non_secret_delivery_fields() -> None:
    with pytest.raises(ValueError, match="SMTP delivery requires"):
        SmtpSettings.from_environment({})

    settings = SmtpSettings.from_environment(
        {
            "STOCKFINDER_SMTP_HOST": "smtp.example.com",
            "STOCKFINDER_ALERT_FROM": "alerts@example.com",
            "STOCKFINDER_ALERT_TO": "one@example.com, two@example.com",
            "STOCKFINDER_SMTP_USER": "user",
            "STOCKFINDER_SMTP_PASSWORD": "secret",
        }
    )

    assert settings.port == 587
    assert settings.recipients == ("one@example.com", "two@example.com")


def test_delivery_is_deduplicated_and_sends_clear_recovery(tmp_path) -> None:
    FakeSmtp.instances.clear()
    state = AlertDeliveryState(tmp_path / "alert-delivery.json")
    settings = SmtpSettings(
        "smtp.example.com",
        587,
        "alerts@example.com",
        ("investor@example.com",),
        "user",
        "secret",
    )

    assert deliver_if_changed(
        _alerts(), settings, state, smtp_factory=FakeSmtp
    ) == "delivered"
    assert deliver_if_changed(
        _alerts().iloc[::-1], settings, state, smtp_factory=FakeSmtp
    ) == "unchanged"
    assert deliver_if_changed(
        pd.DataFrame(), settings, state, smtp_factory=FakeSmtp
    ) == "cleared"

    assert len(FakeSmtp.instances) == 2
    assert FakeSmtp.instances[0].started_tls is True
    assert FakeSmtp.instances[0].login_args == ("user", "secret")
    assert "Position loss" in FakeSmtp.instances[0].messages[0].get_content()
    assert "alerts cleared" in FakeSmtp.instances[1].messages[0]["Subject"]
    payload = json.loads(state.path.read_text(encoding="utf-8"))
    assert payload["digest"] == alert_digest(pd.DataFrame())


def test_build_cached_alerts_uses_persistent_state_without_provider_calls(
    tmp_path,
) -> None:
    repository = Repository(tmp_path / "stockfinder.db")
    repository.save_position("LOSS", 1.0, 100.0, "2026-01-01", "USD")
    MarketHistoryCache(tmp_path / "market").save(
        "USDEUR=X",
        pd.DataFrame(
            {"Close": [0.85]},
            index=pd.date_range("2026-09-19", periods=1),
        ),
    )
    snapshot = ScanSnapshot(
        universe=pd.DataFrame(
            {"Symbol": ["LOSS"], "Region": ["Europe"], "Sector": ["Technology"]}
        ),
        sectors=pd.DataFrame(),
        industries=pd.DataFrame(),
        candidates=pd.DataFrame(),
        completed_at=datetime(2026, 9, 20, tzinfo=UTC),
        source="Test",
        coverage=100.0,
        mode="standard",
        model_version="test",
        risk_profiles=pd.DataFrame(
            {"Symbol": ["LOSS"], "Last price": [80.0], "Market risk": [70.0]}
        ),
    )
    ScanSnapshotStore(tmp_path / "latest_scan").save(snapshot)

    alerts, warnings = build_cached_alerts(tmp_path, "EUR")

    assert warnings == ()
    assert set(alerts["Category"]) == {
        "Concentration",
        "Position loss",
        "Safety",
    }


def test_alert_delivery_cli_dry_run_needs_no_smtp_configuration(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setenv("STOCKFINDER_DATA_DIR", str(tmp_path))

    assert main(["--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "All cached-data alerts are clear." in output
    assert "No completed scan snapshot" in output

    assert main([]) == 0
    assert "no active alerts" in capsys.readouterr().out
    assert not (tmp_path / "alert-delivery.json").exists()