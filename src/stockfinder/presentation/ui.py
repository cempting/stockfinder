"""Streamlit user interface for Stockfinder."""

import json
from collections.abc import MutableMapping
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from stockfinder.analysis import (
    AnalysisResult,
    analyze_long_swing_setup,
    analyze_metals,
    analyze_security,
    calculate_position_plan,
    calculate_reward_risk,
    classify_market_regime,
    normalized_performance_from_histories,
)
from stockfinder.data import (
    METAL_PROXIES,
    METALS_BENCHMARK,
    SECURITY_UNIVERSE,
    DataResult,
    clear_market_data_caches,
    fundamental_metrics,
    fundamental_pillar_metrics,
    get_batch_histories,
    get_global_universe,
    get_history,
    get_news,
    get_profile,
)
from stockfinder.infrastructure.config import AnalysisConfigStore, configured_proxy
from stockfinder.infrastructure.runtime import application_data_dir
from stockfinder.infrastructure.storage import (
    GettexInstrumentStore,
    Repository,
    ScanSnapshotStore,
)
from stockfinder.models import Score, SwingSetup
from stockfinder.presentation.charting import (
    add_relative_volume_lines,
    add_volume_bars,
    price_volume_subplots,
)
from stockfinder.presentation.dashboard import load_application_dashboards
from stockfinder.presentation.dashboard_renderer import render_dashboard
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext
from stockfinder.scan import (
    ensure_rotation_columns,
    market_scan_model_version,
    refresh_market_scan,
)
from stockfinder.scoring import score_fundamentals
from stockfinder.widgets import built_in_widget_registry

WORKSPACE_PAGES = (
    "Command center",
    "Market pulse",
    "Rotation leaders",
    "Metals",
    "Stocks",
    "Settings",
    "Methodology",
)
WORKSPACE_LABELS = {
    "Command center": "Command Center",
    "Market pulse": "Overview",
    "Rotation leaders": "Industries",
    "Metals": "Metals",
    "Stocks": "Stocks",
    "Settings": "Settings",
    "Methodology": "Methodology",
}
STOCKS_VIEWS = ("Discover", "Research")


@st.cache_resource
def repository() -> Repository:
    return Repository(application_data_dir() / "stockfinder.db")


@st.cache_resource
def scan_snapshot_store() -> ScanSnapshotStore:
    return ScanSnapshotStore(application_data_dir() / "latest_scan")


@st.cache_resource
def gettex_instrument_store() -> GettexInstrumentStore:
    return GettexInstrumentStore(application_data_dir() / "gettex_instruments.csv")


@st.cache_resource
def analysis_config_store() -> AnalysisConfigStore:
    return AnalysisConfigStore(application_data_dir() / "analysis_config.json")


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_analysis(symbol: str) -> AnalysisResult:
    return analyze_security(symbol)


@st.cache_data(ttl=60 * 60 * 3, show_spinner=False)
def cached_news(symbol: str) -> DataResult:
    return get_news(symbol)


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def cached_candidate_fundamentals(symbols: tuple[str, ...]) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        result = get_profile(symbol)
        if result.is_fallback:
            rows.append({"Symbol": symbol, "Fundamental data": "Unavailable"})
            continue
        metrics = fundamental_metrics(result.data)
        score = score_fundamentals(metrics)
        rows.append(
            {
                "Symbol": symbol,
                "Growth": metrics.get("Growth"),
                "Quality": score.value,
                "Financial strength": metrics.get("Stability"),
                "Valuation": metrics.get("Valuation"),
                "Fundamental data": f"{score.completeness:.0f}%",
            }
        )
    return pd.DataFrame(rows).reindex(
        columns=[
            "Symbol",
            "Growth",
            "Quality",
            "Financial strength",
            "Valuation",
            "Fundamental data",
        ]
    )


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def cached_broad_universe(day_key: str, refresh_token: int) -> DataResult:
    del refresh_token
    return get_global_universe(date.fromisoformat(day_key))


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def cached_history_chunk(
    symbols: tuple[str, ...], period: str, refresh_token: int
) -> DataResult:
    del refresh_token
    return get_batch_histories(symbols, period)


def main() -> None:
    st.set_page_config(
        page_title="Stockfinder",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="auto",
    )
    _theme()
    _consume_pending_navigation(st.session_state)
    page, load_mode = _sidebar()

    if page == "Command center":
        _dashboard_page(load_mode)
    elif page == "Market pulse":
        _market_page(load_mode)
    elif page == "Rotation leaders":
        _sector_page(load_mode)
    elif page == "Metals":
        _metals_page()
    elif page == "Stocks":
        _stocks_page(load_mode)
    elif page == "Settings":
        _settings_page()
    else:
        _methodology_page(load_mode)


def _consume_pending_navigation(state: MutableMapping[str, Any]) -> None:
    pending_routes = (
        ("pending_workspace_page", "workspace_page", WORKSPACE_PAGES),
        ("pending_stocks_workspace_view", "stocks_workspace_view", STOCKS_VIEWS),
    )
    for pending_key, active_key, valid_values in pending_routes:
        pending_value = state.pop(pending_key, None)
        if pending_value in valid_values:
            state[active_key] = pending_value


def _sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.markdown('<div class="brand">STOCKFINDER</div>', unsafe_allow_html=True)
        st.caption("Evidence-led market research")
        if st.session_state.get("workspace_page") not in WORKSPACE_PAGES:
            st.session_state["workspace_page"] = "Command center"
        page = st.radio(
            "Navigate",
            WORKSPACE_PAGES,
            key="workspace_page",
            format_func=WORKSPACE_LABELS.get,
        )
        config = analysis_config_store().load()
        profile_names = tuple(config["rule_profiles"])
        if st.session_state.get("active_rule_profile") not in profile_names:
            st.session_state["active_rule_profile"] = profile_names[0]
        st.selectbox(
            "Rule profile",
            profile_names,
            key="active_rule_profile",
            help="Sets the initial stock-screening thresholds.",
        )
        st.divider()
        with st.expander("Data controls"):
            extended = st.toggle(
                "Extended loading",
                help=(
                    "Load two years in smaller batches. This is slower but gives "
                    "more history and isolates provider failures more narrowly."
                ),
            )
            if st.button("Refresh now", width="stretch"):
                _force_market_refresh()
                st.rerun()
            st.caption(
                "Standard: 1 year / 200-symbol batches\n\n"
                "Extended: 2 years / 100-symbol batches"
            )
            st.divider()
            st.markdown("**Broker trading list**")
            gettex_store = gettex_instrument_store()
            gettex_count = len(gettex_store.load())
            st.caption(
                f"{gettex_count:,} verified symbols imported"
                if gettex_count
                else "No broker list imported; availability is not verified."
            )
            st.caption(
                "Availability only: prices, charts, and trade levels continue to "
                "use the displayed Yahoo listing exchange and currency."
            )
            uploaded = st.file_uploader(
                "Broker symbols CSV",
                type="csv",
                key="gettex_broker_csv",
                help=(
                    "CSV must contain Symbol, Ticker, Yahoo Symbol, or "
                    "yahoo_symbol values matching the app's symbols."
                ),
            )
            if st.button(
                "Import broker list",
                disabled=uploaded is None,
                width="stretch",
            ):
                try:
                    imported = gettex_store.import_csv(uploaded.getvalue())
                    st.success(f"Imported {len(imported):,} broker symbols.")
                    st.rerun()
                except ValueError as error:
                    st.error(str(error))
            st.download_button(
                "Download CSV template",
                "Symbol\nSAP.DE\nAAPL\n",
                "broker-symbol-template.csv",
                "text/csv",
                width="stretch",
            )
            if gettex_count and st.button("Clear broker list", width="stretch"):
                gettex_store.clear()
                st.rerun()
        st.caption("Daily data · refreshed after market close")
    return page, "extended" if extended else "standard"


def _dashboard_page(load_mode: str) -> None:
    dashboards = load_application_dashboards()
    registry = built_in_widget_registry()
    registry.validate(dashboards)
    dashboard_names = {dashboard.title: dashboard for dashboard in dashboards}

    _heading("Command center", "Configurable, linked market-analysis widgets")
    if st.session_state.get("active_dashboard") not in dashboard_names:
        st.session_state["active_dashboard"] = next(iter(dashboard_names))
    selected_name = st.segmented_control(
        "Dashboard views",
        tuple(dashboard_names),
        key="active_dashboard",
        label_visibility="collapsed",
        width="stretch",
    )
    dashboard = dashboard_names[selected_name]
    context = AnalysisContext(st.session_state)
    if context.breadcrumb() and st.button("Clear analysis context"):
        context.select("region", None)
        st.rerun()
    services = DashboardServices(
        get_history=get_history,
        analyze_security=cached_analysis,
        load_scan=_load_scan,
        get_analysis_config=analysis_config_store().load,
        save_analysis_config=analysis_config_store().save,
        get_broker_symbols=lambda: set(
            gettex_instrument_store().load()["Symbol"].astype(str)
        ),
        get_risk_profiles=_cached_risk_profiles,
        get_candidate_fundamentals=cached_candidate_fundamentals,
        get_positions=repository().positions,
        get_watchlist=repository().watchlist,
        save_position=repository().save_position,
        delete_position=repository().delete_position,
        save_watchlist=repository().save_watchlist,
        delete_watchlist=repository().delete_watchlist,
        get_active_rule_profile=lambda: str(
            st.session_state.get("active_rule_profile", "Swing")
        ),
        load_mode=load_mode,
    )
    render_dashboard(dashboard, registry, context, services)


def _metals_page() -> None:
    _heading(
        "Metals",
        "Physical-metal proxies ranked by momentum, trend, participation, and risk",
    )
    symbols = (*METAL_PROXIES, METALS_BENCHMARK)
    refresh_token = st.session_state.get("market_refresh_token", 0)
    with st.spinner("Loading one year of metals market history..."):
        result = cached_history_chunk(symbols, "1y", refresh_token)
    if result.warning:
        st.warning(result.warning)
    ranked = analyze_metals(result.data)
    st.caption(
        f"Source: {result.source} · retrieved "
        f"{result.retrieved_at.strftime('%Y-%m-%d %H:%M UTC')} · "
        "exchange-traded proxies, USD"
    )
    if ranked.empty:
        st.error("No metal proxy has enough usable history for analysis.")
        return

    leader = ranked.iloc[0]
    strongest_month = ranked.sort_values("1M %", ascending=False).iloc[0]
    positive_trends = int((ranked["Trend"] >= 65).sum())
    complete = len(ranked)
    leader_column, month_column, breadth_column, coverage_column = st.columns(4)
    leader_column.metric(
        "Composite leader",
        str(leader["Metal"]),
        f"{_score_10(leader['Metal score']):.1f}/10 · {leader['Signal']}",
    )
    month_column.metric(
        "Strongest 1M",
        str(strongest_month["Metal"]),
        f"{strongest_month['1M %']:+.1f}%",
    )
    breadth_column.metric("Positive trends", f"{positive_trends} of {complete}")
    coverage_column.metric(
        "Proxy coverage", f"{complete} of {len(METAL_PROXIES)}"
    )

    pulse_tab, detail_tab, method_tab = st.tabs(
        ["Metals pulse", "Metal detail", "Methodology"]
    )
    with pulse_tab:
        st.plotly_chart(
            _metals_performance_chart(result.data, ranked), width="stretch"
        )
        metal_score_columns = (
            "Momentum",
            "Trend",
            "Relative strength",
            "Participation",
            "Risk resilience",
            "Metal score",
        )
        ranked_display = _display_score_columns(ranked, metal_score_columns)
        st.dataframe(
            ranked_display,
            hide_index=True,
            width="stretch",
            column_config={
                "Price": st.column_config.NumberColumn(format="$%.2f"),
                "Day %": st.column_config.NumberColumn(format="%+.2f%%"),
                "1M %": st.column_config.NumberColumn(format="%+.1f%%"),
                "3M %": st.column_config.NumberColumn(format="%+.1f%%"),
                "6M %": st.column_config.NumberColumn(format="%+.1f%%"),
                "Relative 3M %": st.column_config.NumberColumn(format="%+.1f%%"),
                "Volume ratio": st.column_config.NumberColumn(format="%.2fx"),
                "Volatility %": st.column_config.NumberColumn(format="%.1f%%"),
                "Max drawdown %": st.column_config.NumberColumn(format="%.1f%%"),
                **{
                    column: st.column_config.ProgressColumn(
                        min_value=1, max_value=10, format="%.1f"
                    )
                    for column in metal_score_columns
                },
                "Data completeness %": st.column_config.ProgressColumn(
                    min_value=0, max_value=100, format="%.0f%%"
                ),
            },
        )

    with detail_tab:
        selected_metal = st.selectbox("Metal", ranked["Metal"].tolist())
        selected = ranked[ranked["Metal"] == selected_metal].iloc[0]
        symbol = str(selected["Symbol"])
        score_column, price_column, relative_column, risk_column = st.columns(4)
        score_column.metric(
            "Metal score",
            f"{_score_10(selected['Metal score']):.1f}/10",
            str(selected["Signal"]),
        )
        price_column.metric(
            "Proxy price",
            f"${selected['Price']:,.2f}",
            f"{selected['Day %']:+.2f}% today",
        )
        relative_column.metric(
            "Vs broad commodities · 3M",
            f"{selected['Relative 3M %']:+.1f}%",
        )
        risk_column.metric(
            "Risk resilience",
            f"{_score_10(selected['Risk resilience']):.1f}/10",
            f"{selected['Volatility %']:.1f}% volatility",
        )
        st.write(_metal_summary(selected))
        st.plotly_chart(
            _metal_price_chart(result.data[symbol], selected_metal), width="stretch"
        )
        evidence = pd.DataFrame(
            [
                (
                    pillar,
                    _score_10(selected[pillar]),
                    _score_context(selected[pillar]),
                )
                for pillar in (
                    "Momentum",
                    "Trend",
                    "Relative strength",
                    "Participation",
                    "Risk resilience",
                )
            ],
            columns=["Pillar", "Score", "Threshold context"],
        )
        st.dataframe(
            evidence,
            hide_index=True,
            width="stretch",
            column_config={
                "Score": st.column_config.ProgressColumn(
                    min_value=1, max_value=10, format="%.1f"
                )
            },
        )

    with method_tab:
        st.markdown("### How the metal score works")
        st.write(
            "Momentum combines 1-, 3-, and 6-month returns. Trend checks price "
            "against its 50-day average and whether that average is rising. "
            "Relative strength compares the 3-month return with DBC, a broad "
            "commodity benchmark. Participation combines recent volume with "
            "six-month dollar-volume accumulation. Risk resilience rewards lower "
            "annualized volatility and shallower drawdowns."
        )
        st.write(
            "Available pillars are equally weighted. Missing pillars reduce data "
            "completeness instead of receiving a neutral score. The instruments "
            "are exchange-traded proxies, so returns can differ from spot metal "
            "prices because of fees, structure, liquidity, and tracking effects."
        )
        st.caption(
            "Scores summarize observed market evidence; they are not forecasts or "
            "investment recommendations."
        )


