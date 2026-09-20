from types import SimpleNamespace

import pandas as pd

from stockfinder.portfolio import (
    latest_conversion_rate,
    portfolio_alerts,
    portfolio_exposure_snapshot,
)
from stockfinder.widgets.portfolio_exposure import _load_fx_rates


def test_portfolio_exposure_snapshot_values_known_positions() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "MISSING"],
            "quantity": [2.0, 1.0, 1.0],
            "entry_price": [100.0, 100.0, 50.0],
        }
    )
    profiles = pd.DataFrame(
        {
            "Symbol": ["AAA", "BBB"],
            "Last price": [120.0, 60.0],
            "Market risk": [20.0, 50.0],
        }
    )
    universe = pd.DataFrame(
        {
            "Symbol": ["AAA", "BBB", "MISSING"],
            "Region": ["Europe", "Asia", "Europe"],
            "Sector": ["Technology", "Health Care", "Technology"],
            "Industry": ["Software", "Biotechnology", "Software"],
        }
    )

    snapshot = portfolio_exposure_snapshot(positions, profiles, universe, 1_000.0)

    assert snapshot.total_market_value == 300.0
    assert snapshot.total_pnl == 0.0
    assert snapshot.gross_exposure_pct == 30.0
    assert snapshot.largest_position_pct == 80.0
    assert snapshot.weighted_safety == 74.0
    assert snapshot.missing_quotes == 1
    assert snapshot.sectors["Allocation %"].tolist() == [80.0, 20.0]
    assert snapshot.regions["Allocation %"].tolist() == [80.0, 20.0]


def test_portfolio_exposure_converts_currencies_and_excludes_missing_fx() -> None:
    positions = pd.DataFrame(
        {
            "symbol": ["USD_STOCK", "EUR_STOCK", "NO_RATE"],
            "quantity": [1.0, 2.0, 1.0],
            "entry_price": [100.0, 80.0, 100.0],
            "currency": ["USD", "EUR", "JPY"],
        }
    )
    profiles = pd.DataFrame(
        {
            "Symbol": ["USD_STOCK", "EUR_STOCK", "NO_RATE"],
            "Last price": [110.0, 100.0, 120.0],
            "Market risk": [20.0, 20.0, 20.0],
        }
    )

    snapshot = portfolio_exposure_snapshot(
        positions,
        profiles,
        pd.DataFrame(),
        1_000.0,
        fx_rates={"EUR": 1.2},
        base_currency="USD",
    )

    assert snapshot.total_market_value == 350.0
    assert snapshot.total_pnl == 58.0
    assert snapshot.gross_exposure_pct == 35.0
    assert snapshot.missing_quotes == 0
    assert snapshot.missing_fx == 1
    assert snapshot.base_currency == "USD"


def test_latest_conversion_rate_uses_direct_then_inverse_history() -> None:
    direct = pd.DataFrame({"Close": [1.1, 1.2]})
    inverse = pd.DataFrame({"Close": [0.8]})

    assert latest_conversion_rate("EUR", "USD", direct, inverse) == (
        1.2,
        "EURUSD=X",
    )
    rate, source = latest_conversion_rate(
        "EUR", "USD", pd.DataFrame(), inverse
    )
    assert rate == 1.25
    assert source == "USDEUR=X"
    assert latest_conversion_rate(
        "EUR", "USD", pd.DataFrame(), pd.DataFrame()
    ) == (None, None)


def test_load_fx_rates_rejects_fallback_and_uses_verified_inverse() -> None:
    positions = pd.DataFrame({"currency": ["KRW"]})

    def get_history(symbol: str, period: str) -> SimpleNamespace:
        assert period == "5d"
        if symbol == "KRWEUR=X":
            return SimpleNamespace(
                data=pd.DataFrame({"Close": [999.0]}),
                is_fallback=True,
            )
        assert symbol == "EURKRW=X"
        return SimpleNamespace(
            data=pd.DataFrame({"Close": [1_600.0]}),
            is_fallback=False,
        )

    rates, sources = _load_fx_rates(
        positions,
        "EUR",
        SimpleNamespace(get_history=get_history),
    )

    assert rates == {"EUR": 1.0, "KRW": 1 / 1_600.0}
    assert sources == ["EURKRW=X"]


def test_portfolio_alerts_cover_positions_and_watchlist_levels() -> None:
    positions = pd.DataFrame(
        {"symbol": ["LOSS"], "quantity": [1.0], "entry_price": [100.0]}
    )
    profiles = pd.DataFrame(
        {
            "Symbol": ["LOSS", "STOP", "TARGET", "ENTRY"],
            "Last price": [80.0, 80.0, 120.0, 101.0],
            "Market risk": [70.0, 20.0, 20.0, 20.0],
        }
    )
    universe = pd.DataFrame(
        {"Symbol": ["LOSS"], "Region": ["Europe"], "Sector": ["Technology"]}
    )
    exposure = portfolio_exposure_snapshot(positions, profiles, universe, 1_000.0)
    watchlist = pd.DataFrame(
        {
            "symbol": ["STOP", "TARGET", "ENTRY"],
            "entry_price": [None, None, 100.0],
            "target_price": [None, 110.0, None],
            "stop_price": [90.0, None, None],
        }
    )
    rules = {
        "max_position_allocation_pct": 25.0,
        "minimum_position_safety": 40.0,
        "position_loss_pct": 10.0,
        "watchlist_entry_tolerance_pct": 2.0,
    }

    alerts = portfolio_alerts(exposure, watchlist, profiles, rules)

    assert set(alerts["Category"]) == {
        "Concentration",
        "Entry proximity",
        "Position loss",
        "Safety",
        "Watchlist stop",
        "Watchlist target",
    }
    assert alerts.iloc[0]["Severity"] == "Critical"