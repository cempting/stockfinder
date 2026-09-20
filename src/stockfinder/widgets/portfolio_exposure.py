"""Portfolio exposure and watchlist monitoring widget."""

import math
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stockfinder.analysis import classify_market_regime
from stockfinder.dashboard import WidgetSpec
from stockfinder.dashboard_runtime import DashboardServices
from stockfinder.navigation import AnalysisContext
from stockfinder.portfolio import (
    PortfolioExposure,
    fx_conversion_symbols,
    latest_conversion_rate,
    portfolio_exposure_snapshot,
)

REGIME_SYMBOLS = ("SPY", "IWM", "HYG", "IEF", "UUP", "^VIX")
CURRENCIES = ("EUR", "USD", "GBP", "CHF", "JPY", "CAD", "AUD", "HKD", "KRW")


def render_portfolio_exposure(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    positions = services.get_positions()
    watchlist = services.get_watchlist()
    default_base_currency = str(spec.settings.get("base_currency", "EUR")).upper()
    base_currency = st.selectbox(
        "Portfolio base currency",
        CURRENCIES,
        index=CURRENCIES.index(default_base_currency),
        key=f"{spec.widget_id}_base_currency",
    )
    _render_position_editor(
        positions,
        context,
        services,
        spec.widget_id,
        base_currency,
    )
    if positions.empty:
        st.info("No positions recorded. Add one above to start monitoring exposure.")
        _render_watchlist(watchlist, context, services, spec.widget_id)
        return

    universe_result, _, _, _, scan_warning = services.load_scan(services.load_mode)
    histories = {
        symbol: services.get_history(symbol, "1y").data for symbol in REGIME_SYMBOLS
    }
    regime = classify_market_regime(histories)
    control_key = {
        "Risk-on": "supportive",
        "Mixed": "neutral",
        "Risk-off": "defensive",
    }.get(regime.label, "defensive")
    control = services.get_analysis_config()["market_controls"][control_key]
    limit = float(control["max_gross_exposure_pct"])
    fx_rates, fx_sources = _load_fx_rates(positions, base_currency, services)

    initial = portfolio_exposure_snapshot(
        positions,
        services.get_risk_profiles(),
        universe_result.data,
        1.0,
        fx_rates=fx_rates,
        base_currency=base_currency,
    )
    suggested_account = max(
        initial.total_market_value,
        initial.total_market_value / (limit / 100) if limit > 0 else 1.0,
        1.0,
    )
    account_value = st.number_input(
        f"Account value ({base_currency})",
        min_value=1.0,
        value=float(round(suggested_account, 2)),
        help=(
            "Enter a currency-normalized account value. Stored positions do not "
            "include FX conversion rates."
        ),
        key=f"{spec.widget_id}_{base_currency}_account_value",
    )
    snapshot = portfolio_exposure_snapshot(
        positions,
        services.get_risk_profiles(),
        universe_result.data,
        account_value,
        fx_rates=fx_rates,
        base_currency=base_currency,
    )
    _render_metrics(snapshot, regime.label, limit)
    if snapshot.gross_exposure_pct > limit:
        st.warning(
            f"Gross exposure exceeds the {regime.label} control by "
            f"{snapshot.gross_exposure_pct - limit:.1f} percentage points."
        )
    if snapshot.missing_quotes:
        st.warning(
            f"{snapshot.missing_quotes} position(s) lack cached quotes and are "
            "excluded from valuation and allocation."
        )
    if snapshot.missing_fx:
        st.warning(
            f"{snapshot.missing_fx} quoted position(s) lack a verified conversion "
            f"rate to {base_currency} and are excluded from account totals."
        )
    st.caption(
        f"{regime.label} control · maximum gross exposure {limit:.0f}% · "
        f"risk per position {control['risk_per_position_pct']:.2f}% · "
        f"{control['new_entry_policy']}"
    )
    st.caption("FX evidence: " + (" · ".join(fx_sources) or "No conversion required"))
    if scan_warning:
        st.caption(scan_warning)
    _render_allocations(snapshot, spec.widget_id)
    _render_positions(snapshot.positions)
    _render_watchlist(watchlist, context, services, spec.widget_id)


def _render_position_editor(
    positions: pd.DataFrame,
    context: AnalysisContext,
    services: DashboardServices,
    widget_id: str,
    default_currency: str,
) -> None:
    default_symbol = context.get("instrument") or "SPY"
    with st.expander("Manage positions", expanded=positions.empty):
        with st.form(f"{widget_id}_position_form"):
            symbol_column, quantity_column, entry_column, currency_column = (
                st.columns(4)
            )
            symbol = symbol_column.text_input(
                "Symbol",
                value=default_symbol,
                key=f"{widget_id}_position_symbol",
            ).strip().upper()
            quantity = quantity_column.number_input(
                "Quantity",
                min_value=0.01,
                value=1.0,
                key=f"{widget_id}_position_quantity",
            )
            entry_price = entry_column.number_input(
                "Entry price",
                min_value=0.01,
                value=100.0,
                key=f"{widget_id}_position_entry",
            )
            suggested_currency = _suggested_currency(default_symbol, default_currency)
            currency = currency_column.selectbox(
                "Currency",
                CURRENCIES,
                index=CURRENCIES.index(suggested_currency),
                key=f"{widget_id}_position_currency",
            )
            entry_date = st.date_input(
                "Entry date",
                value=date.today(),
                key=f"{widget_id}_position_date",
            )
            if st.form_submit_button(
                "Save position",
                icon=":material/save:",
                type="primary",
            ):
                if not symbol:
                    st.error("Enter a symbol.")
                else:
                    services.save_position(
                        symbol,
                        float(quantity),
                        float(entry_price),
                        entry_date.isoformat(),
                        currency,
                    )
                    st.rerun()

        if not positions.empty:
            remove_column, action_column = st.columns([3, 1])
            remove_symbol = remove_column.selectbox(
                "Close or remove position",
                positions["symbol"].astype(str).tolist(),
                key=f"{widget_id}_remove_position",
            )
            if action_column.button(
                "Remove",
                icon=":material/delete:",
                key=f"{widget_id}_remove_position_button",
            ):
                services.delete_position(remove_symbol)
                st.rerun()


def _render_metrics(
    snapshot: PortfolioExposure,
    regime: str,
    exposure_limit: float,
) -> None:
    value, pnl, exposure, concentration, safety = st.columns(5)
    value.metric(
        f"Market value ({snapshot.base_currency})",
        f"{snapshot.total_market_value:,.2f}",
    )
    pnl.metric(
        f"Unrealized P&L ({snapshot.base_currency})",
        f"{snapshot.total_pnl:+,.2f}",
    )
    exposure.metric(
        "Gross exposure",
        f"{snapshot.gross_exposure_pct:.1f}%",
        f"{snapshot.gross_exposure_pct - exposure_limit:+.1f} pp vs limit",
        delta_color="inverse",
    )
    concentration.metric("Largest position", f"{snapshot.largest_position_pct:.1f}%")
    safety.metric(
        "Weighted safety",
        (
            f"{snapshot.weighted_safety / 10:.1f}/10"
            if math.isfinite(snapshot.weighted_safety)
            else "Unavailable"
        ),
        regime,
    )


def _render_allocations(snapshot: PortfolioExposure, widget_id: str) -> None:
    sector_column, region_column = st.columns(2)
    sector_column.plotly_chart(
        _allocation_chart(snapshot.sectors, "Sector", "Sector allocation"),
        width="stretch",
        key=f"{widget_id}_sector_allocation",
    )
    region_column.plotly_chart(
        _allocation_chart(snapshot.regions, "Region", "Regional allocation"),
        width="stretch",
        key=f"{widget_id}_region_allocation",
    )


def _allocation_chart(frame: pd.DataFrame, dimension: str, title: str) -> go.Figure:
    figure = go.Figure(
        go.Bar(
            x=frame["Allocation %"],
            y=frame[dimension],
            orientation="h",
            text=frame["Allocation %"].map(lambda value: f"{value:.1f}%"),
            textposition="auto",
        )
    )
    figure.update_layout(
        title=title,
        height=300,
        margin={"l": 0, "r": 0, "t": 45, "b": 0},
        xaxis={"range": [0, 100], "title": "Allocation %"},
        yaxis={"autorange": "reversed", "title": None},
    )
    return figure


def _render_positions(positions: pd.DataFrame) -> None:
    base_currency = str(positions.attrs.get("base_currency", "Base"))
    display = positions.rename(
        columns={
            "symbol": "Symbol",
            "quantity": "Quantity",
            "entry_price": "Entry",
            "last_price": "Last",
            "currency": "Currency",
            "fx_rate": f"FX to {base_currency}",
            "market_value": f"Market value ({base_currency})",
            "pnl": f"P&L ({base_currency})",
            "allocation_%": "Allocation %",
            "market_risk": "Observed risk",
        }
    )
    columns = [
        "Symbol",
        "Quantity",
        "Entry",
        "Last",
        "Currency",
        f"FX to {base_currency}",
        f"Market value ({base_currency})",
        f"P&L ({base_currency})",
        "Allocation %",
        "Observed risk",
        "Region",
        "Sector",
        "Industry",
    ]
    st.dataframe(display.reindex(columns=columns), hide_index=True, width="stretch")


def _render_watchlist(
    watchlist: pd.DataFrame,
    context: AnalysisContext,
    services: DashboardServices,
    widget_id: str,
) -> None:
    with st.expander(f"Watchlist · {len(watchlist)} candidates", expanded=False):
        default_symbol = context.get("instrument") or "SPY"
        with st.form(f"{widget_id}_watchlist_form"):
            symbol_column, entry_column, target_column, stop_column = st.columns(4)
            symbol = symbol_column.text_input(
                "Candidate symbol",
                value=default_symbol,
                key=f"{widget_id}_watchlist_symbol",
            ).strip().upper()
            entry = entry_column.number_input(
                "Planned entry",
                min_value=0.0,
                value=0.0,
                key=f"{widget_id}_watchlist_entry",
            )
            target = target_column.number_input(
                "Target",
                min_value=0.0,
                value=0.0,
                key=f"{widget_id}_watchlist_target",
            )
            stop = stop_column.number_input(
                "Invalidation stop",
                min_value=0.0,
                value=0.0,
                key=f"{widget_id}_watchlist_stop",
            )
            notes = st.text_input(
                "Notes",
                key=f"{widget_id}_watchlist_notes",
            )
            if st.form_submit_button("Save candidate", icon=":material/save:"):
                if not symbol:
                    st.error("Enter a symbol.")
                else:
                    services.save_watchlist(
                        symbol,
                        notes,
                        _optional_price(entry),
                        _optional_price(target),
                        _optional_price(stop),
                    )
                    st.rerun()

        if watchlist.empty:
            st.caption("No watchlist candidates recorded.")
            return
        st.dataframe(watchlist, hide_index=True, width="stretch")
        selected_symbol = st.selectbox(
            "Inspect candidate",
            watchlist["symbol"].astype(str).tolist(),
            key=f"{widget_id}_watchlist_candidate",
        )
        inspect_column, remove_column = st.columns(2)
        if inspect_column.button(
            "Inspect",
            icon=":material/search:",
            key=f"{widget_id}_inspect_candidate",
        ):
            context.select("instrument", selected_symbol)
            st.rerun()
        if remove_column.button(
            "Remove",
            icon=":material/delete:",
            key=f"{widget_id}_remove_candidate",
        ):
            services.delete_watchlist(selected_symbol)
            st.rerun()


def _optional_price(value: float) -> float | None:
    return float(value) if value > 0 else None


def _load_fx_rates(
    positions: pd.DataFrame,
    base_currency: str,
    services: DashboardServices,
) -> tuple[dict[str, float], list[str]]:
    currencies = (
        positions.get("currency", pd.Series(dtype=str))
        .fillna("USD")
        .astype(str)
        .str.upper()
        .unique()
    )
    rates = {base_currency: 1.0}
    sources = []
    for currency in currencies:
        if currency == base_currency:
            continue
        direct_symbol, inverse_symbol = fx_conversion_symbols(currency, base_currency)
        direct = services.get_history(direct_symbol, "5d")
        direct_history = pd.DataFrame() if direct.is_fallback else direct.data
        rate, source = latest_conversion_rate(
            currency,
            base_currency,
            direct_history,
            pd.DataFrame(),
        )
        if rate is None:
            inverse = services.get_history(inverse_symbol, "5d")
            inverse_history = pd.DataFrame() if inverse.is_fallback else inverse.data
            rate, source = latest_conversion_rate(
                currency,
                base_currency,
                pd.DataFrame(),
                inverse_history,
            )
        if rate is not None and source is not None:
            rates[currency] = rate
            sources.append(source)
    return rates, sources


def _suggested_currency(symbol: str, default_currency: str) -> str:
    suffixes = {
        ".KS": "KRW",
        ".KQ": "KRW",
        ".T": "JPY",
        ".HK": "HKD",
        ".L": "GBP",
        ".DE": "EUR",
        ".PA": "EUR",
        ".AS": "EUR",
        ".SW": "CHF",
        ".TO": "CAD",
        ".AX": "AUD",
    }
    return next(
        (currency for suffix, currency in suffixes.items() if symbol.endswith(suffix)),
        "USD" if "." not in symbol else default_currency,
    )