def _metals_performance_chart(
    histories: dict[str, pd.DataFrame], ranked: pd.DataFrame
) -> go.Figure:
    series = {}
    volume_histories = {}
    names = ranked.set_index("Symbol")["Metal"].to_dict()
    for symbol, metal in names.items():
        history = histories.get(symbol)
        if history is None or history.empty:
            continue
        close = history["Close"].dropna().tail(126).copy()
        if isinstance(close.index, pd.DatetimeIndex):
            close.index = close.index.tz_localize(None).normalize()
            close = close[~close.index.duplicated(keep="last")]
        if not close.empty:
            series[str(metal)] = close / close.iloc[0] * 100
            volume_histories[str(metal)] = history.tail(126)
    performance = pd.DataFrame(series)
    figure = price_volume_subplots(row_heights=(0.68, 0.32))
    for metal in performance:
        figure.add_scatter(
            x=performance.index,
            y=performance[metal],
            name=metal,
            row=1,
            col=1,
        )
    add_relative_volume_lines(figure, volume_histories)
    figure.update_layout(
        title="Six-month relative performance and volume",
        height=530,
        hovermode="x unified",
        legend_title_text="",
    )
    figure.update_yaxes(title_text="Growth of 100", row=1, col=1)
    return figure


def _metal_price_chart(history: pd.DataFrame, metal: object) -> go.Figure:
    close = history["Close"].dropna()
    sma50 = close.rolling(50).mean()
    figure = price_volume_subplots()
    figure.add_trace(
        go.Scatter(x=close.index, y=close, name=str(metal)), row=1, col=1
    )
    figure.add_trace(
        go.Scatter(x=sma50.index, y=sma50, name="SMA50"), row=1, col=1
    )
    add_volume_bars(figure, history)
    figure.update_layout(
        title=f"{metal} proxy price, 50-day trend, and volume",
        height=530,
        hovermode="x unified",
    )
    figure.update_yaxes(title_text="USD", row=1, col=1)
    return figure


def _metal_summary(metal: pd.Series) -> str:
    trend = "constructive" if metal["Trend"] >= 65 else "not yet constructive"
    if pd.isna(metal["Relative 3M %"]):
        relative = (
            "not comparable with broad commodities because benchmark data is missing"
        )
    else:
        relative = (
            "outperforming broad commodities"
            if metal["Relative 3M %"] >= 0
            else "underperforming broad commodities"
        )
    participation = (
        "supportive" if metal["Participation"] >= 65 else "mixed or weak"
    )
    return (
        f"{metal['Metal']} has a {str(metal['Signal']).lower()} composite signal. "
        f"Its price trend is {trend}, it is {relative} over three months, and "
        f"volume participation is {participation}."
    )


def _stocks_page(load_mode: str) -> None:
    if st.session_state.get("stocks_workspace_view") not in STOCKS_VIEWS:
        st.session_state["stocks_workspace_view"] = "Discover"
    view = st.segmented_control(
        "Stocks workspace",
        STOCKS_VIEWS,
        key="stocks_workspace_view",
    )
    if view == "Research":
        _research_page()
    else:
        _stocks_discovery_page(load_mode)


def _stocks_discovery_page(load_mode: str) -> None:
    _heading(
        "Stocks",
        "Filter the global market, rank setup evidence, and open full research",
    )
    universe, _, _, candidates, history_warning = _load_scan(load_mode)
    _scan_freshness_notice()
    _scan_coverage_warning(history_warning)
    if candidates.empty:
        st.info("No stocks with sufficient cached history are available.")
        return
    stocks = _stock_discovery_frame(
        universe.data, candidates, _cached_risk_profiles()
    )

    total_column, region_column, sector_column, setup_column = st.columns(4)
    total_column.metric("Filterable stocks", f"{len(stocks):,}")
    region_column.metric("Regions", f"{stocks['Region'].nunique():,}")
    sector_column.metric("Sectors", f"{stocks['Sector'].nunique():,}")
    setup_column.metric(
        "Positive setups", f"{int((stocks['Setup score'] >= 65).sum()):,}"
    )
    st.caption(
        f"{len(universe.data):,} listings in the current market universe. "
        "Filterable rows require at least 170 sessions of usable price history."
    )
    gettex_availability = _gettex_filter_control(stocks, "stocks_gettex_filter")

    search = st.text_input(
        "Search symbol or company", placeholder="AAPL or Apple", key="stocks_search"
    )
    with st.expander("Market and classification filters", expanded=True):
        region_column, sector_column, industry_column, exchange_column = st.columns(4)
        regions = region_column.multiselect(
            "Regions", sorted(stocks["Region"].dropna().unique())
        )
        sectors = sector_column.multiselect(
            "Sectors", sorted(stocks["Sector"].dropna().unique())
        )
        industries = industry_column.multiselect(
            "Industries", sorted(stocks["Industry"].dropna().unique())
        )
        exchanges = exchange_column.multiselect(
            "Exchanges", sorted(stocks["Exchange"].dropna().unique())
        )
    promising_filters = _promising_filter_controls("stocks")
    with st.expander("Price, setup, and risk filters", expanded=True):
        states = st.multiselect(
            "Setup states", sorted(stocks["Setup state"].dropna().unique())
        )
        price_min_column, price_max_column, cap_column = st.columns(3)
        minimum_price = price_min_column.number_input(
            "Minimum price", min_value=0.0, value=0.0, step=5.0
        )
        maximum_price = price_max_column.number_input(
            "Maximum price", min_value=0.0, value=10000.0, step=25.0
        )
        cap_label = cap_column.selectbox(
            "Minimum market cap",
            ["Any", "$300M", "$2B", "$10B", "$50B"],
        )
        minimum_market_cap = {
            "Any": 0.0,
            "$300M": 300e6,
            "$2B": 2e9,
            "$10B": 10e9,
            "$50B": 50e9,
        }[cap_label]
        setup_score_column, risk_column, volatility_column = st.columns(3)
        minimum_setup_display = setup_score_column.slider(
            "Minimum setup score", 1, 10, 1, 1
        )
        minimum_safety = risk_column.slider("Minimum safety score", 1, 10, 2, 1)
        minimum_setup = _raw_score_threshold(minimum_setup_display)
        maximum_risk = _raw_risk_limit(minimum_safety)
        maximum_volatility = volatility_column.slider(
            "Maximum annualized volatility %", 10, 200, 100, 5
        )

    filtered = _filter_market_stocks(
        stocks,
        search=search,
        regions=tuple(regions),
        sectors=tuple(sectors),
        industries=tuple(industries),
        exchanges=tuple(exchanges),
        setup_states=tuple(states),
        minimum_price=minimum_price,
        maximum_price=maximum_price,
        minimum_market_cap=minimum_market_cap,
        minimum_setup=minimum_setup,
        maximum_risk=maximum_risk,
        maximum_volatility=maximum_volatility,
        require_sma50=False,
        require_sma150=False,
    )
    filtered = _filter_gettex_availability(filtered, gettex_availability)
    filtered = _filter_promising_stocks(filtered, **promising_filters)
    sort_label = st.selectbox(
        "Rank by",
        [
            "Setup score",
            "Longest heartbeat base",
            "Nearest SMA50",
            "Fastest-rising SMA50",
            "Strongest volume interest",
            "Market cap",
            "Day performance",
            "Highest safety",
        ],
        key="stocks_candidate_ranking",
    )
    filtered = _rank_promising_stocks(filtered, sort_label)
    st.caption(f"Showing {len(filtered):,} of {len(stocks):,} filterable stocks")
    if filtered.empty:
        st.info("No stocks match the current filters.")
        return

    enrich = st.toggle(
        "Add fundamental scores to the top 50 matches",
        help=(
            "Fetches free company-profile data only for the current shortlist. "
            "Results are cached for six hours."
        ),
    )
    display = filtered.head(250).copy()
    if enrich:
        symbols = tuple(display["Symbol"].head(50))
        with st.spinner(f"Loading fundamentals for {len(symbols)} stocks..."):
            fundamentals = cached_candidate_fundamentals(symbols)
        display = display.merge(fundamentals, on="Symbol", how="left")
    display = _display_score_columns(
        display,
        ("Setup score", "Quality", "Growth", "Financial strength", "Valuation"),
        ("Market risk",),
    ).rename(columns={"Market risk": "Safety", "Risk label": "Risk level"})

    selection = st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        height=650,
        row_height=72,
        key="global_stock_discovery",
        on_select="rerun",
        selection_mode="single-row",
        column_config=_stock_discovery_columns(),
    )
    if len(filtered) > len(display):
        st.caption("The table is capped at the top 250 ranked matches.")
    selected_rows = _selected_rows(selection)
    if selected_rows:
        selected = display.iloc[selected_rows[0]]
        st.session_state["research_symbol"] = str(selected["Symbol"])
        st.session_state["research_listing"] = {
            key: selected.get(key)
            for key in (
                "Symbol",
                "Region",
                "Country",
                "Exchange",
                "Currency",
                "GETTEX",
            )
        }
        st.session_state["pending_stocks_workspace_view"] = "Research"
        st.rerun()


def _stock_discovery_frame(
    universe: pd.DataFrame,
    candidates: pd.DataFrame,
    risk_profiles: pd.DataFrame,
) -> pd.DataFrame:
    market_columns = ["Symbol", "Market cap", "Volume", "Day %"]
    frame = candidates.merge(
        universe[market_columns].drop_duplicates("Symbol"), on="Symbol", how="left"
    )
    if not risk_profiles.empty:
        frame = frame.merge(
            risk_profiles[["Symbol", "Market risk", "Risk label", "ATR %"]],
            on="Symbol",
            how="left",
        )
    else:
        frame["Market risk"] = pd.NA
        frame["Risk label"] = "Unavailable"
        frame["ATR %"] = pd.NA
    return _add_gettex_availability(frame)


def _add_gettex_availability(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    imported = gettex_instrument_store().load()
    if imported.empty:
        enriched["GETTEX"] = "Not verified"
        return enriched
    symbols = set(imported["Symbol"])
    enriched["GETTEX"] = enriched["Symbol"].map(
        lambda symbol: (
            "Available" if str(symbol).upper() in symbols else "Not available"
        )
    )
    return enriched


def _filter_gettex_availability(
    stocks: pd.DataFrame, availability: str
) -> pd.DataFrame:
    if stocks.empty or availability == "All":
        return stocks.copy()
    return stocks[stocks["GETTEX"] == availability].copy()


def _gettex_filter_control(stocks: pd.DataFrame, key: str) -> str:
    statuses = set(stocks["GETTEX"].dropna()) if "GETTEX" in stocks else set()
    options = ["All", *sorted(statuses)]
    return st.segmented_control(
        "Broker availability",
        options,
        default="All",
        key=key,
        help=(
            "Availability comes only from the imported broker symbol list. "
            "Listing exchange is shown separately as the market-data source."
        ),
    ) or "All"


def _stock_discovery_columns() -> dict[str, object]:
    progress = {
        column: st.column_config.ProgressColumn(
            min_value=1, max_value=10, format="%.1f"
        )
        for column in (
            "Setup score",
            "Safety",
            "Quality",
            "Growth",
            "Financial strength",
            "Valuation",
        )
    }
    return {
        "Price · SMA50": st.column_config.ImageColumn(width=240),
        "Price": st.column_config.NumberColumn(format="%.2f"),
        "Day %": st.column_config.NumberColumn(format="%+.2f%%"),
        "Market cap": st.column_config.NumberColumn(format="$%.0f"),
        "Volume": st.column_config.NumberColumn(format="%.0f"),
        "Volatility %": st.column_config.NumberColumn(format="%.1f%%"),
        "Max drawdown %": st.column_config.NumberColumn(format="%.1f%%"),
        "ATR %": st.column_config.NumberColumn(format="%.1f%%"),
        "From pivot %": st.column_config.NumberColumn(format="%+.1f%%"),
        "Breakout volume": st.column_config.NumberColumn(format="%.2fx"),
        "Heartbeat base": st.column_config.CheckboxColumn(disabled=True),
        "Base sessions": st.column_config.NumberColumn(format="%d"),
        "Heartbeat turns": st.column_config.NumberColumn(format="%d"),
        "Near SMA50": st.column_config.CheckboxColumn(disabled=True),
        "Crossed SMA50 recently": st.column_config.CheckboxColumn(disabled=True),
        "Distance to SMA50 %": st.column_config.NumberColumn(format="%+.1f%%"),
        "SMA50 rising": st.column_config.CheckboxColumn(disabled=True),
        "SMA50 slope 20D %": st.column_config.NumberColumn(format="%+.1f%%"),
        "Volume increasing": st.column_config.CheckboxColumn(disabled=True),
        "Volume trend ratio": st.column_config.NumberColumn(format="%.2fx"),
        "GETTEX": st.column_config.TextColumn(
            "Broker availability",
            help="Tradability confirmed by the imported broker symbol list.",
        ),
        **progress,
    }


def _force_market_refresh() -> None:
    st.session_state["market_refresh_token"] = (
        st.session_state.get("market_refresh_token", 0) + 1
    )
    for key in list(st.session_state):
        if isinstance(key, str) and key.startswith("broad_scan_result_"):
            del st.session_state[key]
    st.session_state.pop("scan_risk_profiles", None)
    st.session_state["force_market_refresh"] = True
    clear_market_data_caches()


def _rotation_change_columns():
    return {
        "Momentum change": st.column_config.NumberColumn(
            format="%+.1f",
            help="Short-horizon normalized momentum minus the 3M/6M baseline.",
        ),
        "Liquidity change": st.column_config.NumberColumn(
            format="%+.1f",
            help="Average 1W/1M liquidity score minus the 3M/6M average.",
        ),
        "Recent flow %": st.column_config.NumberColumn(
            format="%+.1f%%",
            help="Average 1W/1M up-day versus down-day dollar-volume balance.",
        ),
        "Above rising SMA150 %": st.column_config.NumberColumn(format="%.1f%%"),
    }


def _early_rotation_columns():
    component_help = {
        "Breadth acceleration": "Members crossing above SMA20 versus 10 sessions ago.",
        "RS inflection": "Recent industry relative-strength change versus the market.",
        "Positive dollar volume": (
            "Abnormal five-day dollar volume, rewarded only with positive price."
        ),
        "Close pressure": "Recent closes near the upper end of each daily range.",
    }
    return {
        "Early rotation score": st.column_config.ProgressColumn(
            min_value=1,
            max_value=10,
            format="%.1f",
            help="Equal-weight composite of four early accumulation signals.",
        ),
        **{
            name: st.column_config.ProgressColumn(
                min_value=1, max_value=10, format="%.1f", help=help_text
            )
            for name, help_text in component_help.items()
        },
    }


def _load_scan(
    load_mode: str,
) -> tuple[DataResult, pd.DataFrame, pd.DataFrame, pd.DataFrame, str | None]:
    config = analysis_config_store().load()
    scan_model_version = market_scan_model_version(config)
    refresh_token = st.session_state.get("market_refresh_token", 0)
    result_key = (
        f"broad_scan_result_{date.today().isoformat()}_{load_mode}_"
        f"{scan_model_version}_{refresh_token}"
    )
    if result_key in st.session_state:
        return st.session_state[result_key]

    if not st.session_state.get("force_market_refresh", False):
        snapshot = scan_snapshot_store().load()
        if (
            snapshot is not None
            and snapshot.mode == load_mode
            and snapshot.model_version == scan_model_version
            and not snapshot.risk_profiles.empty
        ):
            universe_result = DataResult(
                snapshot.universe,
                snapshot.source,
                snapshot.completed_at,
                warning=snapshot.warning,
            )
            industries = ensure_rotation_columns(snapshot.industries)
            result = (
                universe_result,
                snapshot.sectors,
                industries,
                snapshot.candidates,
                snapshot.warning,
            )
            st.session_state[result_key] = result
            st.session_state["scan_snapshot_meta"] = {
                "completed_at": snapshot.completed_at,
                "coverage": snapshot.coverage,
                "mode": snapshot.mode,
                "source": snapshot.source,
            }
            st.session_state["scan_risk_profiles"] = snapshot.risk_profiles
            return result

    with st.status("Preparing broad market scan", expanded=True) as status:
        progress = st.progress(0, text="Waiting for price batches")

        def report(stage: str, completed: int, total: int, usable: int) -> None:
            if stage == "Loading market universe":
                status.write(
                    "Refreshing US membership and curated international listings..."
                )
            elif stage == "Loading price history":
                fraction = completed / total if total else 0
                progress.progress(
                    fraction,
                    text=(
                        f"Price history: {completed:,}/{total:,} symbols · "
                        f"{usable:,} usable"
                    ),
                )
            elif stage != "Complete":
                status.write(stage)

        snapshot = refresh_market_scan(
            config,
            load_mode,
            scan_snapshot_store(),
            as_of=date.today(),
            universe_loader=lambda as_of: cached_broad_universe(
                (as_of or date.today()).isoformat(), refresh_token
            ),
            history_loader=lambda symbols, period: cached_history_chunk(
                symbols, period, refresh_token
            ),
            progress=report,
        )
        progress.progress(
            1.0,
            text=(
                f"Price history complete · {len(snapshot.risk_profiles):,} "
                "usable symbols"
            ),
        )
        status.update(
            label=(
                f"Scan complete · {len(snapshot.industries):,} industries · "
                f"{len(snapshot.candidates):,} filterable stocks"
            ),
            state="complete",
            expanded=False,
        )
    universe_result = DataResult(
        snapshot.universe,
        snapshot.source,
        snapshot.completed_at,
        warning=snapshot.warning,
    )
    st.session_state["scan_snapshot_meta"] = {
        "completed_at": snapshot.completed_at,
        "coverage": snapshot.coverage,
        "mode": load_mode,
        "source": universe_result.source,
    }
    st.session_state["force_market_refresh"] = False
    st.session_state["scan_risk_profiles"] = snapshot.risk_profiles
    result = (
        universe_result,
        snapshot.sectors,
        snapshot.industries,
        snapshot.candidates,
        snapshot.warning,
    )
    st.session_state[result_key] = result
    return result


def _cached_risk_profiles() -> pd.DataFrame:
    profiles = st.session_state.get("scan_risk_profiles")
    if isinstance(profiles, pd.DataFrame):
        return profiles
    snapshot = scan_snapshot_store().load()
    if snapshot is None:
        return pd.DataFrame()
    st.session_state["scan_risk_profiles"] = snapshot.risk_profiles
    return snapshot.risk_profiles


def _market_page(load_mode: str) -> None:
    _heading("Market overview", "Regime, liquidity, and industry rotation in one view")
    st.caption(
        "Built for active rotation decisions rather than a passive buy-and-hold "
        "assumption. Gaining and losing states require price momentum, liquidity, "
        "and recent directional volume to agree."
    )
    symbols = ["SPY", "QQQ", "IWM", "^VIX", "TLT", "GLD"]
    columns = st.columns(6)
    market_histories = {}
    for column, symbol in zip(columns, symbols, strict=True):
        result = get_history(symbol, "1y")
        market_histories[symbol] = result.data
        close = result.data["Close"]
        change = (close.iloc[-1] / close.iloc[-2] - 1) * 100
        column.metric(symbol, f"{close.iloc[-1]:,.2f}", f"{change:+.2f}%")

    for symbol in ("HYG", "IEF", "UUP", "DBC"):
        market_histories[symbol] = get_history(symbol, "1y").data
    regime = classify_market_regime(market_histories)
    regime_column, equity_column, credit_column = st.columns(3)
    regime_column.metric("Market regime", regime.label, f"{regime.score}/4 checks")
    equity_check = regime.checks.get("SPY above rising SMA150", False)
    credit_check = regime.checks.get(
        "High yield outperforming Treasuries over 3M", False
    )
    equity_column.metric("Equity trend", "Supportive" if equity_check else "Defensive")
    credit_column.metric(
        "Credit appetite", "Supportive" if credit_check else "Defensive"
    )
    control_key = {
        "Risk-on": "supportive",
        "Mixed": "neutral",
        "Risk-off": "defensive",
    }.get(regime.label, "defensive")
    control = analysis_config_store().load()["market_controls"][control_key]
    st.subheader("General control plan")
    exposure, position_risk, entry_policy = st.columns([1, 1, 2])
    exposure.metric(
        "Maximum gross exposure", f"{control['max_gross_exposure_pct']:.0f}%"
    )
    position_risk.metric(
        "Risk per position", f"{control['risk_per_position_pct']:.2f}%"
    )
    entry_policy.markdown(f"**New entries**\n\n{control['new_entry_policy']}")
    st.caption(
        "Controls are configurable guardrails for research and position planning, "
        "not personalized investment advice. News and sentiment are not yet inputs."
    )
    with st.expander("Market regime evidence"):
        st.dataframe(
            pd.DataFrame(
                [
                    (name, "Supportive" if passed else "Defensive")
                    for name, passed in regime.checks.items()
                ],
                columns=["Signal", "State"],
            ),
            hide_index=True,
            width="stretch",
        )

    st.subheader("Cross-asset direction")
    cross_asset_rows = []
    for symbol in ("SPY", "IWM", "HYG", "IEF", "TLT", "UUP", "GLD", "DBC"):
        close = market_histories[symbol]["Close"].dropna()
        cross_asset_rows.append(
            (
                symbol,
                (close.iloc[-1] / close.iloc[-22] - 1) * 100,
                (close.iloc[-1] / close.iloc[-64] - 1) * 100,
                "Above"
                if close.iloc[-1] > close.rolling(150).mean().iloc[-1]
                else "Below",
            )
        )
    st.dataframe(
        pd.DataFrame(
            cross_asset_rows,
            columns=["Proxy", "1M %", "3M %", "Versus SMA150"],
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "1M %": st.column_config.NumberColumn(format="%.1f%%"),
            "3M %": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    st.caption(
        "Cross-asset direction and industry accumulation are price/volume proxies. "
        "They do not measure subscriptions, redemptions, or cash flows directly."
    )

    comparison_histories = {
        symbol: market_histories[symbol] for symbol in symbols[:3]
    }
    performance = normalized_performance_from_histories(comparison_histories)
    figure = price_volume_subplots(row_heights=(0.68, 0.32))
    for symbol, color in zip(
        performance,
        ("#49c28a", "#f4c95d", "#4f8edc"),
        strict=True,
    ):
        figure.add_scatter(
            x=performance.index,
            y=performance[symbol],
            name=symbol,
            line={"color": color},
            row=1,
            col=1,
        )
    add_relative_volume_lines(figure, comparison_histories)
    figure.update_layout(height=430, legend_title_text="", hovermode="x unified")
    figure.update_yaxes(title_text="Growth of 100", row=1, col=1)
    st.plotly_chart(figure, width="stretch")

    universe, _, industries, _, history_warning = _load_scan(load_mode)
    risk_profiles = _cached_risk_profiles()
    _scan_freshness_notice()
    _scan_coverage_warning(history_warning)
    st.caption(
        f"{len(universe.data):,} US and curated international listings · "
        f"{len(risk_profiles):,} cached market-risk profiles · "
        "1W, 1M, 3M, and 6M liquidity always analyzed"
    )
    for labels in (("1W", "1M"), ("3M", "6M")):
        horizon_columns = st.columns(2)
        for column, label in zip(horizon_columns, labels, strict=True):
            column.metric(
                f"{label} market liquidity",
                f"{_score_10(industries[f'Liquidity {label}'].mean()):.1f}/10",
                f"Flow {industries[f'Flow {label} %'].mean():+.1f}%",
            )
    losing = industries[industries["Rotation state"] == "Losing"].sort_values(
        ["Momentum change", "Liquidity change"]
    )
    early = industries[
        industries["Early rotation signal"].isin(["Emerging", "Building"])
    ].sort_values("Early rotation score", ascending=False)
    established_winners = industries[industries["Winning"]].sort_values(
        "Rotation score", ascending=False
    )
    early_count, winning_count, losing_count, total_count = st.columns(4)
    early_count.metric("Early rotation", f"{len(early):,}")
    winning_count.metric("Winning industries", f"{len(established_winners):,}")
    losing_count.metric("Losing industries", f"{len(losing):,}")
    total_count.metric("Regional industries", f"{len(industries):,}")
    st.subheader("Industry rotation now")
    st.markdown("**Emerging or building accumulation**")
    early_columns = [
        "Region",
        "Sector",
        "Industry",
        "Early rotation signal",
        "Early rotation score",
        "Breadth acceleration",
        "RS inflection",
        "Positive dollar volume",
        "Close pressure",
    ]
    st.dataframe(
        _display_score_columns(
            early[early_columns].head(15),
            (
                "Early rotation score",
                "Breadth acceleration",
                "RS inflection",
                "Positive dollar volume",
                "Close pressure",
            ),
        ),
        hide_index=True,
        width="stretch",
        column_config=_early_rotation_columns(),
    )
    st.caption(
        "This secondary indicator looks for fresh, broad accumulation before an "
        "industry qualifies as an established winner. It does not replace the "
        "primary rotation state."
    )
    gain_column, loss_column = st.columns(2)
    rotation_columns = [
        "Region",
        "Sector",
        "Industry",
        "Momentum change",
        "Liquidity change",
        "Recent flow %",
        "Above rising SMA150 %",
    ]
    with gain_column:
        st.markdown("**Winning industries**")
        st.dataframe(
            established_winners[rotation_columns].head(10),
            hide_index=True,
            width="stretch",
            column_config=_rotation_change_columns(),
        )
    with loss_column:
        st.markdown("**Losing momentum and liquidity**")
        st.dataframe(
            losing[rotation_columns].head(10),
            hide_index=True,
            width="stretch",
            column_config=_rotation_change_columns(),
        )
    st.caption(
        "Change values compare normalized 1W/1M evidence with 3M/6M evidence. "
        "Positive values indicate acceleration; negative values indicate decay. "
        "Directional volume is a price/volume proxy, not observed fund flow."
    )
    rotation_view = st.segmented_control(
        "Industry direction",
        ["Early", "Winning", "Losing"],
        default="Winning",
        key="market_industry_direction",
    )
    selected_frame = {
        "Early": early,
        "Winning": established_winners,
        "Losing": losing,
    }[rotation_view]
    if not selected_frame.empty:
        _industry_proxy_gallery(
            selected_frame.reset_index(drop=True),
            rotation_view,
            market_histories["SPY"],
        )
    st.subheader("Industry liquidity flow")
    liquidity_score_columns = (
        "Liquidity 1W",
        "Liquidity 1M",
        "Liquidity 3M",
        "Liquidity 6M",
        "Liquidity composite",
        "Rotation score",
        "Early rotation score",
    )
    heatmap_industries = _display_score_columns(
        industries, liquidity_score_columns
    )
    heatmap = px.treemap(
        heatmap_industries,
        path=["Region", "Sector", "Industry"],
        values="Members",
        color="Liquidity composite",
        color_continuous_scale=["#d95d39", "#263238", "#49c28a"],
        range_color=[1, 10],
        hover_data=[
            "Liquidity 1W",
            "Liquidity 1M",
            "Liquidity 3M",
            "Liquidity 6M",
            "Flow 1W %",
            "Flow 1M %",
            "Flow 3M %",
            "Flow 6M %",
            "Momentum change",
            "Liquidity change",
            "Rotation state",
            "Early rotation score",
            "Early rotation signal",
            "Above rising SMA150 %",
        ],
        custom_data=["Region", "Sector", "Industry"],
    )
    heatmap.update_layout(height=560, margin={"t": 15, "l": 0, "r": 0, "b": 0})
    heatmap_selection = st.plotly_chart(
        heatmap,
        width="stretch",
        key="industry_liquidity_heatmap",
        on_select="rerun",
        selection_mode="points",
    )
    st.subheader("Gaining industries with investable trends")
    winning_industries = industries[
        industries["Winning"] & (industries["Rotation state"] == "Gaining")
    ].head(10)
    winning_industries_display = _display_score_columns(
        winning_industries,
        liquidity_score_columns,
    )
    winner_selection = st.dataframe(
        winning_industries_display,
        hide_index=True,
        width="stretch",
        key="market_winning_industries",
        on_select="rerun",
        selection_mode="single-row",
    )
    selected_context = _selected_rotation_context(
        heatmap_selection, winner_selection, winning_industries
    )
    if selected_context:
        st.session_state["selected_rotation_context"] = selected_context
        st.session_state["pending_workspace_page"] = "Rotation leaders"
        st.rerun()
    if st.button("Open rotation leaders", type="primary"):
        st.session_state["pending_workspace_page"] = "Rotation leaders"
        st.rerun()


def _industry_option_label(row: pd.Series) -> str:
    confirmation = " · established winner" if bool(row.get("Winning")) else ""
    return f"{row['Industry']} · {row['Sector']}{confirmation}"


def _industry_proxy(row: pd.Series) -> tuple[str, str]:
    config = analysis_config_store().load()
    region = str(row.get("Listing region", row.get("Region", "United States")))
    industry = str(row["Industry"])
    sector = str(row["Sector"])
    return configured_proxy(config, region, sector, industry)


def _industry_proxy_figure(
    proxy: str, history: pd.DataFrame, benchmark_history: pd.DataFrame
) -> go.Figure:
    close = history["Close"].dropna()
    benchmark = benchmark_history["Close"].dropna()
    normalized = close / close.iloc[0] * 100
    benchmark_normalized = benchmark / benchmark.iloc[0] * 100
    figure = price_volume_subplots()
    figure.add_trace(
        go.Scatter(x=normalized.index, y=normalized, name=proxy, line={"width": 3}),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=normalized.index,
            y=normalized.rolling(50).mean(),
            name="SMA50",
            line={"color": "#2364aa"},
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=normalized.index,
            y=normalized.rolling(150).mean(),
            name="SMA150",
            line={"color": "#d4a017"},
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=benchmark_normalized.index,
            y=benchmark_normalized,
            name="SPY",
            line={"color": "#7d8990", "dash": "dot"},
        ),
        row=1,
        col=1,
    )
    add_volume_bars(figure, history)
    figure.update_layout(
        height=480,
        legend_title_text="",
        hovermode="x unified",
    )
    figure.update_yaxes(title_text="Growth of 100", row=1, col=1)
    return figure


def _industry_proxy_thumbnail(
    proxy: str, label: str, history: pd.DataFrame
) -> go.Figure:
    close = history["Close"].dropna()
    normalized = close / close.iloc[0] * 100
    figure = price_volume_subplots(
        row_heights=(0.76, 0.24), vertical_spacing=0.03
    )
    figure.add_trace(
        go.Scatter(
            x=normalized.index,
            y=normalized,
            name=proxy,
            mode="lines+markers",
            line={"color": "#49c28a", "width": 2},
            marker={"size": 8, "opacity": 0},
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=normalized.index,
            y=normalized.rolling(50).mean(),
            name="SMA50",
            line={"color": "#f4c95d", "width": 1.5},
        ),
        row=1,
        col=1,
    )
    add_volume_bars(figure, history, showlegend=False)
    figure.update_layout(
        title={"text": label, "font": {"size": 14}},
        height=270,
        margin={"t": 42, "l": 12, "r": 12, "b": 12},
        showlegend=False,
        hovermode="x unified",
        clickmode="event+select",
    )
    figure.update_xaxes(showgrid=False, title=None)
    figure.update_yaxes(showgrid=True, title=None, row=1, col=1)
    figure.update_yaxes(showticklabels=False, title=None, row=2, col=1)
    return figure


def _industry_proxy_gallery(
    industries: pd.DataFrame,
    rotation_view: str,
    benchmark_history: pd.DataFrame,
) -> None:
    st.subheader(f"{rotation_view} industry charts")
    entries = []
    proxy_results: dict[str, DataResult] = {}
    for position, row in industries.iterrows():
        proxy, proxy_kind = _industry_proxy(row)
        if proxy not in proxy_results:
            proxy_results[proxy] = get_history(proxy, "1y")
        identity = (
            rotation_view,
            str(row["Region"]),
            str(row["Sector"]),
            str(row["Industry"]),
        )
        entries.append((position, row, proxy, proxy_kind, identity))

    fallback_proxies = [
        proxy for proxy, result in proxy_results.items() if result.is_fallback
    ]
    if fallback_proxies:
        st.warning(
            "Synthetic demonstration data is active for: "
            + ", ".join(fallback_proxies)
        )

    identities = {entry[4] for entry in entries}
    expanded = st.session_state.get("expanded_industry_proxy")
    if expanded not in identities:
        expanded = None
        st.session_state.pop("expanded_industry_proxy", None)

    if expanded:
        _, row, proxy, proxy_kind, _ = next(
            entry for entry in entries if entry[4] == expanded
        )
        with st.container(border=True):
            title_column, close_column = st.columns([8, 1])
            title_column.subheader(
                f"{row['Industry']} · {row['Region']} · {row['Sector']}"
            )
            if close_column.button(
                "Close",
                key="close_industry_proxy_detail",
                width="stretch",
            ):
                st.session_state.pop("expanded_industry_proxy", None)
                st.session_state["proxy_gallery_version"] = (
                    st.session_state.get("proxy_gallery_version", 0) + 1
                )
                st.rerun()
            result = proxy_results[proxy]
            st.plotly_chart(
                _industry_proxy_figure(
                    proxy, result.data, benchmark_history
                ),
                width="stretch",
                key=f"expanded_proxy_{rotation_view}_{proxy}",
            )
            st.caption(
                f"Proxy: {proxy} · {proxy_kind} · Source: {result.source}. The ETF "
                "is a tradable proxy, not the exact equal-weight industry index."
            )

    gallery_version = st.session_state.get("proxy_gallery_version", 0)
    for offset in range(0, len(entries), 3):
        columns = st.columns(3)
        row_entries = entries[offset : offset + 3]
        for column, entry in zip(
            columns[: len(row_entries)], row_entries, strict=True
        ):
            position, row, proxy, _, identity = entry
            result = proxy_results[proxy]
            label = f"{row['Industry']}<br><sup>{proxy} · {row['Region']}</sup>"
            with column:
                event = st.plotly_chart(
                    _industry_proxy_thumbnail(proxy, label, result.data),
                    width="stretch",
                    key=(
                        f"proxy_gallery_{gallery_version}_{rotation_view}_{position}"
                    ),
                    on_select="rerun",
                    selection_mode="points",
                    config={"displayModeBar": False},
                )
                open_detail = st.button(
                    "Open detail",
                    icon=":material/open_in_full:",
                    help=f"Expand {row['Industry']}",
                    key=(
                        f"expand_proxy_{gallery_version}_{rotation_view}_{position}"
                    ),
                    width="stretch",
                )
                if (_selected_points(event) or open_detail) and expanded != identity:
                    st.session_state["expanded_industry_proxy"] = identity
                    st.rerun()


def _industry_browser_frame(
    industries: pd.DataFrame,
    candidates: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Build one row per regional industry with its configured tradable proxy."""
    frame = industries.copy()
    if frame.empty:
        return frame
    stock_counts = (
        candidates.groupby(["Region", "Sector", "Industry"])
        .size()
        .rename("Stocks")
        if not candidates.empty
        else pd.Series(dtype=int, name="Stocks")
    )
    frame = frame.join(stock_counts, on=["Region", "Sector", "Industry"])
    frame["Stocks"] = frame["Stocks"].fillna(0).astype(int)
    proxies = frame.apply(
        lambda row: configured_proxy(
            config,
            str(row.get("Listing region", row["Region"])),
            str(row["Sector"]),
            str(row["Industry"]),
        ),
        axis=1,
    )
    frame["ETF / proxy"] = proxies.map(lambda value: value[0])
    frame["Proxy scope"] = proxies.map(lambda value: value[1])
    return frame


def _filter_industry_browser(
    industries: pd.DataFrame,
    *,
    search: str = "",
    regions: tuple[str, ...] = (),
    sectors: tuple[str, ...] = (),
    states: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Apply only user-selected filters to the industry browser."""
    if industries.empty:
        return industries.copy()
    mask = pd.Series(True, index=industries.index)
    if search.strip():
        query = search.strip()
        mask &= (
            industries["Industry"].str.contains(
                query, case=False, regex=False, na=False
            )
            | industries["Sector"].str.contains(
                query, case=False, regex=False, na=False
            )
            | industries["ETF / proxy"].str.contains(
                query, case=False, regex=False, na=False
            )
        )
    for column, selected in (
        ("Region", regions),
        ("Sector", sectors),
        ("Rotation state", states),
    ):
        if selected:
            mask &= industries[column].isin(selected)
    return industries.loc[mask].copy()


def _stocks_for_industries(
    candidates: pd.DataFrame, industries: pd.DataFrame
) -> pd.DataFrame:
    """Return all analyzed stocks belonging to the visible industry rows."""
    if candidates.empty or industries.empty:
        return candidates.iloc[0:0].copy()
    keys = industries[["Region", "Sector", "Industry"]].drop_duplicates()
    return candidates.merge(keys, on=["Region", "Sector", "Industry"], how="inner")


def _filter_industry_stocks(
    stocks: pd.DataFrame,
    *,
    search: str = "",
    setup_states: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Apply the industry's explicit stock controls without hidden thresholds."""
    if stocks.empty:
        return stocks.copy()
    mask = pd.Series(True, index=stocks.index)
    if search.strip():
        query = search.strip()
        mask &= stocks["Symbol"].str.contains(
            query, case=False, regex=False, na=False
        ) | stocks["Company"].str.contains(query, case=False, regex=False, na=False)
    if setup_states:
        mask &= stocks["Setup state"].isin(setup_states)
    return stocks.loc[mask].copy()


def _sector_page(load_mode: str) -> None:
    _heading(
        "Industries",
        "Browse every industry ETF and stock; apply filters only when useful",
    )
    config = analysis_config_store().load()
    _, _, industries, candidates, history_warning = _load_scan(load_mode)
    _scan_freshness_notice()
    _scan_coverage_warning(history_warning)
    if industries.empty:
        st.info("No industry data is available.")
        return

    browser = _industry_browser_frame(industries, candidates, config)
    st.subheader("1. Filter the universe (optional)")
    st.caption("Leave every control empty to see the complete cached universe.")
    search = st.text_input(
        "Search industry, sector, or ETF",
        placeholder="Semiconductors, Technology, or SMH",
        key="industry_browser_search",
    )
    region_column, sector_column, state_column = st.columns(3)
    regions = region_column.multiselect(
        "Regions",
        sorted(browser["Region"].dropna().astype(str).unique()),
        key="industry_browser_regions",
    )
    sectors = sector_column.multiselect(
        "Sectors",
        sorted(browser["Sector"].dropna().astype(str).unique()),
        key="industry_browser_sectors",
    )
    states = state_column.multiselect(
        "Momentum states",
        sorted(browser["Rotation state"].dropna().astype(str).unique()),
        key="industry_browser_states",
    )
    visible_industries = _filter_industry_browser(
        browser,
        search=search,
        regions=tuple(regions),
        sectors=tuple(sectors),
        states=tuple(states),
    )
    visible_stocks = _stocks_for_industries(candidates, visible_industries)

    st.subheader("2. Industry ETFs")
    st.caption(
        f"Showing {len(visible_industries):,} of {len(browser):,} regional "
        "industries. A sector ETF or regional benchmark is shown when no "
        "dedicated industry ETF is configured."
    )
    industry_columns = [
        column
        for column in (
            "Region",
            "Sector",
            "Industry",
            "ETF / proxy",
            "Proxy scope",
            "Rotation state",
            "Rotation score",
            "Stocks",
        )
        if column in visible_industries
    ]
    st.dataframe(
        _display_score_columns(
            visible_industries[industry_columns], ("Rotation score",)
        ),
        hide_index=True,
        width="stretch",
        height=420,
        column_config={
            "Rotation score": st.column_config.ProgressColumn(
                min_value=1,
                max_value=10,
                format="%.1f",
                help="Composite price, liquidity, flow, and breadth evidence.",
            )
        },
    )

    st.subheader("3. Stocks in the visible industries")
    if visible_stocks.empty:
        st.info("No analyzed stocks match the optional industry filters.")
        return
    stock_search_column, state_filter_column, rank_column = st.columns([2, 2, 1])
    stock_search = stock_search_column.text_input(
        "Search symbol or company",
        placeholder="AAPL or Apple",
        key="industry_stock_search",
    )
    setup_states = state_filter_column.multiselect(
        "Setup states",
        sorted(visible_stocks["Setup state"].dropna().astype(str).unique()),
        key="industry_stock_setup_states",
    )
    rank_label = rank_column.selectbox(
        "Rank by",
        ["Setup score", "Highest safety", "Nearest SMA50"],
        key="industry_candidate_ranking",
    )
    visible_stocks = _filter_industry_stocks(
        visible_stocks,
        search=stock_search,
        setup_states=tuple(setup_states),
    )
    risk_profiles = _cached_risk_profiles()
    if "Market risk" not in visible_stocks and not risk_profiles.empty:
        visible_stocks = visible_stocks.merge(
            risk_profiles[["Symbol", "Market risk", "Risk label", "ATR %"]],
            on="Symbol",
            how="left",
        )
    visible_stocks = _rank_promising_stocks(visible_stocks, rank_label)
    st.caption(
        f"Showing all {len(visible_stocks):,} analyzed stocks that match the "
        "manual filters. Select a row to open full research."
    )
    stock_columns = [
        column
        for column in (
            "Symbol",
            "Company",
            "Region",
            "Sector",
            "Industry",
            "Setup state",
            "Setup score",
            "Price",
            "Distance to SMA50 %",
            "Volatility %",
            "Market risk",
        )
        if column in visible_stocks
    ]
    stocks_display = _display_score_columns(
        visible_stocks[stock_columns],
        ("Setup score",),
        ("Market risk",),
    ).rename(columns={"Market risk": "Safety"})
    selection = st.dataframe(
        stocks_display,
        hide_index=True,
        width="stretch",
        height=650,
        key="industry_stocks",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Setup score": st.column_config.ProgressColumn(
                min_value=1, max_value=10, format="%.1f"
            ),
            "Safety": st.column_config.ProgressColumn(
                min_value=1, max_value=10, format="%.1f"
            ),
        },
    )
    selected_rows = _selected_rows(selection)
    if selected_rows:
        selected = stocks_display.iloc[selected_rows[0]]
        st.session_state["research_symbol"] = str(selected["Symbol"])
        st.session_state["research_listing"] = {
            key: selected.get(key)
            for key in ("Symbol", "Region", "Country", "Exchange", "Currency")
        }
        st.session_state["pending_stocks_workspace_view"] = "Research"
        st.session_state["pending_workspace_page"] = "Stocks"
        st.rerun()


def _scan_freshness_notice() -> None:
    metadata = st.session_state.get("scan_snapshot_meta")
    if not metadata:
        return
    completed_at = metadata["completed_at"].astimezone(UTC)
    st.caption(
        f"Analysis as of {completed_at.strftime('%Y-%m-%d %H:%M UTC')} · "
        f"{metadata['coverage']:.1f}% history coverage · "
        f"{metadata['mode'].title()} mode · {metadata['source']}"
    )


def _scan_coverage_warning(warning: str | None) -> None:
    if not warning:
        return
    if "History coverage:" in warning:
        coverage = warning.rsplit("History coverage:", 1)[-1]
        st.warning(f"Partial market data · History coverage: {coverage}")
    else:
        st.warning(warning)


def _research_page() -> None:
    default_symbol = st.session_state.get("research_symbol") or "NVDA"
    _heading(
        "Stock research", "Fundamentals and risk first, technical confirmation second"
    )
    symbol = st.text_input("Ticker", value=default_symbol, max_chars=12).strip().upper()
    if not symbol:
        return
    with st.spinner(f"Building evidence record for {symbol}..."):
        result = cached_analysis(symbol)
    st.session_state["research_symbol"] = symbol
    _source_notice(result)

    profile = result.profile.data
    name = profile.get("longName", symbol)
    st.subheader(f"{name} · {symbol}")
    listing = st.session_state.get("research_listing", {})
    if isinstance(listing, dict) and symbol == listing.get("Symbol"):
        details = [
            str(listing.get(key))
            for key in ("Exchange", "Country", "Currency")
            if listing.get(key) and not pd.isna(listing.get(key))
        ]
        if details:
            st.caption(" · ".join(details))
    gettex_status = _add_gettex_availability(
        pd.DataFrame({"Symbol": [symbol]})
    ).iloc[0]["GETTEX"]
    st.caption(
        f"Broker availability: {gettex_status} · market data remains from the "
        "listed exchange"
    )
    price, quality = st.columns(2)
    price.metric(
        "Last close",
        f"${result.latest_price:,.2f}",
        f"{result.daily_change:+.2f}%",
        help="Latest daily close and change from the preceding close.",
    )
    quality.metric(
        "Quality",
        f"{_score_10(result.analysis.quality.value):.1f}/10",
        result.analysis.quality.label,
        help=(
            "Higher is better: 1–4.4 weak, 4.5–6.4 neutral, "
            "6.5–7.9 positive, 8+ strong."
        ),
    )
    risk, technical = st.columns(2)
    risk.metric(
        "Safety",
        f"{_safety_score_10(result.analysis.risk.value):.1f}/10",
        result.analysis.risk.label,
        help="Higher is better; 10 indicates the lowest observed market risk.",
    )
    technical.metric(
        "Technical",
        f"{_score_10(result.analysis.technical.value):.1f}/10",
        result.analysis.technical.label,
        help=(
            "Higher is better: 1–4.4 weak, 4.5–6.4 neutral, "
            "6.5–7.9 positive, 8+ strong."
        ),
    )
    volatility = _annualized_volatility(result.history.data)
    st.caption(
        f"Quality: {_score_context(result.analysis.quality.value)} "
        f"Technical: {_score_context(result.analysis.technical.value)} "
        f"Risk: {_score_context(result.analysis.risk.value, risk=True)} "
        f"{_volatility_context(volatility)}"
    )

    st.subheader("Overview")
    _research_overview(result)

    st.divider()
    st.subheader("Price and volume")
    st.plotly_chart(_price_chart(result), width="stretch")

    st.divider()
    st.subheader("Quality and growth")
    _quality_growth_panel(result)

    st.divider()
    st.subheader("Business and moat")
    _business_moat_panel(result.profile.data)

    st.divider()
    st.subheader("Risk and trade plan")
    _risk_panel(result)

    st.divider()
    st.subheader("News and catalysts")
    _news_panel(symbol)

    st.divider()
    st.subheader("Peers")
    _peer_panel(symbol)

    st.divider()
    with st.form("research_watchlist"):
        st.subheader("Add to watchlist")
        notes = st.text_area(
            "Investment thesis", placeholder="Evidence, catalyst, and invalidation..."
        )
        entry, target, stop = st.columns(3)
        active_plan = st.session_state.get(f"active_trade_plan_{symbol}", {})
        entry_price = entry.number_input(
            "Planned entry",
            min_value=0.0,
            value=round(active_plan.get("entry", result.latest_price), 2),
        )
        target_price = target.number_input(
            "Target",
            min_value=0.0,
            value=round(active_plan.get("target", result.latest_price * 1.15), 2),
        )
        stop_price = stop.number_input(
            "Stop",
            min_value=0.0,
            value=round(
                active_plan.get("stop", result.latest_price - 2 * result.atr), 2
            ),
        )
        if st.form_submit_button("Save candidate", type="primary"):
            repository().save_watchlist(
                symbol, notes, entry_price, target_price, stop_price
            )
            st.success(f"{symbol} saved to the watchlist.")


def _research_overview(result: AnalysisResult) -> None:
    profile = result.profile.data
    setup = analyze_long_swing_setup(result.history.data)
    target = profile.get("targetMeanPrice")
    earnings = profile.get("earningsTimestampStart")
    next_earnings = (
        datetime.fromtimestamp(earnings, UTC).strftime("%Y-%m-%d")
        if isinstance(earnings, (int, float))
        else "Unavailable"
    )
    st.markdown(
        f"### Swing setup: {setup.state} · {_score_10(setup.score):.1f}/10"
    )
    st.caption(
        f"{_score_context(setup.score)} The score summarizes 11 trend, base, "
        "pivot, and breakout checks."
    )
    target_column, earnings_column = st.columns(2)
    target_column.metric(
        "Analyst mean target",
        f"${target:,.2f}" if isinstance(target, (int, float)) else "Unavailable",
        (
            f"{(target / result.latest_price - 1) * 100:+.1f}% vs price"
            if isinstance(target, (int, float))
            else None
        ),
    )
    earnings_column.metric("Next earnings", next_earnings)
    st.markdown("**Decision summary**")
    passed = sum(setup.checks.values())
    st.write(
        f"{passed} of {len(setup.checks)} technical setup checks pass. "
        f"Fundamental data is {result.analysis.quality.completeness:.0f}% complete; "
        f"risk data is {result.analysis.risk.completeness:.0f}% complete."
    )
    st.caption(
        "Analyst targets and automated states are evidence inputs, not price "
        "predictions or investment recommendations."
    )


def _quality_growth_panel(result: AnalysisResult) -> None:
    profile = result.profile.data
    pillars = {
        name: score_fundamentals(components)
        for name, components in fundamental_pillar_metrics(profile).items()
    }
    st.subheader("Fundamental scorecard")
    st.caption(
        "The overall quality score is the equal-weight average of available "
        "pillars. Each pillar is the average of its available reported metrics; "
        "missing values are excluded and shown through completeness."
    )
    _score_evidence("Overall fundamental score", result.analysis.quality)
    for start in range(0, len(pillars), 3):
        columns = st.columns(3)
        for column, (name, score) in zip(
            columns, list(pillars.items())[start : start + 3], strict=True
        ):
            column.metric(
                name,
                (
                    f"{_score_10(score.value):.1f}/10"
                    if score.completeness
                    else "Unavailable"
                ),
                score.label if score.completeness else None,
                help=f"Reported metric coverage: {score.completeness:.0f}%.",
            )
    for name, score in pillars.items():
        with st.expander(
            f"{name} evidence · "
            + (
                f"{_score_10(score.value):.1f}/10"
                if score.completeness
                else "Unavailable"
            )
        ):
            if score.completeness:
                st.caption(
                    f"{_score_context(score.value)} Reported metric coverage: "
                    f"{score.completeness:.0f}%."
                )
                st.dataframe(
                    _fundamental_evidence_frame(profile, score),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Score": st.column_config.ProgressColumn(
                            min_value=1, max_value=10, format="%.1f"
                        )
                    },
                )
            else:
                st.info("No reported metrics are available for this pillar.")

    st.subheader("Reported fundamentals")
    fields = [
        (
            "Revenue growth",
            profile.get("revenueGrowth"),
            "percent",
            ">10% is supportive; compare with industry and consistency.",
        ),
        (
            "Earnings growth",
            profile.get("earningsGrowth"),
            "percent",
            ">10% is supportive; volatile or one-off earnings need review.",
        ),
        (
            "Gross margin",
            profile.get("grossMargins"),
            "percent",
            ">50% supports pricing-power evidence; industry norms vary.",
        ),
        (
            "Operating margin",
            profile.get("operatingMargins"),
            "percent",
            ">10% is supportive; compare with direct peers.",
        ),
        (
            "Profit margin",
            profile.get("profitMargins"),
            "percent",
            ">0% means profitable; stability matters more than one period.",
        ),
        (
            "Return on equity",
            profile.get("returnOnEquity"),
            "percent",
            ">15% is supportive unless driven by high leverage.",
        ),
        (
            "Return on assets",
            profile.get("returnOnAssets"),
            "percent",
            ">5% is a useful baseline; asset-heavy industries differ.",
        ),
        (
            "Free cash flow",
            profile.get("freeCashflow"),
            "currency",
            "Positive is supportive; scale against revenue and market value.",
        ),
        (
            "Operating cash flow",
            profile.get("operatingCashflow"),
            "currency",
            "Positive and recurring is supportive.",
        ),
        (
            "Debt to equity",
            profile.get("debtToEquity"),
            "number",
            "Lower is safer; the score maps 20 best to 200 weakest.",
        ),
        (
            "Current ratio",
            profile.get("currentRatio"),
            "number",
            "1.0 covers current liabilities; 1.5–2.5 is generally stronger.",
        ),
        (
            "Trailing P/E",
            profile.get("trailingPE"),
            "number",
            "Lower needs durable earnings; score range is 8 best to 55 weakest.",
        ),
    ]
    frame = pd.DataFrame(
        [
            (label, _format_research_value(value, kind), context)
            for label, value, kind, context in fields
        ],
        columns=["Measure", "Reported value", "How to read it"],
    )
    st.dataframe(frame, hide_index=True, width="stretch")


def _fundamental_evidence_frame(
    profile: dict[str, object], score: Score
) -> pd.DataFrame:
    free_cash_flow = profile.get("freeCashflow")
    total_revenue = profile.get("totalRevenue")
    free_cash_flow_margin = (
        float(free_cash_flow) / float(total_revenue)
        if isinstance(free_cash_flow, (int, float))
        and isinstance(total_revenue, (int, float))
        and total_revenue
        else None
    )
    specifications = {
        "Gross margin": (
            profile.get("grossMargins"),
            "percent",
            "Neutral 32% · Positive 46% · Strong 56%+",
            "Pricing power before operating costs; compare with direct peers.",
        ),
        "Operating margin": (
            profile.get("operatingMargins"),
            "percent",
            "Neutral 14% · Positive 20% · Strong 24%+",
            "Profit retained after normal operating expenses.",
        ),
        "Return on equity": (
            profile.get("returnOnEquity"),
            "percent",
            "Neutral 14% · Positive 20% · Strong 24%+",
            "Return on shareholder capital; high leverage can inflate it.",
        ),
        "Return on assets": (
            profile.get("returnOnAssets"),
            "percent",
            "Neutral 7% · Positive 10% · Strong 12%+",
            "Efficiency of the asset base; asset-heavy industries score lower.",
        ),
        "Revenue growth": (
            profile.get("revenueGrowth"),
            "percent",
            "Neutral 10% · Positive 19% · Strong 26%+",
            "Top-line expansion; consistency matters more than one period.",
        ),
        "Earnings growth": (
            profile.get("earningsGrowth"),
            "percent",
            "Neutral 10% · Positive 19% · Strong 26%+",
            "Profit growth; review whether it is recurring or one-off.",
        ),
        "Free cash flow margin": (
            free_cash_flow_margin,
            "percent",
            "Neutral 6% · Positive 13% · Strong 18%+",
            "Revenue converted into cash after capital expenditure.",
        ),
        "Positive free cash flow": (
            free_cash_flow,
            "currency",
            "Positive = 10 · Zero or negative = 1",
            "Cash remaining after operations and capital expenditure.",
        ),
        "Positive operating cash flow": (
            profile.get("operatingCashflow"),
            "currency",
            "Positive = 10 · Zero or negative = 1",
            "Cash generated by normal business operations.",
        ),
        "Debt to equity": (
            profile.get("debtToEquity"),
            "number",
            "Neutral ≤119 · Positive ≤83 · Strong ≤56",
            "Lower leverage generally improves financial resilience.",
        ),
        "Current ratio": (
            profile.get("currentRatio"),
            "number",
            "Neutral 1.5 · Positive 1.8 · Strong 2.1+",
            "Ability to cover short-term liabilities with current assets.",
        ),
        "Trailing P/E": (
            profile.get("trailingPE"),
            "number",
            "Neutral ≤34 · Positive ≤25 · Strong ≤17",
            "Price paid for trailing earnings; durability still matters.",
        ),
        "Forward P/E": (
            profile.get("forwardPE"),
            "number",
            "Neutral ≤28 · Positive ≤21 · Strong ≤15",
            "Price paid for estimated earnings; forecasts can change.",
        ),
        "Price to book": (
            profile.get("priceToBook"),
            "number",
            "Neutral ≤6.0 · Positive ≤4.2 · Strong ≤2.8",
            "Market value relative to net assets; sector relevance varies.",
        ),
        "Dividend yield": (
            profile.get("dividendYield"),
            "percent",
            "Neutral 2.7% · Positive 3.9% · Strong 4.8%+",
            "Current income yield; a high yield can signal elevated risk.",
        ),
        "Payout sustainability": (
            profile.get("payoutRatio"),
            "percent",
            "Neutral ≤61% · Positive ≤48% · Strong ≤38%",
            "Lower payout leaves more earnings to absorb shocks and reinvest.",
        ),
    }
    rows = []
    for component, normalized_score in score.components.items():
        raw_value, kind, thresholds, interpretation = specifications[component]
        rows.append(
            (
                component,
                _format_research_value(raw_value, kind),
                _score_10(normalized_score),
                thresholds,
                interpretation,
            )
        )
    return pd.DataFrame(
        rows,
        columns=[
            "Measure",
            "Reported value",
            "Score",
            "Threshold context",
            "Why it matters",
        ],
    )


def _business_moat_panel(profile: dict[str, object]) -> None:
    summary = profile.get("longBusinessSummary")
    st.subheader("Business model")
    st.write(summary or "Business description is unavailable from the current source.")
    website = profile.get("website")
    if isinstance(website, str) and website:
        st.link_button("Company website", website)

    signals = [
        ("Gross margin", profile.get("grossMargins"), 0.50, "percent"),
        ("Operating margin", profile.get("operatingMargins"), 0.10, "percent"),
        ("Return on equity", profile.get("returnOnEquity"), 0.15, "percent"),
        ("Revenue growth", profile.get("revenueGrowth"), 0.10, "percent"),
        ("Positive free cash flow", profile.get("freeCashflow"), 0.0, "currency"),
    ]
    rows = []
    for label, value, threshold, kind in signals:
        available = isinstance(value, (int, float))
        rows.append(
            (
                label,
                _format_research_value(value, kind),
                "Supportive"
                if available and value > threshold
                else "Weak / unavailable",
            )
        )
    st.subheader("Moat evidence proxies")
    st.dataframe(
        pd.DataFrame(rows, columns=["Signal", "Evidence", "Interpretation"]),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "These quantitative signals may support pricing power or financial "
        "durability. They do not establish a competitive moat; qualitative "
        "research on switching costs, network effects, IP, brand, and regulation "
        "is still required."
    )


def _news_panel(symbol: str) -> None:
    result = cached_news(symbol)
    if result.warning:
        st.warning(result.warning)
    if result.data.empty:
        st.info("No recent news is available from the current provider.")
        return
    news = result.data.head(10).copy()
    news["Published"] = pd.to_datetime(news["Published"], errors="coerce").dt.strftime(
        "%Y-%m-%d %H:%M"
    )
    for article in news.itertuples(index=False):
        if article.URL:
            st.markdown(f"#### [{article.Title}]({article.URL})")
        else:
            st.markdown(f"#### {article.Title}")
        st.caption(f"{article.Published} · {article.Publisher}")
        if article.Summary:
            st.write(article.Summary)
        st.divider()
    st.caption(
        f"Source: {result.source} · retrieved "
        f"{result.retrieved_at.strftime('%Y-%m-%d %H:%M UTC')}"
    )


def _format_research_value(value: object, kind: str) -> str:
    if not isinstance(value, (int, float)):
        return "Unavailable"
    if kind == "percent":
        return f"{value * 100:+.1f}%"
    if kind == "currency":
        return f"${value:,.0f}"
    return f"{value:,.2f}"


def _annualized_volatility(history: pd.DataFrame) -> float:
    returns = history["Close"].pct_change().dropna()
    return float(returns.std() * (252**0.5) * 100) if not returns.empty else 0.0


def _candidate_volatility_context(value: object) -> str:
    if not isinstance(value, (int, float)) or pd.isna(value):
        return "Unavailable"
    return _volatility_context(float(value), concise=True)


def _candidate_score_context(value: object) -> str:
    if not isinstance(value, (int, float)) or pd.isna(value):
        return "Unavailable"
    return _score_context(float(value), concise=True)


def _fundamental_signal(row: pd.Series) -> str:
    values = pd.to_numeric(
        pd.Series(
            [row.get("Quality"), row.get("Growth"), row.get("Financial strength")]
        ),
        errors="coerce",
    ).dropna()
    if values.empty:
        return "Unavailable"
    peak = float(values.max())
    if peak >= 80:
        return "Strong"
    if peak >= 65:
        return "Positive"
    return "Weak"


def _filter_market_stocks(
    stocks: pd.DataFrame,
    *,
    search: str = "",
    regions: tuple[str, ...] = (),
    sectors: tuple[str, ...] = (),
    industries: tuple[str, ...] = (),
    exchanges: tuple[str, ...] = (),
    setup_states: tuple[str, ...] = (),
    minimum_price: float = 0.0,
    maximum_price: float = float("inf"),
    minimum_market_cap: float = 0.0,
    minimum_setup: float = 0.0,
    maximum_risk: float = 100.0,
    maximum_volatility: float = float("inf"),
    require_sma50: bool = False,
    require_sma150: bool = False,
) -> pd.DataFrame:
    """Apply composable discovery filters to cached global stock evidence."""
    if stocks.empty:
        return stocks.copy()
    mask = pd.Series(True, index=stocks.index)
    if search:
        query = search.strip()
        mask &= stocks["Symbol"].str.contains(
            query, case=False, regex=False, na=False
        ) | stocks["Company"].str.contains(query, case=False, regex=False, na=False)
    for column, selected in (
        ("Region", regions),
        ("Sector", sectors),
        ("Industry", industries),
        ("Exchange", exchanges),
        ("Setup state", setup_states),
    ):
        if selected:
            mask &= stocks[column].isin(selected)
    mask &= stocks["Price"].between(minimum_price, maximum_price)
    mask &= stocks["Market cap"].fillna(0) >= minimum_market_cap
    mask &= stocks["Setup score"].fillna(0) >= minimum_setup
    mask &= stocks["Market risk"].fillna(100) <= maximum_risk
    mask &= stocks["Volatility %"].fillna(float("inf")) <= maximum_volatility
    if require_sma50:
        mask &= stocks["Price above SMA50"].fillna(False)
    if require_sma150:
        mask &= stocks["Price above SMA150"].fillna(False)
    return stocks.loc[mask].copy()


PROMISING_CRITERIA = (
    "Heartbeat consolidation",
    "SMA50 breakout opportunity",
    "Rising SMA50",
    "Increasing volume",
    "Above SMA150 (long-term)",
)


def _promising_filter_controls(key_prefix: str) -> dict[str, object]:
    with st.expander("Promising stock criteria", expanded=True):
        criteria_column, policy_column = st.columns([2, 1])
        criteria = criteria_column.multiselect(
            "Evidence criteria",
            PROMISING_CRITERIA,
            default=[],
            key=f"{key_prefix}_promising_criteria",
            help="Select one or more evidence signals to include in the filter.",
        )
        match_policy = policy_column.segmented_control(
            "Match",
            ["Any selected", "All selected"],
            default="Any selected",
            key=f"{key_prefix}_promising_match_policy",
            help=(
                "Any selected keeps a stock when at least one criterion passes. "
                "All selected requires every selected criterion."
            ),
        )
        base_column, sma50_column, volume_column = st.columns(3)
        minimum_base_sessions = base_column.slider(
            "Minimum base length",
            5,
            20,
            10,
            1,
            key=f"{key_prefix}_minimum_base_sessions",
            disabled="Heartbeat consolidation" not in criteria,
            help=(
                "Longer controlled bases receive preference; the scan tests "
                "5–20 sessions."
            ),
        )
        maximum_sma50_distance = sma50_column.slider(
            "Maximum distance to SMA50 %",
            1.0,
            10.0,
            5.0,
            0.5,
            key=f"{key_prefix}_maximum_sma50_distance",
            disabled="SMA50 breakout opportunity" not in criteria,
            help=(
                "Absolute distance above or below SMA50; smaller is nearer to "
                "crossing."
            ),
        )
        minimum_volume_ratio = volume_column.slider(
            "Minimum volume trend",
            1.0,
            2.0,
            1.1,
            0.05,
            key=f"{key_prefix}_minimum_volume_ratio",
            disabled="Increasing volume" not in criteria,
            help=(
                "Recent 10-day average volume divided by the preceding 40-day "
                "average."
            ),
        )
        st.caption(
            "Heartbeat requires a controlled ≤15% base with at least two price "
            "direction changes. SMA150 is optional and intended for longer-term "
            "investing rather than the core swing setup."
        )
    return {
        "criteria": tuple(criteria),
        "require_all": match_policy == "All selected",
        "minimum_base_sessions": minimum_base_sessions,
        "maximum_sma50_distance": maximum_sma50_distance,
        "minimum_volume_ratio": minimum_volume_ratio,
    }


def _filter_promising_stocks(
    stocks: pd.DataFrame,
    criteria: tuple[str, ...],
    require_all: bool = False,
    minimum_base_sessions: int = 7,
    maximum_sma50_distance: float = 5.0,
    minimum_volume_ratio: float = 1.10,
) -> pd.DataFrame:
    """Require only the independently selected promising-stock evidence."""
    if stocks.empty or not criteria:
        return stocks.copy()
    evidence = []
    if "Heartbeat consolidation" in criteria:
        evidence.append(
            stocks["Heartbeat base"].fillna(False)
            & (stocks["Base sessions"].fillna(0) >= minimum_base_sessions)
        )
    if "SMA50 breakout opportunity" in criteria:
        evidence.append(
            stocks["Distance to SMA50 %"].abs().fillna(float("inf"))
            <= maximum_sma50_distance
        )
    if "Rising SMA50" in criteria:
        evidence.append(stocks["SMA50 rising"].fillna(False))
    if "Increasing volume" in criteria:
        evidence.append(
            stocks["Volume trend ratio"].fillna(0) >= minimum_volume_ratio
        )
    if "Above SMA150 (long-term)" in criteria:
        evidence.append(stocks["Price above SMA150"].fillna(False))
    evidence_frame = pd.concat(evidence, axis=1)
    mask = evidence_frame.all(axis=1) if require_all else evidence_frame.any(axis=1)
    return stocks.loc[mask].copy()


def _rank_promising_stocks(stocks: pd.DataFrame, ranking: str) -> pd.DataFrame:
    if stocks.empty:
        return stocks.copy()
    if ranking == "Nearest SMA50":
        return stocks.loc[
            stocks["Distance to SMA50 %"].abs().sort_values().index
        ].copy()
    column, ascending = {
        "Setup score": ("Setup score", False),
        "Longest heartbeat base": ("Base sessions", False),
        "Fastest-rising SMA50": ("SMA50 slope 20D %", False),
        "Strongest volume interest": ("Volume trend ratio", False),
        "Market cap": ("Market cap", False),
        "Day performance": ("Day %", False),
        "Highest safety": ("Market risk", True),
    }[ranking]
    return stocks.sort_values(column, ascending=ascending, na_position="last")


def _filter_technical_candidates(
    stocks: pd.DataFrame,
    states: tuple[str, ...],
    minimum_setup: float,
    minimum_volume: float,
    maximum_volatility: float,
    maximum_risk: float,
    maximum_base_width: float,
    maximum_pivot_distance: float,
    require_sma50: bool,
    require_sma150: bool,
    require_volume: bool,
    require_base: bool,
) -> pd.DataFrame:
    mask = (
        stocks["Setup state"].isin(states)
        & (stocks["Setup score"] >= minimum_setup)
        & (stocks["Volatility %"] <= maximum_volatility)
    )
    if "Market risk" in stocks:
        mask &= stocks["Market risk"].isna() | (
            stocks["Market risk"] <= maximum_risk
        )
    for enabled, column in (
        (require_sma50, "Price above SMA50"),
        (require_sma150, "Price above SMA150"),
        (require_volume, "Volume Evidence"),
        (require_base, "Consolidation base"),
    ):
        if enabled:
            mask &= stocks[column].fillna(False).astype(bool)
    if require_volume:
        mask &= stocks["Breakout volume"] >= max(1.5, minimum_volume)
    if require_base:
        mask &= (stocks["Base range %"] <= maximum_base_width) & (
            stocks["From pivot %"].abs() <= maximum_pivot_distance
        )
    return stocks.loc[mask].copy()


def _filter_fundamental_candidates(
    stocks: pd.DataFrame,
    attributes: tuple[str, ...],
    minimum_score: float,
    require_all: bool,
) -> pd.DataFrame:
    if not attributes:
        return stocks.copy()
    evidence = stocks[list(attributes)].apply(pd.to_numeric, errors="coerce")
    passes = evidence.ge(minimum_score)
    mask = passes.all(axis=1) if require_all else passes.any(axis=1)
    return stocks.loc[mask].copy()


def _volume_signal(value: object) -> str:
    if not isinstance(value, (int, float)) or pd.isna(value):
        return "Unavailable"
    ratio = float(value)
    if ratio >= 1.5:
        return "Confirmed spike"
    if ratio >= 1.0:
        return "Building"
    return "Unconfirmed"


def _volatility_context(volatility: float, concise: bool = False) -> str:
    if volatility < 20:
        band, sizing = "Low", "price movement is relatively contained"
    elif volatility < 35:
        band, sizing = "Moderate", "allow normal room around technical levels"
    elif volatility < 50:
        band, sizing = "High", "wider stops and fewer shares may be needed"
    else:
        band, sizing = "Very high", "expect large swings; reduce size materially"
    if concise:
        return f"{band} ({volatility:.1f}% annualized)"
    return f"Volatility: {band} at {volatility:.1f}% annualized; {sizing}."


def _score_10(value: object) -> float:
    """Convert an internal 0-100 strength score to a displayed 1-10 score."""
    if not isinstance(value, (int, float)) or pd.isna(value):
        return float("nan")
    return round(max(1.0, min(10.0, float(value) / 10)), 1)


def _safety_score_10(value: object) -> float:
    """Convert an internal 0-100 risk score to safety where 10 is best."""
    if not isinstance(value, (int, float)) or pd.isna(value):
        return float("nan")
    return round(max(1.0, min(10.0, 10 - float(value) / 10)), 1)


def _raw_score_threshold(value: float) -> float:
    return 0.0 if value <= 1 else min(100.0, value * 10)


def _raw_risk_limit(value: float) -> float:
    return 100.0 if value <= 1 else max(0.0, (10 - value) * 10)


def _display_score_columns(
    frame: pd.DataFrame,
    score_columns: tuple[str, ...] = (),
    risk_columns: tuple[str, ...] = (),
) -> pd.DataFrame:
    display = frame.copy()
    for column in score_columns:
        if column in display:
            display[column] = display[column].map(_score_10)
    for column in risk_columns:
        if column in display:
            display[column] = display[column].map(_safety_score_10)
    return display


def _score_context(value: float, risk: bool = False, concise: bool = False) -> str:
    if risk:
        bands = [(80, "High"), (60, "Elevated"), (35, "Moderate"), (0, "Low")]
        display = _safety_score_10(value)
    else:
        bands = [(80, "Strong"), (65, "Positive"), (45, "Neutral"), (0, "Weak")]
        display = _score_10(value)
    label = next(name for minimum, name in bands if value >= minimum)
    score_name = "Safety" if risk else "Score"
    if concise:
        return f"{label} · {display:.1f}/10"
    suffix = "risk" if risk else "evidence"
    return f"{score_name} {display:.1f}/10 · {label.lower()} {suffix}."


def _settings_page() -> None:
    _heading(
        "Analysis settings",
        "Regional mappings, market controls, and rule profiles",
    )
    store = analysis_config_store()
    config = store.load()

    st.subheader("Geography")
    geography_options = {
        "Listing region": "listing_region",
        "Company domicile": "company_domicile",
    }
    current_label = next(
        label
        for label, value in geography_options.items()
        if value == config["geography_dimension"]
    )
    selected_label = st.segmented_control(
        "Sector and industry grouping",
        tuple(geography_options),
        default=current_label,
    )
    if (
        selected_label
        and geography_options[selected_label] != config["geography_dimension"]
    ):
        config["geography_dimension"] = geography_options[selected_label]
        store.save(config)
        _force_market_refresh()
        st.rerun()

    st.subheader("Rule profiles")
    profile_name = st.selectbox("Profile to edit", tuple(config["rule_profiles"]))
    profile = config["rule_profiles"][profile_name]
    with st.form("rule_profile_editor"):
        setup, volatility = st.columns(2)
        minimum_setup = setup.number_input(
            "Minimum setup score (0-100)",
            0,
            100,
            int(profile["minimum_setup_score"]),
        )
        maximum_volatility = volatility.number_input(
            "Maximum annualized volatility %",
            0,
            100,
            int(profile["maximum_volatility_pct"]),
        )
        safety, fundamental = st.columns(2)
        minimum_safety = safety.number_input(
            "Minimum safety score (0-100)",
            0,
            100,
            int(profile["minimum_safety_score"]),
        )
        minimum_fundamental = fundamental.number_input(
            "Minimum fundamental score (0-100)",
            0,
            100,
            int(profile["minimum_fundamental_score"]),
        )
        require_sma150 = st.checkbox(
            "Require price above SMA150",
            value=bool(profile["require_above_sma150"]),
        )
        if st.form_submit_button("Save rule profile", type="primary"):
            profile.update(
                {
                    "minimum_setup_score": minimum_setup,
                    "maximum_volatility_pct": maximum_volatility,
                    "minimum_safety_score": minimum_safety,
                    "minimum_fundamental_score": minimum_fundamental,
                    "require_above_sma150": require_sma150,
                }
            )
            store.save(config)
            st.success(f"Saved {profile_name} profile.")

    st.subheader("Market control bands")
    controls = pd.DataFrame.from_dict(config["market_controls"], orient="index")
    controls.index.name = "Regime"
    edited_controls = st.data_editor(
        controls.reset_index(),
        hide_index=True,
        width="stretch",
        disabled=["Regime"],
        column_config={
            "max_gross_exposure_pct": st.column_config.NumberColumn(
                "Maximum gross exposure %", min_value=0, max_value=100
            ),
            "risk_per_position_pct": st.column_config.NumberColumn(
                "Risk per position %", min_value=0.0, max_value=100.0
            ),
            "new_entry_policy": st.column_config.TextColumn("New-entry policy"),
        },
    )
    if st.button("Save market controls"):
        config["market_controls"] = edited_controls.set_index("Regime").to_dict(
            orient="index"
        )
        store.save(config)
        st.success("Saved market control bands.")

    st.subheader("Regional ETF and index proxies")
    region = st.selectbox("Region mapping", tuple(config["regional_proxies"]))
    mapping = config["regional_proxies"][region]
    with st.form("regional_proxy_editor"):
        benchmark = st.text_input("Regional benchmark", value=mapping["benchmark"])
        sectors_json = st.text_area(
            "Sector mappings (JSON)",
            value=json.dumps(mapping.get("sectors", {}), indent=2, sort_keys=True),
            height=180,
        )
        industries_json = st.text_area(
            "Industry mappings (JSON)",
            value=json.dumps(mapping.get("industries", {}), indent=2, sort_keys=True),
            height=220,
        )
        if st.form_submit_button("Save regional proxies", type="primary"):
            try:
                config["regional_proxies"][region] = {
                    "benchmark": benchmark.strip().upper(),
                    "sectors": json.loads(sectors_json),
                    "industries": json.loads(industries_json),
                }
                store.save(config)
                st.success(f"Saved {region} proxy mappings.")
            except (json.JSONDecodeError, ValueError) as error:
                st.error(str(error))

    st.download_button(
        "Download configuration",
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        "stockfinder-analysis-config.json",
        "application/json",
    )
    if st.button("Reset all analysis settings"):
        store.reset()
        _force_market_refresh()
        st.rerun()


def _methodology_page(load_mode: str) -> None:
    _heading("Methodology", "Transparent assumptions, controls, and known limits")
    st.subheader("Current profile")
    first, second = st.columns(2)
    first.metric("Liquidity windows", "1W · 1M · 3M · 6M")
    second.metric("Data mode", load_mode.title())
    st.subheader("Score policy")
    st.write(
        "All user-facing scores use a 1–10 scale, where 10 is best. Fundamental "
        "quality, safety, and technical confirmation remain separate. Missing "
        "inputs reduce completeness; they are never replaced by an unexplained "
        "average value."
    )
    st.write(
        "The fundamental scorecard groups reported metrics into Quality, Growth, "
        "Cash flow, Stability, Valuation, and Dividends. Available metrics are "
        "equally weighted within each pillar, and available pillars are equally "
        "weighted in the overall quality score."
    )
    st.write(
        "The broad scan combines classified NASDAQ and NYSE stocks with a curated "
        "set of liquid local listings from Europe, Asia, Asia-Pacific, Canada, "
        "Latin America, and Africa. Regional industries are analyzed separately."
    )
    st.write(
        "Industry liquidity uses aggregate member dollar volume and is always "
        "calculated over one week, one month, three months, and six months. Each "
        "horizon reports liquidity growth and up-day versus down-day flow balance."
    )
    st.write(
        "The active rotation model compares normalized 1W/1M momentum and "
        "liquidity with 3M/6M baselines. An industry is Gaining only when momentum "
        "change, liquidity change, and recent directional volume are all positive; "
        "it is Losing when all three are negative. Other combinations are Mixed."
    )
    st.write(
        "A separate early-rotation indicator looks for breadth accelerating above "
        "SMA20, relative strength inflecting versus the broad market, abnormal "
        "positive dollar volume, and closes near the upper end of their daily "
        "ranges. Emerging requires at least three confirming components; Building "
        "requires two. It is an earlier accumulation proxy, not observed fund flow."
    )
    st.write(
        "An industry is a winner only when its equal-weight price index is above a "
        "rising SMA150, its three- and six-month returns are positive, liquidity "
        "scores confirm in at least three of four horizons, and at least half of "
        "covered members are above rising SMA150. This established-trend flag is "
        "confirmation; stock discovery begins in every Gaining industry."
    )
    st.write(
        "The cached stock pool includes every stock with sufficient history in a "
        "Gaining industry. Promising stock criteria are independent selectable "
        "filters: heartbeat consolidation, SMA50 crossing opportunity, rising "
        "SMA50, increasing volume, and optional price above SMA150. Any selected "
        "keeps stocks matching at least one signal; All selected requires every "
        "chosen signal."
    )
    st.write(
        "Heartbeat requires a controlled base no wider than 15%, at least two "
        "direction changes, and the selected minimum duration. SMA50 opportunity "
        "uses absolute distance above or below SMA50. Rising SMA50 requires a "
        "positive 20-session slope. Increasing volume compares the recent 10-day "
        "average with the preceding 40 days. SMA150 is intended as longer-term "
        "investment confirmation rather than a core swing requirement."
    )
    st.write(
        "Stock research classifies the long swing rule as Ready near pivot, "
        "Price breakout · volume unconfirmed, Breakout confirmed, Developing, or "
        "Reject: trend. Confirmation requires "
        "a close above the adaptive base pivot on at least 1.5x 50-day average "
        "volume, with the close in the upper quarter of the breakout-day range."
    )
    st.write(
        "The suggested entry is the base pivot plus 0.25 ATR. Candidate stops "
        "include an ATR stop, the structural base low, SMA50, the recent swing "
        "low, and a profile-based trailing stop. Shares equal the lesser of the "
        "risk-budget limit and the available-cash limit."
    )
    st.write(
        "Every successful broad scan also persists a market-risk profile for each "
        "usable cached history: last price, daily change, annualized volatility, "
        "maximum drawdown, ATR, swing low, and a price-risk score. Watchlist and "
        "Portfolio use this snapshot without provider requests. Balance-sheet risk, "
        "fundamentals, and moat evidence still require explicit Stock Research."
    )
    st.write(
        "Refresh now clears both provider and processed-scan caches. Standard "
        "loading requests one year in 200-symbol batches; extended loading "
        "requests two years in 100-symbol batches. Progress reports completed and "
        "usable symbols, then aggregation and setup-filtering stages."
    )
    st.subheader("Data providers")
    st.dataframe(
        pd.DataFrame(
            [
                ("Price and volume", "Yahoo Finance", "Synthetic, visibly labeled"),
                ("Company profile", "Yahoo Finance", "Synthetic, visibly labeled"),
                (
                    "US membership",
                    "Nasdaq public stock screener",
                    "Representative US fallback",
                ),
                (
                    "International listings",
                    "Curated Yahoo-compatible symbols",
                    "Licensed global membership provider",
                ),
                ("Broad price history", "Yahoo Finance batches", "Missing excluded"),
                ("Persistence", "Local SQLite", "Hosted database before cloud use"),
            ],
            columns=["Capability", "Current source", "Fallback / next step"],
        ),
        hide_index=True,
        width="stretch",
    )
    st.warning(
        "This is a research tool, not personalized financial advice. Synthetic "
        "fallback data must never be used for a trading decision. International "
        "listing availability and market access depend on your broker."
    )


def _price_chart(result: AnalysisResult) -> go.Figure:
    history = result.history.data.tail(378).copy()
    history["SMA 50"] = history["Close"].rolling(50).mean()
    history["SMA 150"] = history["Close"].rolling(150).mean()
    figure = price_volume_subplots()
    figure.add_trace(
        go.Candlestick(
            x=history.index,
            open=history["Open"],
            high=history["High"],
            low=history["Low"],
            close=history["Close"],
            name="Price",
            increasing_line_color="#0b6e4f",
            decreasing_line_color="#d95d39",
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=history.index,
            y=history["SMA 50"],
            name="SMA 50",
            line={"color": "#2364aa"},
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Scatter(
            x=history.index,
            y=history["SMA 150"],
            name="SMA 150",
            line={"color": "#d4a017"},
        ),
        row=1,
        col=1,
    )
    add_volume_bars(figure, history)
    figure.update_layout(
        height=620, xaxis_rangeslider_visible=False, hovermode="x unified"
    )
    return figure


def _score_evidence(title: str, score: Score) -> None:
    displayed_value = (
        _safety_score_10(score.value)
        if "risk" in title.lower()
        else _score_10(score.value)
    )
    st.markdown(f"**{title}: {displayed_value:.1f}/10 · {score.label}**")
    is_risk = "risk" in title.lower()
    st.caption(
        f"{_score_context(score.value, risk=is_risk)} "
        + (
            "Higher Safety means less observed risk."
            if is_risk
            else "Higher scores mean stronger evidence."
        )
    )
    st.progress(
        score.completeness / 100, text=f"Data completeness {score.completeness:.0f}%"
    )
    if score.components:
        frame = pd.DataFrame(
            [
                (
                    name,
                    _safety_score_10(value) if is_risk else _score_10(value),
                    _score_context(value, risk=is_risk),
                )
                for name, value in score.components.items()
            ],
            columns=["Component", "Score", "Threshold context"],
        )
        st.dataframe(
            frame,
            hide_index=True,
            width="stretch",
            column_config={
                "Score": st.column_config.ProgressColumn(
                    min_value=1, max_value=10, format="%.1f"
                )
            },
        )


def _risk_evidence_frame(result: AnalysisResult) -> pd.DataFrame:
    history = result.history.data
    profile = result.profile.data
    returns = history["Close"].pct_change().dropna()
    volatility = float(returns.std() * (252**0.5)) if not returns.empty else None
    drawdown = history["Close"] / history["Close"].cummax() - 1
    maximum_drawdown = abs(float(drawdown.min())) if not drawdown.empty else None
    specifications = {
        "Volatility": (
            volatility,
            "percent",
            "10% or less = 10 · 70%+ = 1",
            "Higher variability usually requires wider stops and smaller positions.",
        ),
        "Maximum drawdown": (
            maximum_drawdown,
            "percent",
            "5% or less = 10 · 60%+ = 1",
            "Largest observed peak-to-trough decline in the loaded history.",
        ),
        "Balance-sheet leverage": (
            profile.get("debtToEquity"),
            "number",
            "Debt/equity 20 or less = 10 · 220+ = 1",
            "More debt can amplify losses and refinancing pressure.",
        ),
        "Liquidity": (
            profile.get("currentRatio"),
            "number",
            "Current ratio 0.5 = 1 · 2.5+ = 10",
            "Higher short-term asset coverage improves financial flexibility.",
        ),
    }
    rows = []
    for component, normalized_risk in result.analysis.risk.components.items():
        raw_value, kind, thresholds, interpretation = specifications[component]
        rows.append(
            (
                component,
                _format_research_value(raw_value, kind),
                _safety_score_10(normalized_risk),
                thresholds,
                interpretation,
            )
        )
    return pd.DataFrame(
        rows,
        columns=[
            "Measure",
            "Observed value",
            "Safety",
            "Threshold context",
            "Why it matters",
        ],
    )


def _setup_evidence_frame(setup: SwingSetup) -> pd.DataFrame:
    metrics = setup.metrics
    observed = {
        "Price above SMA50": (
            f"${metrics.get('Close', 0):,.2f} vs ${metrics.get('SMA50', 0):,.2f}",
            "Close > SMA50",
            "Confirms price is above its intermediate trend.",
        ),
        "Price above SMA150": (
            f"${metrics.get('Close', 0):,.2f} vs ${metrics.get('SMA150', 0):,.2f}",
            "Close > SMA150",
            "Confirms price is above its long-term trend.",
        ),
        "SMA50 rising": (
            f"{metrics.get('SMA50 slope 20D %', 0):+.1f}% over 20 sessions",
            "> 0%",
            "A rising medium-term average confirms improving trend direction.",
        ),
        "SMA150 rising or flattening after crossover": (
            f"{metrics.get('SMA150 slope 20D %', 0):+.1f}% over 20 sessions",
            "> 0%, or ≥ -1% after bullish crossover",
            "Allows a new trend while rejecting a clearly falling long-term base.",
        ),
        "Prior advance at least 10%": (
            f"{metrics.get('Prior advance %', 0):+.1f}%",
            "≥ 10%",
            "Requires meaningful demand before the consolidation.",
        ),
        "Base range no more than 15%": (
            f"{metrics.get('Base range %', 0):.1f}%",
            "≤ 15%",
            "A tighter base limits volatility before a possible breakout.",
        ),
        "Within 5% below pivot": (
            f"{metrics.get('Distance to pivot %', 0):.1f}% below pivot",
            "0% to 5% below",
            "Keeps a potential entry close to the breakout level.",
        ),
        "Base volume controlled": (
            f"{metrics.get('Base volume ratio', 0):.2f}x prior volume",
            "≤ 1.10x",
            "Contracting volume suggests limited distribution inside the base.",
        ),
        "Breakout above pivot": (
            f"Close ${metrics.get('Close', 0):,.2f} · pivot ${setup.pivot:,.2f}",
            "Close > pivot",
            "Price must clear resistance before a breakout is confirmed.",
        ),
        "Breakout volume at least 1.5x": (
            f"{metrics.get('Breakout volume ratio', 0):.2f}x average",
            "≥ 1.50x",
            "Strong participation reduces the chance of a weak breakout.",
        ),
        "Breakout close in upper quartile": (
            f"{metrics.get('Breakout close location %', 0):.1f}% of daily range",
            "≥ 75%",
            "A strong close shows buyers retained control into the finish.",
        ),
    }
    return pd.DataFrame(
        [
            (
                rule,
                "Pass" if passed else "Fail",
                *observed[rule],
            )
            for rule, passed in setup.checks.items()
        ],
        columns=["Rule", "Result", "Observed", "Threshold", "Why it matters"],
    )


def _risk_panel(result: AnalysisResult) -> None:
    risk_profile = st.segmented_control(
        "Trade risk profile",
        ["Conservative", "Balanced", "Aggressive"],
        default="Balanced",
        key=f"trade_risk_profile_{result.analysis.symbol}",
        help="Controls suggested stop distance and default account risk.",
    ) or "Balanced"
    multiplier = {"Conservative": 1.5, "Balanced": 2.0, "Aggressive": 2.5}[risk_profile]
    setup = analyze_long_swing_setup(result.history.data)
    atr_stop = setup.suggested_entry - multiplier * result.atr
    sma50 = float(result.history.data["Close"].rolling(50).mean().iloc[-1])
    trailing = setup.suggested_entry * (
        1 - {"Conservative": 0.06, "Balanced": 0.09, "Aggressive": 0.12}[risk_profile]
    )
    state, setup_score, pivot = st.columns(3)
    state.metric(
        "Swing-rule state",
        setup.state,
        help="Overall state from the trend, base, pivot, and breakout rules.",
    )
    setup_score.metric(
        "Rule score",
        f"{_score_10(setup.score):.1f}/10",
        help="Composite of 11 setup checks; 6.5+ positive and 8+ strong.",
    )
    pivot.metric(
        "Base pivot",
        f"${setup.pivot:,.2f}",
        help="Highest price in the base; breakout must close above it.",
    )
    volatility = _annualized_volatility(result.history.data)
    atr_percent = result.atr / result.latest_price * 100
    st.caption(
        f"{_score_context(setup.score)} {_volatility_context(volatility)} "
        f"ATR14 is {atr_percent:.1f}% of price, so judge stop distances against "
        "this stock's normal daily range."
    )

    st.subheader("Observed risk evidence")
    st.dataframe(
        _risk_evidence_frame(result),
        hide_index=True,
        width="stretch",
        column_config={
            "Safety": st.column_config.ProgressColumn(
                min_value=1, max_value=10, format="%.1f"
            )
        },
    )
    st.subheader("Setup rule evidence")
    st.dataframe(_setup_evidence_frame(setup), hide_index=True, width="stretch")
    st.subheader("Pattern measurements")
    base_length, base_width, prior_advance, breakout_volume = st.columns(4)
    base_length.metric(
        "Base length",
        f"{setup.metrics.get('Base length sessions', 0):.0f} sessions",
        help="Longest valid base among 5, 7, 10, 15, and 20 sessions.",
    )
    base_width.metric(
        "Base width",
        f"{setup.metrics.get('Base range %', 0):.1f}%",
        help="High-to-low range of the base; no more than 15% passes.",
    )
    prior_advance.metric(
        "Prior advance",
        f"{setup.metrics.get('Prior advance %', 0):+.1f}%",
        help="Price advance before the base; at least 10% passes.",
    )
    breakout_volume.metric(
        "Breakout volume",
        f"{setup.metrics.get('Breakout volume ratio', 0):.2f}x",
        help="Latest volume / 50-day average; at least 1.50x confirms.",
    )
    heartbeat, sma50_distance, sma50_slope, volume_trend = st.columns(4)
    heartbeat.metric(
        "Heartbeat turns",
        f"{setup.metrics.get('Heartbeat turns', 0):.0f}",
        help=(
            "Price-direction reversals inside the selected sideways base; "
            "2+ qualifies."
        ),
    )
    sma50_distance.metric(
        "Distance to SMA50",
        f"{setup.metrics.get('Distance to SMA50 %', 0):+.1f}%",
        (
            "Crossed recently"
            if setup.metrics.get("Crossed SMA50 recently", 0)
            else None
        ),
        help=(
            "Absolute distance up to the chosen threshold indicates a crossing "
            "opportunity."
        ),
    )
    sma50_slope.metric(
        "SMA50 slope · 20D",
        f"{setup.metrics.get('SMA50 slope 20D %', 0):+.1f}%",
        help="Positive means the 50-day average is rising.",
    )
    volume_trend.metric(
        "Volume interest",
        f"{setup.metrics.get('Volume trend ratio', 0):.2f}x",
        help=(
            "Recent 10-day average volume / preceding 40-day average; "
            "1.10x+ qualifies."
        ),
    )

    stop_levels = {
        f"ATR ({multiplier:.1f}x)": atr_stop,
        "Structural base stop": setup.structural_stop,
        "50-day average": sma50,
        "Recent 20-day swing low": result.swing_low,
        "Trailing stop": trailing,
    }
    stops = pd.DataFrame(stop_levels.items(), columns=["Method", "Candidate level"])
    st.dataframe(
        stops,
        hide_index=True,
        width="stretch",
        column_config={
            "Candidate level": st.column_config.NumberColumn(format="$%.2f")
        },
    )
    st.subheader("Position plan")
    account, risk_percent, stop_method = st.columns(3)
    account_size = account.number_input(
        "Account value", min_value=1_000.0, value=100_000.0, step=1_000.0
    )
    default_risk = {"Conservative": 0.25, "Balanced": 0.5, "Aggressive": 1.0}[
        risk_profile
    ]
    risk_budget = risk_percent.slider("Account risk %", 0.25, 3.0, default_risk, 0.25)
    selected_method = stop_method.selectbox("Stop method", list(stop_levels))
    entry_column, stop_column = st.columns(2)
    entry_price = entry_column.number_input(
        "Planned entry",
        min_value=0.01,
        value=round(max(0.01, setup.suggested_entry), 2),
        key=f"plan_entry_{result.analysis.symbol}",
    )
    default_stop = min(entry_price - 0.01, stop_levels[selected_method])
    stop_price = stop_column.number_input(
        "Planned stop",
        min_value=0.0,
        value=round(max(0.0, default_stop), 2),
        key=f"plan_stop_{result.analysis.symbol}_{selected_method}",
    )
    try:
        plan = calculate_position_plan(
            account_size, risk_budget, entry_price, stop_price
        )
    except ValueError as error:
        st.warning(str(error))
        return
    base_low = setup.structural_stop + 0.25 * result.atr
    measured_move = setup.pivot + max(0.0, setup.pivot - base_low)
    risk_per_share = entry_price - stop_price
    target_options = {
        "2R target": entry_price + 2 * risk_per_share,
        "Measured move": measured_move,
    }
    analyst_target = result.profile.data.get("targetMeanPrice")
    if isinstance(analyst_target, (int, float)):
        target_options["Analyst mean target"] = float(analyst_target)
    target_method = st.selectbox("Target method", list(target_options))
    target_price = st.number_input(
        "Planned target",
        min_value=0.01,
        value=round(max(0.01, target_options[target_method]), 2),
        key=f"plan_target_{result.analysis.symbol}_{target_method}",
    )
    try:
        reward_risk = calculate_reward_risk(entry_price, stop_price, target_price)
    except ValueError as error:
        st.warning(str(error))
        reward_risk = None

    shares, loss, value, reward = st.columns(4)
    shares.metric(
        "Shares",
        f"{plan.shares:,}",
        help="Lower of risk-budget shares and cash-affordable shares.",
    )
    loss.metric(
        "Planned loss",
        f"${plan.planned_loss:,.2f}",
        help="Shares × (entry − stop); must stay within the risk budget.",
    )
    value.metric(
        "Position value",
        f"${plan.position_value:,.2f}",
        help="Shares × entry, constrained by the available account value.",
    )
    reward.metric(
        "Reward / risk",
        f"{reward_risk:.2f}R" if reward_risk is not None else "Invalid",
        help="Potential gain / planned loss per share; default minimum is 2R.",
    )
    if reward_risk is not None and reward_risk < 2:
        st.warning("Planned reward/risk is below the default 2R minimum.")
    st.session_state[f"active_trade_plan_{result.analysis.symbol}"] = {
        "entry": entry_price,
        "stop": stop_price,
        "target": target_price,
        "shares": plan.shares,
        "reward_risk": reward_risk,
    }
    st.caption(
        f"Risk budget ${plan.risk_budget:,.2f} · risk/share "
        f"${plan.risk_per_share:,.2f} · risk limit {plan.risk_limited_shares:,} "
        f"shares · cash limit {plan.capital_limited_shares:,} shares"
    )


def _peer_panel(symbol: str) -> None:
    snapshot = scan_snapshot_store().load()
    universe = snapshot.universe if snapshot is not None else SECURITY_UNIVERSE
    row = universe[universe["Symbol"] == symbol]
    if row.empty:
        st.info("This symbol is outside the latest broad-market snapshot.")
        return
    industry = row.iloc[0]["Industry"]
    peers = universe[
        (universe["Industry"] == industry) & (universe["Symbol"] != symbol)
    ].copy()
    if "Market cap" in peers:
        peers = peers.sort_values("Market cap", ascending=False)
    peer_symbols = peers["Symbol"].head(5).tolist()
    symbols = list(dict.fromkeys([symbol, *peer_symbols, "SPY"]))
    st.caption(f"Compared with leading available {industry} peers and SPY.")
    histories = {item: get_history(item, "6mo").data for item in symbols}
    performance = normalized_performance_from_histories(histories)
    figure = price_volume_subplots(row_heights=(0.68, 0.32))
    for item in performance:
        figure.add_scatter(
            x=performance.index,
            y=performance[item],
            name=item,
            row=1,
            col=1,
        )
    add_relative_volume_lines(figure, histories)
    figure.update_layout(height=530, hovermode="x unified")
    figure.update_yaxes(title_text="Growth of 100", row=1, col=1)
    st.plotly_chart(figure, width="stretch")


def _source_notice(result: AnalysisResult) -> None:
    fallbacks = []
    if result.history.is_fallback:
        fallbacks.append("price history")
    if result.profile.is_fallback:
        fallbacks.append("company profile")
    if fallbacks:
        st.error(
            "Synthetic demonstration data is active for "
            + " and ".join(fallbacks)
            + ". Do not use this analysis for a trading decision."
        )
    else:
        timestamp = result.history.retrieved_at.strftime("%Y-%m-%d %H:%M UTC")
        st.caption(f"Source: Yahoo Finance · retrieved {timestamp}")


def _selected_rotation_context(
    heatmap_selection: object,
    winner_selection: object,
    winning_industries: pd.DataFrame,
) -> tuple[str, str, str] | None:
    points = _selected_points(heatmap_selection)
    if points:
        custom_data = points[0].get("customdata") or []
        if len(custom_data) >= 3 and all(custom_data[:3]):
            return tuple(str(value) for value in custom_data[:3])
    rows = _selected_rows(winner_selection)
    if rows:
        row = winning_industries.iloc[rows[0]]
        return str(row["Region"]), str(row["Sector"]), str(row["Industry"])
    return None


def _selected_rows(event: Any) -> list[int]:
    selection = event.get("selection", {})
    return list(selection.get("rows", []))


def _selected_points(event: Any) -> list[dict[str, Any]]:
    selection = event.get("selection", {})
    return list(selection.get("points", []))


def _heading(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="eyebrow">DECISION WORKSPACE</div>
        <h1>{title}</h1>
        <p class="subtitle">{subtitle}</p>
        """,
        unsafe_allow_html=True,
    )


def _theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Newsreader:opsz,wght@6..72,600&display=swap');
        :root {
            --canvas: #0d1418;
            --surface: #151e22;
            --surface-raised: #1a2529;
            --border: #2b3a3e;
            --text: #edf2ef;
            --muted: #a9b7b3;
            --green: #49c28a;
            --amber: #f4c95d;
            --coral: #ff8066;
            color-scheme: dark;
        }
        .stApp {
            background: linear-gradient(135deg, #0d1418 0%, #111b1e 58%, #151a1b 100%);
            color: var(--text);
            font-family: 'DM Sans', sans-serif;
        }
        [data-testid="stAppViewContainer"] > .main {
            background: transparent;
        }
        [data-testid="stHeader"] {
            background: rgba(9, 14, 17, 0.94);
            border-bottom: 1px solid var(--border);
        }
        h1, h2, h3 {
            font-family: 'Newsreader', serif !important;
            color: var(--text) !important;
            letter-spacing: 0 !important;
        }
        h1 { font-size: 2.6rem !important; margin: 0 !important; }
        [data-testid="stSidebar"] {
            background: #101b1e;
            border-right: 1px solid var(--border);
        }
        [data-testid="stSidebar"] * { color: var(--text); }
        [data-testid="stMetric"] {
            border-top: 3px solid var(--green);
            background: rgba(21, 30, 34, 0.66);
            border-bottom: 1px solid var(--border);
            padding: 0.9rem 0;
        }
        [data-testid="stMetricLabel"] p { color: var(--muted) !important; }
        [data-testid="stMetricValue"] { color: var(--text) !important; }
        .brand {
            font-family: 'Newsreader', serif;
            font-size: 1.35rem;
            letter-spacing: 0.08rem;
            color: var(--amber) !important;
            margin: 0.4rem 0 0;
        }
        .eyebrow {
            color: var(--green);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08rem;
            margin-top: 0.5rem;
        }
        .subtitle {
            color: var(--muted);
            margin-top: 0.15rem;
            margin-bottom: 1.7rem;
        }
        [data-testid="stCaptionContainer"] { color: var(--muted); }
        [data-baseweb="input"],
        [data-baseweb="textarea"],
        [data-baseweb="select"] > div {
            background: var(--surface) !important;
            border-color: var(--border) !important;
        }
        [data-baseweb="tab-list"] {
            border-bottom: 1px solid var(--border);
        }
        [data-baseweb="tab"] { color: var(--muted); }
        [aria-selected="true"][data-baseweb="tab"] { color: var(--green); }
        .st-key-active_dashboard [data-testid="stButtonGroup"] {
            border-bottom: 1px solid var(--border);
            margin-bottom: 1.25rem;
        }
        .st-key-active_dashboard [data-testid="stButtonGroup"] > div {
            gap: 1.75rem;
            justify-content: flex-start;
            flex-wrap: wrap;
        }
        .st-key-active_dashboard button {
            background: transparent !important;
            border: 0 !important;
            border-bottom: 3px solid transparent !important;
            border-radius: 0 !important;
            color: var(--muted) !important;
            font-family: 'Newsreader', serif !important;
            font-size: 1.15rem !important;
            font-weight: 600 !important;
            padding: 0.6rem 0 0.45rem !important;
        }
        .st-key-active_dashboard button[aria-checked="true"] {
            border-bottom-color: var(--green) !important;
            color: var(--text) !important;
        }
        .st-key-active_dashboard button:hover {
            color: var(--text) !important;
        }
        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {
            background: var(--green);
            border-color: var(--green);
            color: #07120d;
        }
        .stButton > button[kind="secondary"],
        .stDownloadButton > button {
            background: var(--surface-raised);
            border-color: var(--border);
            color: var(--text);
        }
        [data-testid="stDataFrame"] {
            border: 1px solid var(--border);
            background: var(--surface);
        }
        hr { border-color: var(--border) !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
